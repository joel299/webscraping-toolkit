[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$baseUrl = 'https://wuyvgmzbmuwcjjzmgccs.supabase.co'
$key = [Environment]::GetEnvironmentVariable('SUPABASE_SERVICE_ROLE_KEY', 'Process')

if ([string]::IsNullOrWhiteSpace($key)) {
    Write-Host 'A chave nao esta definida nesta sessao. Digite-a no prompt oculto.' -ForegroundColor Yellow
    $secureKey = Read-Host 'Supabase service_role / secret key' -AsSecureString
    $keyPointer = [IntPtr]::Zero
    try {
        $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    } finally {
        if ($keyPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
        }
        $secureKey.Dispose()
    }
    if ([string]::IsNullOrWhiteSpace($key)) { throw 'A chave nao pode ficar vazia.' }
}
# Supabase API keys use URL-safe text and never contain whitespace. Clipboard
# pastes can insert line breaks in the middle, so remove them before headers.
$key = [System.Text.RegularExpressions.Regex]::Replace($key, '[\s\x00-\x1F\x7F]', '')
if ([string]::IsNullOrWhiteSpace($key)) {
    throw 'A chave ficou vazia depois de remover espacos e quebras de linha. Digite-a novamente.'
}
if (-not ($key.StartsWith('eyJ') -or $key.StartsWith('sb_secret_'))) {
    throw 'O valor carregado nao tem o prefixo de uma chave secret/service_role Supabase. Recarregue a chave pelo prompt.'
}

$uri = "$baseUrl/rest/v1/prospect_leads_google?select=place_id&limit=1"
$response = $null
$headers = @{ apikey = $key }
# Legacy service_role keys are JWTs and also establish the database role.
# New sb_secret keys are API keys, not JWTs; send them only as apikey.
if ($key.StartsWith('eyJ')) {
    $headers.Authorization = "Bearer $key"
}

try {
    $response = Invoke-WebRequest -Method Get -Uri $uri -Headers $headers -TimeoutSec 20 -UseBasicParsing -ErrorAction Stop
    $status = [int]$response.StatusCode
    Write-Host "HTTP $status" -ForegroundColor Green
} catch {
    $exception = $_.Exception
    while ($exception -is [System.AggregateException] -and $exception.InnerException) {
        $exception = $exception.InnerException
    }
    $httpResponse = $exception.Response
    if ($httpResponse) {
        $status = [int]$httpResponse.StatusCode
        switch ($status) {
            401 { Write-Host 'HTTP 401: a API respondeu, mas nao aceitou a chave/projeto.' -ForegroundColor Yellow }
            403 { Write-Host 'HTTP 403: autenticacao recebida, mas acesso negado pela API ou pelos grants.' -ForegroundColor Yellow }
            404 { Write-Host 'HTTP 404: API acessivel, mas tabela/endpoint nao encontrado ou nao exposto.' -ForegroundColor Yellow }
            default { Write-Host "HTTP ${status}: o endpoint respondeu." -ForegroundColor Yellow }
        }
    } else {
        $message = $exception.Message
        if ($key) { $message = $message.Replace($key, '[CHAVE OCULTA]') }
        Write-Host "Falha antes de receber HTTP ($($exception.GetType().Name)): $message" -ForegroundColor Red
    }
    exit 1
} finally {
    if ($response -and $response.PSObject.Methods['Dispose']) { $response.Dispose() }
    $headers.Clear()
    $key = $null
}
