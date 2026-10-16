[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Read-RequiredValue([string]$Prompt, [string]$DefaultValue = '') {
    while ($true) {
        if ($DefaultValue) {
            $value = Read-Host "$Prompt [$DefaultValue]"
            if ([string]::IsNullOrWhiteSpace($value)) { $value = $DefaultValue }
        } else {
            $value = Read-Host $Prompt
        }
        if (-not [string]::IsNullOrWhiteSpace($value)) { return $value.Trim() }
        Write-Host 'Este campo e obrigatorio.' -ForegroundColor Yellow
    }
}

Write-Host 'Configurar conexao PostgreSQL para Central de Leads' -ForegroundColor Cyan
Write-Host 'A senha sera digitada de forma oculta e salva em um arquivo privado do seu usuario Windows.'
Write-Host 'O projeto espera as tabelas public.prospect_leads_google, public.prospect_searches e public.prospect_search_leads.'
Write-Host 'No Supabase, postgres e o nome do banco; prospect_leads_google e o nome de uma tabela.'
Write-Host ''

$hostName = Read-RequiredValue 'Host do PostgreSQL'
if ($hostName -match '^https?://') {
    try {
        $hostUri = [Uri]$hostName
        if (-not $hostUri.IsAbsoluteUri -or $hostUri.HostNameType -eq [UriHostNameType]::Unknown -or $hostUri.AbsolutePath -notin @('', '/')) {
            throw 'invalido'
        }
        $hostName = $hostUri.Host
    } catch {
        throw 'Host invalido. Informe somente o host ou uma URL contendo apenas host (sem caminho).'
    }
}
if ($hostName -match '^[^.]+\.supabase\.co$') {
    throw 'Esse e o host da API do projeto, nao do PostgreSQL. No Dashboard do Supabase, abra Connect e copie Host, Port e User de Session pooler.'
}
$portText = Read-RequiredValue 'Porta' '5432'
$port = 0
if (-not [int]::TryParse($portText, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
    throw 'Porta invalida. Informe um numero entre 1 e 65535.'
}
$database = Read-RequiredValue 'Nome do banco' 'postgres'
$username = Read-RequiredValue 'Usuario do banco'
$passwordSecure = Read-Host 'Senha do banco (entrada oculta)' -AsSecureString
if ($passwordSecure.Length -eq 0) { throw 'A senha nao pode ficar vazia.' }

$bstr = [IntPtr]::Zero
try {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($passwordSecure)
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)

    $escapedUser = [Uri]::EscapeDataString($username)
    $escapedPassword = [Uri]::EscapeDataString($password)
    $escapedDatabase = [Uri]::EscapeDataString($database)
    $dsn = "postgres://${escapedUser}:${escapedPassword}@${hostName}:${port}/${escapedDatabase}?sslmode=require"

    $secretDirectory = Join-Path $env:APPDATA 'CentralDeLeads'
    $secretPath = Join-Path $secretDirectory 'postgres-url.txt'
    New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null

    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $currentSid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $secretDirectory -AclObject $acl
    [System.IO.File]::WriteAllText($secretPath, $dsn, [System.Text.UTF8Encoding]::new($false))

    [Environment]::SetEnvironmentVariable('PROSPECT_DATABASE_URL_FILE', $secretPath, 'User')
    $env:PROSPECT_DATABASE_URL_FILE = $secretPath
} finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $password = $null
    $dsn = $null
    $passwordSecure.Dispose()
}

Write-Host ''
Write-Host 'Credencial salva com acesso restrito ao seu usuario Windows.' -ForegroundColor Green
Write-Host "Arquivo: $secretPath"
Write-Host 'As buscas continuarao usando o fluxo atual; a persistencia no PostgreSQL ficara habilitada ao reiniciar.'
Write-Host 'Antes de iniciar, aplique as migrations SQL de supabase/migrations no banco escolhido.'
Write-Host 'O aplicativo precisa de acesso de leitura e gravacao nas tres tabelas prospect_* listadas acima.'
Write-Host 'Depois de aplicar as migrations, habilite a leitura do banco no terminal com:'
Write-Host '  [Environment]::SetEnvironmentVariable(''PROSPECT_READ_MODE'', ''database'', ''User'')'
Write-Host '  $env:PROSPECT_READ_MODE = ''database''' 
