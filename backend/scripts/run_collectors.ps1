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
  # the same cycle as the Celery beat: EOD prices and flows, indices, order book, risk-free rate,
  # dollar/gold/oil, news, features, living ranking, and the D1, W1 and M1 models (engine.yaml)
  & $py -m tmon.tasks.cycle
  if ($LASTEXITCODE -eq 2) {
    # another cycle holds the lock: running the rest now would fight it for the database
    Write-Host "another cycle is already running; nothing was started"
    exit 2
  }
  & $py -m tmon.tools.v2_ranking
  # where each symbol stands in its fall or run-up, with that state's history
  & $py -m tmon.tools.turning_points
  # ties to the index, dollar, copper and Brent, and moves after dated shocks
  & $py -m tmon.tools.stock_drivers
  # industry map: export-domestic axis, dollar tie, beta and cohesion per industry
  & $py -m tmon.tools.industry_map
  # every chart term of the glossary: tested readings, each symbol's values and risk numbers
  & $py -m tmon.tools.ta_signals
  # after which candles the next ones were green: streaks, entries from a base, uptrend pullbacks
  & $py -m tmon.tools.entry_odds
  # market state from breadth and the plan's paper test: enter, exit, switch or wait
  & $py -m tmon.tools.regime_paper
  # leveraged funds against the market, and the fund types side by side
  & $py -m tmon.tools.leveraged_funds
  # new assembly/capital letters from Codal, then the day each invitation names
  & $py -m tmon.ingest.codal.cli events
  & $py -m tmon.ingest.codal.cli meetings
  # EPS and group P/E change only with a new financial statement: refresh them once a week
  if ((Get-Date).DayOfWeek -eq 'Thursday') { & $py -m tmon.ingest.tsetmc.cli info }
} else {
  & $py -m tmon.ingest.tsetmc.cli intraday --follow
}
