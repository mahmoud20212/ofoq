import { spawn } from 'node:child_process'

const port = process.env.PORT || '3000'
const env = {
  ...process.env,
  NODE_OPTIONS: [process.env.NODE_OPTIONS, '--no-deprecation'].filter(Boolean).join(' '),
  DATABASE_URL: process.env.DATABASE_URL || 'file:./ofoq.db',
  NEXT_DIST_DIR: process.env.NEXT_DIST_DIR || '.next-local',
}

const child = spawn(
  process.execPath,
  ['node_modules/next/dist/bin/next', 'dev', '--port', port, '--hostname', '0.0.0.0'],
  { env, stdio: 'inherit' },
)

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  else process.exit(code ?? 1)
})
