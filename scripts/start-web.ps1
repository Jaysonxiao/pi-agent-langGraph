param(
    [ValidateSet('fake', 'compatible')][string]$Provider = 'fake',
    [string]$Workspace = '.',
    [string]$Database = '',
    [int]$Port = 8766
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    uv sync --extra web
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    Push-Location (Join-Path $projectRoot 'web-ui')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) {
            npm ci --no-fund --no-audit
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    $runArguments = @('run', '--extra', 'web')
    if ($Provider -eq 'compatible' -and (Test-Path -LiteralPath '.env')) {
        $runArguments += @('--env-file', '.env')
    }
    $runArguments += @('pi-agent-web', '--provider', $Provider, '--workspace', $Workspace,
        '--port', $Port)
    if ($Database) { $runArguments += @('--database', $Database) }
    & uv @runArguments
    if ($LASTEXITCODE -ne 0) { throw 'Web service exited with an error.' }
} finally { Pop-Location }
