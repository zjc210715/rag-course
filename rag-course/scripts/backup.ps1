# Ops backup: snapshot the backend data volume (users.db + chroma + audit + sample)
#
# Usage (from rag-course/):
#   powershell -ExecutionPolicy Bypass -File scripts/backup.ps1
#
# Design:
#   - Stop backend before copying for SQLite consistency (hot copies can be torn);
#   - Copy out with `docker cp`, compress locally with tar (avoids shell quoting in PS);
#   - Keep only the newest 7 archives (rotation);
#   - nginx returns 502 for a few seconds during backup - run off-peak.
$ErrorActionPreference = "Stop"

$projectDir  = Split-Path -Parent $PSScriptRoot
$backupRoot  = Join-Path $projectDir "backups"
$stamp       = Get-Date -Format "yyyyMMdd-HHmmss"
$leaf        = "kb-$stamp.tar.gz"
$composeFile = Join-Path $projectDir "docker-compose.yml"

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

# Find the compose-created data volume (e.g. rag-course_app_data)
$volume = docker volume ls --format "{{.Name}}" | Where-Object { $_ -like "*app_data" } | Select-Object -First 1
if (-not $volume) {
    Write-Error "app_data volume not found - is the stack up?"
    exit 1
}

Write-Host "Backing up volume: $volume"
docker compose -f $composeFile stop backend
try {
    $tempRoot = Join-Path $env:TEMP ("kb-copy-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    docker cp "rag-backend:/app/data" (Join-Path $tempRoot "data")
    tar -czf (Join-Path $backupRoot $leaf) -C $tempRoot "data"
    Remove-Item $tempRoot -Recurse -Force
} finally {
    docker compose -f $composeFile start backend
}

Write-Host "Backup done: $(Join-Path $backupRoot $leaf)"

# Rotation: keep the newest 7 archives
$old = Get-ChildItem $backupRoot -Filter "kb-*.tar.gz" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 7
if ($old) {
    $old | Remove-Item
    Write-Host "Removed old backups: $($old.Count)"
}

Write-Host "Current backups:"
Get-ChildItem $backupRoot -Filter "kb-*.tar.gz" | Select-Object Name, Length, LastWriteTime
