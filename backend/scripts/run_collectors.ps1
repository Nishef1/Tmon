# Collectors for the live database: the intraday poller (follows trading hours) and, with -Eod,
# the end-of-day refresh + features + model + v2 ranking. Used by the Windows scheduled tasks.
param([switch]$Eod)
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$env:TMON_DATABASE_URL = "sqlite:///" + ($root.Replace([string][char]92, '/')) + "/data/tmon-live.sqlite3"
$env:TMON_OBJECT_STORE = "file"
$env:TMON_OBJECT_STORE_DIR = Join-Path $root "data/objects"
$py = Join-Path $root "backend/.venv/Scripts/python.exe"
Set-Location (Join-Path $root "backend")
if ($Eod) {
  & $py -m tmon.ingest.tsetmc.cli eod
  & $py -m tmon.ingest.tsetmc.cli indices
  & $py -c "from tmon.core.db import session_scope; from tmon.features.store import refresh_features; from tmon.engine.service import train_and_publish; from tmon.storage.objectstore import get_object_store
with session_scope() as s:
    refresh_features(s,'D1'); s.commit(); train_and_publish(s,get_object_store()); s.commit()"
  & $py -m tmon.tools.v2_ranking
} else {
  & $py -m tmon.ingest.tsetmc.cli intraday --follow
}
