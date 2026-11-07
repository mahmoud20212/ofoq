# Local Keycloak integration

The public website uses the `ofoq-dev` realm at `http://localhost:8081` and the
confidential OIDC client `ofoq-site`. Payload Admin authentication is independent.

Run the website from this directory with `npm run dev`, then open
`http://localhost:3000`. Use this exact hostname rather than `127.0.0.1` so the
callback and cookie origins match.

## Configuration

`node scripts/setup-keycloak.mjs` configures the existing local Keycloak container,
sets S256 PKCE and the login/account themes, and writes integration secrets to
the ignored `.env.local`. It uses the container's existing admin environment
internally and never prints credentials. It preserves existing users. Restart
the dev server if it was running before environment changes.

For manual configuration, copy `.env.example` to `.env.local` and set a random
`AUTH_SESSION_SECRET` of at least 32 characters and the Keycloak client secret.
Never commit `.env.local`. Register these exact client URLs:

- Redirect URI: `http://localhost:3000/auth/callback`
- Post logout redirect URI: `http://localhost:3000/`
- Web origin: `http://localhost:3000`

The client enables Standard Flow, disables Direct Access Grants and service
accounts, and requires PKCE S256. Registration is enabled on the realm, with
`ofoq-login` for login and `my-account` for account management.

## Routes and sessions

- `/auth/login` and `/auth/register` start Keycloak browser flows.
- `/auth/callback` validates the code, state, nonce and PKCE transaction.
- `/auth/session` returns only public identity fields with `private, no-store`.
- `/auth/my-page` opens the authenticated Keycloak account `myPage`; visitors first sign in.
- `POST /auth/logout` requires the configured site Origin and ends both sessions.

After login or registration, the callback always redirects to the configured
Keycloak `/account/myPage` route. The site serves the landing page and legal pages;
legacy dashboard/account URLs redirect to `/auth/my-page`. Other legacy application
pages return to the landing page, whose navigation scrolls to the relevant sections.

The browser receives an encrypted HttpOnly cookie containing only an opaque
session identifier. Access and refresh tokens live in encrypted server-side
files under `AUTH_SESSION_DIR` (default `.cache/auth-sessions`). The short-lived
authentication transaction has a separate HttpOnly cookie. The standard
Keycloak logout redirect uses an ID token hint, never an access or refresh token.
App sessions have a seven-day absolute limit. Refresh failure removes the session.

This file-backed session store targets the current single-node deployment.
Keep its directory private and persistent, outside publicly served folders.
For multiple application replicas or ephemeral hosting, replace it with a shared
session store before deployment. Expired records are deleted when accessed;
periodically remove old files older than seven days to reclaim unused storage.
Production requires HTTPS for both the website and Keycloak. Set `AUTH_URL`,
`KEYCLOAK_ISSUER`, client URLs and secrets for that environment.

## Verification

- `node node_modules/typescript/bin/tsc --noEmit`
- `npm run build`
- `node scripts/test-keycloak.mjs` with the local website and Keycloak running.

The integration test creates and automatically removes a disposable user. It
checks login, registration page rendering, identity, refresh, logout, invalid
callbacks, callback replay, unsafe return URLs, and cross-origin logout rejection.
The account menu still needs visual verification on desktop and mobile when a
browser automation connection is available.
