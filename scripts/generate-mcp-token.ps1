[CmdletBinding()]
param(
    [string]$Subject = 'local-agent',
    [string]$Scopes = 'read,write,delete',
    [string]$TTL = '24h'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($env:MCP_JWT_SECRET_FILE)) {
    $configuredPath = [Environment]::GetEnvironmentVariable('MCP_JWT_SECRET_FILE', 'User')
    if (-not [string]::IsNullOrWhiteSpace($configuredPath)) { $env:MCP_JWT_SECRET_FILE = $configuredPath }
}
if ([string]::IsNullOrWhiteSpace($env:MCP_JWT_SECRET_FILE)) {
    throw 'Execute .\scripts\setup-mcp-auth.ps1 antes de gerar o token.'
}

Push-Location $repoRoot
try {
    go run ./cmd/mcp-token -subject $Subject -scopes $Scopes -ttl $TTL
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar token JWT.' }
} finally {
    Pop-Location
}
