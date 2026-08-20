# Restore drill: extract the newest backup to a temp dir and verify it can be used.
# Read-only check - does not touch production data.
# A full restore drill (into a fresh environment) should be done on a test machine.
#
# Usage (from rag-course/):
#   powershell -ExecutionPolicy Bypass -File scripts/restore-check.ps1
$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $PSScriptRoot
$backupRoot = Join-Path $projectDir "backups"

$latest = Get-ChildItem $backupRoot -Filter "kb-*.tar.gz" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $latest) {
    Write-Error "No backup found - run scripts/backup.ps1 first"
    exit 1
}

$temp = Join-Path $env:TEMP ("kb-restore-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $temp | Out-Null

Write-Host "Extracting: $($latest.Name) -> $temp"
tar -xzf $latest.FullName -C $temp

$dataDir = Join-Path $temp "data"
if (-not (Test-Path $dataDir)) { $dataDir = $temp }  # compat with old backups without data/ prefix

# 1) SQLite integrity + key table row counts
$db = Join-Path $dataDir "users.db"
$check = & python -c "import sqlite3,sys; c=sqlite3.connect(r'$db'); print('integrity:', c.execute('PRAGMA integrity_check').fetchone()[0]); print('users:', c.execute('SELECT COUNT(*) FROM users').fetchone()[0]); print('security_log:', c.execute('SELECT COUNT(*) FROM security_log').fetchone()[0])"
Write-Host "users.db check: $check"

# 2) chroma directory file count
$chromaCount = (Get-ChildItem (Join-Path $dataDir "chroma") -Recurse -File -ErrorAction SilentlyContinue).Count
Write-Host "chroma files: $chromaCount"

# 3) audit log line count
$auditFile = Join-Path $dataDir "audit.jsonl"
if (Test-Path $auditFile) {
    $auditLines = (Get-Content $auditFile | Measure-Object -Line).Lines
    Write-Host "audit lines: $auditLines"
} else {
    Write-Host "audit.jsonl: not found (no Q&A records yet?)"
}

Write-Host "Restore drill done (temp dir: $temp - delete it after confirming)"
