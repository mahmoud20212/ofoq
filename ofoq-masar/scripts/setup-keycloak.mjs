import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../', import.meta.url))
const container = 'ofoq-keycloak-dev'
const realm = 'ofoq-dev'
const clientId = 'ofoq-masar'
const site = 'http://localhost:8000'
const docker = (...args) => execFileSync('docker', ['exec', container, ...args], { encoding: 'utf8', stdio: ['ignore','pipe','pipe'] })
const admin = (...args) => docker('/opt/keycloak/bin/kcadm.sh', ...args)
const adminJson = (args, data) => execFileSync('docker', ['exec','-i',container,'/opt/keycloak/bin/kcadm.sh',...args,'-f','-'], {input:JSON.stringify(data),encoding:'utf8',stdio:['pipe','pipe','pipe']})
try {
 docker('sh','-c','u="${KC_BOOTSTRAP_ADMIN_USERNAME:-$KEYCLOAK_ADMIN}"; p="${KC_BOOTSTRAP_ADMIN_PASSWORD:-$KEYCLOAK_ADMIN_PASSWORD}"; if [ -n "$u" ] && [ -n "$p" ]; then /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user "$u" --password "$p" >/dev/null 2>&1; fi')
 const clients=JSON.parse(admin('get','clients','-r',realm,'-q',`clientId=${clientId}`,'--fields','id,clientId'))
 const existing=clients[0]?.id?JSON.parse(admin('get',`clients/${clients[0].id}`,'-r',realm)):{}
 const config={clientId,enabled:true,publicClient:false,standardFlowEnabled:true,directAccessGrantsEnabled:false,serviceAccountsEnabled:false,frontchannelLogout:false,fullScopeAllowed:false,protocol:'openid-connect',redirectUris:[`${site}/auth/callback/`],webOrigins:[site],attributes:{...existing.attributes,'pkce.code.challenge.method':'S256','post.logout.redirect.uris':`${site}/`,'backchannel.logout.url':'http://host.docker.internal:8000/auth/backchannel-logout/','backchannel.logout.session.required':'true'},defaultClientScopes:['web-origins','acr','profile','email']}
 let id=clients[0]?.id
 if(id)adminJson(['update',`clients/${id}`,'-r',realm],config)
 else id=adminJson(['create','clients','-r',realm,'-i'],config).trim()
 const secret=JSON.parse(admin('get',`clients/${id}/client-secret`,'-r',realm)).value
 if(!secret)throw new Error('No secret')
 const file=resolve(root,'.env.local')
 let env=existsSync(file)?readFileSync(file,'utf8'):''
 const values={MASAR_AUTH_URL:site,KEYCLOAK_ISSUER:'http://localhost:8081/realms/ofoq-dev',KEYCLOAK_CLIENT_ID:clientId,KEYCLOAK_CLIENT_SECRET:secret}
 if(!/^DJANGO_SECRET_KEY=.+/m.test(env))values.DJANGO_SECRET_KEY=randomBytes(48).toString('base64url')
 for(const [key,value] of Object.entries(values)){
  const pattern=new RegExp(`^${key}=.*$`,'m');const line=`${key}=${JSON.stringify(value)}`
  env=pattern.test(env)?env.replace(pattern,()=>line):`${env.trimEnd()}\n${line}\n`
 }
 writeFileSync(file,env,{mode:0o600})
 console.log('Masar client configured. Secrets saved privately; realm and other clients unchanged.')
}catch{console.error('Keycloak setup failed; no secrets printed. Check the existing container and admin session.');process.exitCode=1}
