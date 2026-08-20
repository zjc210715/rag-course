# Check TLS certificate expiry; warn when less than 30 days left.
# Usage (from rag-course/):
#   powershell -ExecutionPolicy Bypass -File scripts/check-cert.ps1
$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $PSScriptRoot
$certFile = Join-Path $projectDir "certs\kb.crt"

if (-not (Test-Path $certFile)) {
    Write-Host "Certificate not found: $certFile"
    exit 1
}

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certFile)
$daysLeft = [math]::Floor(($cert.NotAfter - (Get-Date)).TotalDays)

Write-Host "Certificate: $($cert.Subject)"
Write-Host "Expires:     $($cert.NotAfter)  ($daysLeft days left)"

if ($daysLeft -lt 0) {
    Write-Host "CRITICAL: certificate has EXPIRED - service is broken, renew now!"
    exit 1
} elseif ($daysLeft -lt 30) {
    Write-Host "WARNING: certificate expires in less than 30 days - renew now!"
    exit 1
} elseif ($daysLeft -lt 90) {
    Write-Host "NOTE: plan a certificate renewal within 90 days."
}
