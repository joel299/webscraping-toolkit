[CmdletBinding()]
param(
    [string]$ProjectUrl = 'https://wuyvgmzbmuwcjjzmgccs.supabase.co'
)

$ErrorActionPreference = 'Stop'
$envPath = Join-Path (Split-Path -Parent $PSScriptRoot) '.env'

$parsedUrl = $null
if (-not [Uri]::TryCreate($ProjectUrl, [UriKind]::Absolute, [ref]$parsedUrl) -or
    $parsedUrl.Scheme -ne 'https') {
    throw 'Informe uma URL HTTPS valida do projeto Supabase.'
}

# PowerShell 7.1+ supports masked string input. Windows PowerShell 5.1 does
# not; use its plain Read-Host path so paste is actually captured instead of
# passing through the SecureString conversion that returned an empty value.
if ($PSVersionTable.PSVersion -ge [Version]'7.1') {
    $key = Read-Host 'Cole a chave service_role/secret do Supabase' -MaskInput
} else {
    Write-Warning 'Este PowerShell antigo mostra a chave durante a entrada. O valor nao sera impresso nem salvo no historico do comando.'
    $key = Read-Host 'Cole a chave service_role/secret do Supabase'
}

$key = [regex]::Replace($key, '[\s\x00-\x1F\x7F]', '')
if ([string]::IsNullOrWhiteSpace($key)) { throw 'O PowerShell recebeu uma entrada vazia; o .env nao foi alterado.' }
if (-not ($key.StartsWith('eyJ') -or $key.StartsWith('sb_secret_'))) {
    throw 'A chave nao parece ser service_role/secret do Supabase.'
}
# Preserve unrelated .env settings and replace only the two Supabase entries.
$lines = @()
if (Test-Path -LiteralPath $envPath) {
    $lines = @(Get-Content -LiteralPath $envPath | Where-Object {
        $_ -notmatch '^\s*(SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)\s*='
    })
}
$lines += "SUPABASE_URL=$ProjectUrl"
$lines += "SUPABASE_SERVICE_ROLE_KEY=$key"
$tmpPath = "$envPath.tmp"
[System.IO.File]::WriteAllLines($tmpPath, $lines, [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $tmpPath -Destination $envPath -Force
$key = $null

Write-Host 'Configuracao Supabase salva no .env local (ignorado pelo Git). A chave nao foi exibida.' -ForegroundColor Green
