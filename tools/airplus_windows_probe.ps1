# Existing Windows PowerShell 5.1 or PowerShell 7 is sufficient.
# Read-only cloud discovery. No MQTT connection or device commands are issued.
# Account credentials and app signing material stay in process memory.
param([switch]$OfflineSelfTest)
$ErrorActionPreference = 'Stop'
$AirHost = 'https://www.api.air.philips.com/'
$GigyaHost = 'https://cdc.accounts.home.id/'
$AppId = '9fd505fa9c7111e9a1e3061302926720'
$GigyaKey = '4_JGZWlP8eQHpEqkvQElolbA'
$SigningSource = 'https://raw.githubusercontent.com/kwesolowski/node-red-contrib-philips-airplus/acbffa3683e728512dde7da824184586d3f4f9f9/docs/api-reverse-engineered.md'
$SigningSourceHash = '2015948594b31cae4f432e5cbd59ae3a34ceb908ad2e7634e449c32df76c384b'

function Get-Hex([byte[]]$Bytes) {
    return [BitConverter]::ToString($Bytes).Replace('-', '').ToLowerInvariant()
}
function Get-Hash([string]$Value) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return Get-Hex ($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))) }
    finally { $hasher.Dispose() }
}
function Get-Hmac([string]$Value, [string]$Key) {
    $hasher = [Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($Key))
    try { return Get-Hex ($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))) }
    finally { $hasher.Dispose() }
}
function ConvertTo-JavaUrlEncoding([string]$Value) {
    $result = [Text.StringBuilder]::new()
    foreach ($valueByte in [Text.Encoding]::UTF8.GetBytes($Value)) {
        if (($valueByte -ge 48 -and $valueByte -le 57) -or
            ($valueByte -ge 65 -and $valueByte -le 90) -or
            ($valueByte -ge 97 -and $valueByte -le 122) -or
            $valueByte -in @(45, 46, 95, 42)) {
            [void]$result.Append([char]$valueByte)
        } elseif ($valueByte -eq 32) { [void]$result.Append('+') }
        else { [void]$result.Append('%' + $valueByte.ToString('X2')) }
    }
    return $result.ToString()
}
function Get-AirSignature([string]$Timestamp, [string]$Username, [string]$Key) {
    $canonical = 'app_id=' + $AppId + '&timestamp=' + $Timestamp + '&username=' + (ConvertTo-JavaUrlEncoding $Username)
    return Get-Hmac (Get-Hmac $canonical $Key) $Username
}
function Get-SigningValue([string]$Document) {
    if ((Get-Hash $Document) -ne $SigningSourceHash) { throw 'Signing source hash mismatch' }
    $match = [regex]::Match($Document, '(?m)^\*\*Secret Key\*\*: `(a_[A-Za-z0-9]{32})`\r?$')
    if (-not $match.Success) { throw 'Signing value missing from pinned source' }
    return $match.Groups[1].Value
}
function Assert-Reply($Reply, [switch]$Gigya) {
    $code = if ($Gigya) { $Reply.errorCode } else { $Reply.meta.code }
    if ($null -eq $code -or $code -ne 0) {
        if ($code -is [int] -or $code -is [long]) { throw "Backend error $code" }
        throw 'Unexpected backend reply'
    }
}
function Get-SafeDevices($Devices) {
    $output = @()
    foreach ($device in $Devices) {
        if (-not ($device.device_id -is [string]) -or $device.device_id -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid device record' }
        $output += [ordered]@{
            reference = (Get-Hash $device.device_id).Substring(0, 12)
            model = $device.device_info.modelid
            type = $device.device_info.type
            firmware = $device.device_info.swversion
            region = $device.device_info.service_region
            online = $device.device_info.is_online
        }
    }
    return $output
}

if ($OfflineSelfTest) {
    if ((ConvertTo-JavaUrlEncoding 'PHILIPS:a b~*') -ne 'PHILIPS%3Aa+b%7E*') { throw 'URL encoding self-test failed' }
    $fixtureKey = 'a_' + ('0' * 32)
    $actual = Get-AirSignature '1000' 'PHILIPS:deadbeef' $fixtureKey
    if ($actual -ne 'a7dccd6496e7a3604274a3daa6c617d1534b0a3ed2bf34a3ca2bf6a0f3665fbb') { throw 'HMAC self-test failed' }
    $fixture = [pscustomobject]@{ device_id = 'private-device'; device_info = [pscustomobject]@{ modelid = 'AC3220/10'; name = 'private-name'; mac = 'private-mac' } }
    $summary = @(Get-SafeDevices @($fixture)) | ConvertTo-Json -Depth 5
    if ($summary -match 'private-device|private-name|private-mac') { throw 'Redaction self-test failed' }
    Write-Output 'Offline self-tests passed; no account or network was contacted.'
    exit 0
}

$stage = 'download verified signing reference'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $document = (Invoke-WebRequest -UseBasicParsing -Uri $SigningSource -TimeoutSec 30 -MaximumRedirection 0).Content
    $signingValue = Get-SigningValue $document
    $document = $null
    $email = (Read-Host 'Philips account email').Trim()
    if ($email -notmatch '^[^\s@]+@[^\s@]+$') { throw 'Invalid email' }
    $stage = 'request email code'
    $reply = Invoke-RestMethod -Uri ($GigyaHost + 'accounts.auth.otp.email.sendCode') -Method Post -ContentType 'application/x-www-form-urlencoded' -Body @{ email = $email; apiKey = $GigyaKey; format = 'json' } -TimeoutSec 30 -MaximumRedirection 0
    Assert-Reply $reply -Gigya
    if (-not $reply.vToken) { throw 'Missing verification handle' }
    $verification = $reply.vToken
    $secureCode = Read-Host 'Six-digit Philips email code' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureCode)
    try { $code = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($code -notmatch '^[0-9]{6}$') { throw 'Invalid code format' }
    $stage = 'verify email code'
    $reply = Invoke-RestMethod -Uri ($GigyaHost + 'accounts.auth.otp.email.login') -Method Post -ContentType 'application/x-www-form-urlencoded' -Body @{ email = $email; code = $code; vToken = $verification; apiKey = $GigyaKey; format = 'json' } -TimeoutSec 30 -MaximumRedirection 0
    $code = $null; $verification = $null; $secureCode = $null
    Assert-Reply $reply -Gigya
    if (-not ($reply.UID -is [string]) -or -not $reply.UID) { throw 'Missing account UID' }
    $username = 'PHILIPS:' + $reply.UID
    $reply = $null
    $stage = 'get cloud clock'
    $reply = Invoke-RestMethod -Uri ($AirHost + 'device/serverTime/') -TimeoutSec 30 -MaximumRedirection 0
    Assert-Reply $reply
    $timestamp = [string]$reply.data.timestamp2
    if ($timestamp -notmatch '^[0-9]{1,20}$') { throw 'Invalid server timestamp' }
    $stage = 'create new cloud token'
    $body = @{ username = $username; timestamp = $timestamp; app_id = $AppId } | ConvertTo-Json -Compress
    $reply = Invoke-RestMethod -Uri ($AirHost + 'enduser/v2/getToken/') -Method Post -ContentType 'application/json; charset=utf-8' -Headers @{ Signature = (Get-AirSignature $timestamp $username $signingValue) } -Body $body -TimeoutSec 30 -MaximumRedirection 0
    Assert-Reply $reply
    if (-not ($reply.data.token -is [string]) -or -not $reply.data.token) { throw 'Missing cloud token' }
    $headers = @{ Authorization = 'jwt ' + $reply.data.token }
    $reply = $null
    $stage = 'read own device list'
    $reply = Invoke-RestMethod -Uri ($AirHost + 'enduser/deviceList/') -Headers $headers -TimeoutSec 30 -MaximumRedirection 0
    Assert-Reply $reply
    $devices = @($reply.data)
    $safeDevices = @(Get-SafeDevices $devices)
    $connections = @()
    if ($devices.Count -gt 0) {
        $ownIds = @($devices | ForEach-Object { $_.device_id })
        $stage = 'read MQTT metadata'
        $body = @{ device_id = $ownIds } | ConvertTo-Json -Compress
        $reply = Invoke-RestMethod -Uri ($AirHost + 'enduser/v2/mqttInfo/') -Method Post -ContentType 'application/json; charset=utf-8' -Headers $headers -Body $body -TimeoutSec 30 -MaximumRedirection 0
        Assert-Reply $reply
        foreach ($connection in $reply.data.mqttinfos) {
            if ($connection.device_id -notin $ownIds) { throw 'Unexpected MQTT device' }
            $broker = [string]$connection.endpoint
            if ($broker -notmatch '^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.amazonaws\.com$') { throw 'Unexpected MQTT endpoint' }
            $connections += @{ reference = (Get-Hash $connection.device_id).Substring(0, 12); broker_host = $broker; has_signed_path = [bool]$connection.path; has_client_id = [bool]$connection.client_id }
        }
    }
    [ordered]@{ cloud_token_created = $true; device_count = $devices.Count; devices = $safeDevices; mqtt_metadata = $connections; device_state_changed = $false; mqtt_connection_attempted = $false } | ConvertTo-Json -Depth 8
} catch {
    # Never print the exception/response body: those may carry credentials.
    $safeError = if ($_.Exception.Message -match '^Backend error [0-9]+$') { $_.Exception.Message } else { 'No raw response or credentials printed.' }
    Write-Output "Diagnostic failed during: $stage. $safeError"
    exit 1
} finally {
    $headers = $null; $reply = $null; $signingValue = $null; $username = $null; $email = $null; $code = $null
}
