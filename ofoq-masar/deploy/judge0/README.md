# Dedicated local Judge0 development service

**Prepared, not running or security-validated.** On 2026-11-18 the Docker CLI and Compose
were installed, but the Linux daemon and docker-desktop WSL2 distribution were stopped.
No daemon, VM, service, boot setting, execution policy or existing container was changed.
The preview database was migrated independently and contains only a password-disabled CLI operator.

## Prerequisites and privilege boundary

The [official 1.13.1 release](https://github.com/judge0/judge0/releases/tag/v1.13.1)
documents Linux, Ubuntu 22.04 and cgroup v1 configuration. It does not establish support
for this stopped Windows/WSL2 environment. Do not alter GRUB/cgroup configuration on a
shared machine to make this recipe run. Use a dedicated Linux development VM/host with
the documented cgroup arrangement, sufficient RAM/storage, and reviewed Docker access.

Upstream marks **both server and workers privileged**. This recipe preserves that actual
requirement rather than pretending an unprivileged unsupported setup is secure. Privileged
containers may affect their Linux host. An internal Docker network, a missing application
bind mount, and isolate limits do NOT establish isolation from a compromised privileged
container. Use a separate disposable VM without Ofoq data, host shares or application secrets.
Review patching, host egress firewall, filesystem and resource isolation before allowing code.

The Judge0 image is fixed to the linux/amd64 manifest verified from the official registry:
`sha256:6b5d6a66aa19a8e878a52ea3c6a560afc1086734d96e2885b561fd5c6018f082`.
It was inspected only, not downloaded or run. PostgreSQL 16.2 and Redis 7.2.4 mirror the
release's deployment reference; these older dependency pins need a security/compatibility
review before deployment. This is not a claim that all images are free of vulnerabilities.

## Files and credentials

- `compose.yaml`: a dedicated compose project/network/volume, no external Ofoq network,
  only API port `127.0.0.1:2359:2358`. Database/Redis have no host port. No app paths mounted.
- `prepare.py init`: generates random API, Redis, PostgreSQL and Rails secrets locally once.
- `.local/`: Git-ignored config, preview SQLite and preview media. Never print `judge0.conf`,
  run `docker compose config` without `--quiet`, or publish Docker inspection/logs containing secrets.
- `manage.ps1`: scoped lifecycle commands; never starts Docker Desktop or changes the OS.
- `educa.judge0_preview_settings`: opt-in CLI settings with fixed preview DB and independent
  files/cache/channels/email. Does not change normal settings or Keycloak.

From the project root on Windows:

```powershell
& .\.venv\Scripts\python.exe -B deploy/judge0/prepare.py init
& .\.venv\Scripts\python.exe -B deploy/judge0/prepare.py preview
docker compose --project-name ofoq-masar-judge0-dev --file deploy/judge0/compose.yaml config --quiet
```

Init is idempotent and preserves existing secrets. Restrict `.local` to the local operator.
`chmod(0600)` is best-effort; Windows ACL enforcement was not audited. No credentials are
added to `.env.local` and no production DB path can be passed to preview preparation.
The current preview operator is ID 1, has three narrow runtime/reviewer permissions,
has no usable password, and has no superuser/user-management permissions. It is CLI-only.

## Start and stop (not executed here)

On a reviewed dedicated compatible Linux Docker host, the equivalent scoped commands are:

```text
docker compose --project-name ofoq-masar-judge0-dev --file deploy/judge0/compose.yaml up -d --wait db redis
docker compose --project-name ofoq-masar-judge0-dev --file deploy/judge0/compose.yaml up -d server workers
docker compose --project-name ofoq-masar-judge0-dev --file deploy/judge0/compose.yaml ps
docker compose --project-name ofoq-masar-judge0-dev --file deploy/judge0/compose.yaml stop
```

They affect only this project. Stop preserves its data; no deletion/reset command is supplied.
`manage.ps1 -Action Up -ReviewedDedicatedLinuxHost` additionally checks a live Linux amd64
daemon and cgroup v1, failing before startup otherwise. Validate/Status/Stop need no review flag.
PowerShell execution policy currently blocks direct `.ps1` invocation; the syntax was parsed
successfully. No execution policy was changed. Use the documented direct Compose commands
or an independently authorized script-execution process.

The expected local address is **http://127.0.0.1:2359**, not an active link today.
If the service is in a dedicated Linux VM, keep its port bound to that VM's loopback and
use a reviewed loopback-only SSH tunnel to host port 2359; do not expose the API to LAN/Internet.
Do not set `sandbox-review.txt` until the actual deployment/isolation review is recorded.
That file contains a non-secret review reference; it is not automated proof of isolation.

## Connect using existing connector and command only

All commands below use the isolated settings. Django global options must precede the
lab_judge0 subcommand because it has nested argparse subparsers.

```text
.venv\Scripts\python.exe -B educa/manage.py lab_judge0 --settings=educa.judge0_preview_settings inspect --engine judge0-dev
.venv\Scripts\python.exe -B educa/manage.py lab_judge0 --settings=educa.judge0_preview_settings sync --engine judge0-dev --actor 1
.venv\Scripts\python.exe -B educa/manage.py lab_judge0 --settings=educa.judge0_preview_settings bind --engine judge0-dev --remote-id REMOTE_ID --actor 1
.venv\Scripts\python.exe -B educa/manage.py lab_judge0 --settings=educa.judge0_preview_settings smoke --language LOCAL_ID --actor 1 --seconds 30
.venv\Scripts\python.exe -B educa/manage.py lab_judge0 --settings=educa.judge0_preview_settings enable --language LOCAL_ID --actor 1
```

Discover actual Python/JavaScript/C++ editions; do not reuse known IDs from other services.
`smoke` tests a correct Arabic output, runtime error and timeout; it does **not** cover the
whole acceptance matrix below. Do not call enable before a real successful smoke run.
No language was synchronized, tested or activated in the current preview.

## Pending actual acceptance matrix

Use the existing Judge0Client, lab_judge0 and private reference services, never another client
or public demo service. Log scenario/status only, not hidden inputs or credentials.

| Scenario, for every discovered candidate language | Bounded test / required evidence |
| --- | --- |
| Correct input/output | Read `2 3`, output `5`; accepted and exact expected stdout |
| Arabic round-trip | Read one fixed Arabic line, echo it; compare UTF-8 exactly |
| Syntax/compile error | A short invalid statement; program error, not service failure |
| Runtime error | Explicit exception/abort; program error, not service failure |
| Time limit | Busy loop with 0.2s CPU and bounded wall; time_limit |
| Output bound | Finite 128KiB output with 64KiB ceiling; output_limit or service-enforced bound |
| Network | One short attempt to a controlled disposable listener, timeout ≤1s; no listener contact |
| App filesystem | Disposable sentinel, never a real secret; verify unavailable in sandbox |
| Resource enforcement | Confirm requested ceilings and service maxima, terminal measured results |

Do not probe the Internet, metadata endpoints, other Ofoq services or arbitrary files.
A single refused TCP connection alone does not prove network blocking: verify the controlled
listener is reachable from a permitted control context and unreachable only from the sandbox.
Filesystem sentinel absence alone does not prove privileged-host isolation.

Reference tests must use a synthetic preview challenge with at least two cases: first both
pass, then a separate version with one expected mismatch. Persist tokens, interrupt only the
dedicated verifier, then resume by GET without another POST. To test service outage, stop
only the dedicated server after preserving known tokens and confirm a service error/pending
state, not wrong_answer/passed; restart only it and resume. Never restart shared Ofoq services.
These actual tests are blocked today and have not been marked successful.
