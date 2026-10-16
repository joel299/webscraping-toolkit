[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$secretDirectory = Join-Path $env:APPDATA 'CentralDeLeads'
$secretPath = Join-Path $secretDirectory 'mcp-jwt-secret.txt'
New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null

if (-not (Test-Path -LiteralPath $secretPath)) {
    $bytes = [byte[]]::new(32)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    [System.IO.File]::WriteAllText($secretPath, $secret, [System.Text.UTF8Encoding]::new($false))
    $bytes = $null
    $secret = $null
}

[Environment]::SetEnvironmentVariable('MCP_JWT_SECRET_FILE', $secretPath, 'User')
$env:MCP_JWT_SECRET_FILE = $secretPath
Write-Host 'Chave de assinatura salva na pasta de perfil deste usuario.' -ForegroundColor Green
Write-Host 'Reinicie o servidor para ativar JWT nas rotas REST e no endpoint /mcp.'
Write-Host 'Gere um token com .\scripts\generate-mcp-token.ps1; nao compartilhe o token.'
