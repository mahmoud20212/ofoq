param(
    [ValidateSet('Validate','Up','Stop','Status')][string]$Action = 'Status',
    [switch]$ReviewedDedicatedLinuxHost
)
$ErrorActionPreference = 'Stop'
$composeFile = Join-Path $PSScriptRoot 'compose.yaml'
function Invoke-Compose([string[]]$Arguments) {
    & docker compose --project-name ofoq-masar-judge0-dev --file $composeFile @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated Judge0 command failed' }
}
switch ($Action) {
    'Validate' { Invoke-Compose -Arguments @('config','--quiet') }
    'Status' { Invoke-Compose -Arguments @('ps') }
    'Stop' { Invoke-Compose -Arguments @('stop') } # Retains data; never stops another compose project.
    'Up' {
        if (-not $ReviewedDedicatedLinuxHost) {
            throw 'Requires a reviewed dedicated Linux Docker host; upstream containers are privileged'
        }
        $platform = & docker info --format '{{.OSType}}:{{.Architecture}}:{{.CgroupVersion}}' 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'Docker engine unavailable; no services started' }
        if ($platform -notmatch '^linux:(x86_64|amd64):1$') {
            throw 'Requires reviewed Linux amd64 with cgroup v1 for the documented Judge0 1.13.1 setup; no system changes made'
        }
        Invoke-Compose -Arguments @('config','--quiet')
        Invoke-Compose -Arguments @('up','-d','--wait','db','redis')
        Invoke-Compose -Arguments @('up','-d','server','workers')
        Write-Output 'Started dedicated containers; readiness and sandbox tests still required at http://127.0.0.1:2359'
    }
}
