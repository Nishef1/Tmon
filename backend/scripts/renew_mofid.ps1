# Renew every Mofid link from its saved login (hidden Chrome on this PC), sync here, and hand the
# token to the server over ssh. Used by the Tmon-Mofid scheduled task each morning before the
# market. Prints one line per portfolio and never the token.
#   powershell -ExecutionPolicy Bypass -File backend/scripts/renew_mofid.ps1
#   powershell -ExecutionPolicy Bypass -File backend/scripts/renew_mofid.ps1 -Register   # create the 08:00 task
param([switch]$Register)
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ($Register) {
  $action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`""
  $trigger = New-ScheduledTaskTrigger -Daily -At 08:00
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
  Register-ScheduledTask -TaskName "Tmon-Mofid" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Renew the Mofid login and send it to the Tmon server" -Force | Out-Null
  Write-Host "Tmon-Mofid: every day at 08:00 (or as soon as the PC is on)"
  exit 0
}
$env:TMON_DATABASE_URL = "sqlite:///" + ($root.Replace([string][char]92, '/')) + "/data/tmon-live.sqlite3"
$env:TMON_OBJECT_STORE = "file"
$env:TMON_OBJECT_STORE_DIR = Join-Path $root "data/objects"
$py = Join-Path $root "backend/.venv/Scripts/python.exe"
$key = $HOME.Replace([string][char]92, '/') + "/.ssh/tmon_vps"  # forward slashes: the line is split like a shell
$log = Join-Path $root "data/logs/mofid-renew.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Set-Location (Join-Path $root "backend")
$ssh = "ssh -p 1415 -i $key -o BatchMode=yes -o ConnectTimeout=20 root@185.7.172.67"
"== $(Get-Date -Format s)" | Add-Content $log
& $py -m tmon.portfolio.mofid renew --ssh $ssh 2>&1 | ForEach-Object { "$_" } | Tee-Object -Append $log
exit $LASTEXITCODE
