#!/usr/bin/env bash
# Run on the Windows machine (Git Bash) from the repo root AFTER the daily cycle finished here.
# The PC does all heavy work (ingest, features, training); the server only shows the result
# (docs/15-deploy.md, "تقسیم کار"). This ships a slim copy of the database and the artifacts the
# API reads, then swaps them in on the server after an integrity check.
#   bash deploy/sync-data.sh            # only what changed (days / tables that differ)
#   bash deploy/sync-data.sh --full     # the whole slim database, from scratch
# The default compares the two databases (deploy/syncdb.py) and sends only the differing days and
# tables, usually a few MB. It falls back to the full copy by itself when a delta is not safe: no
# server database, a different table layout, too much differing, or the server's result not
# matching the PC's after applying. needs ~/.ssh/tmon_vps
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=root@185.7.172.67
SSH=(ssh -p 1415 -i ~/.ssh/tmon_vps -o BatchMode=yes "$HOST")
SCP=(scp -q -P 1415 -i ~/.ssh/tmon_vps)
PY=backend/.venv/Scripts/python.exe
OUT=data/ship
FEATURE_DATES=60  # the site reads only the newest feature row of each symbol

mkdir -p "$OUT" && rm -f "$OUT"/*
SRV_DB=/var/lib/tmon/tmon-live.sqlite3
MODE=${1:-delta}

ship_artifacts() {
  # the API reads models/, scores/, v2/, data-health/; training snapshots and raw payloads stay on the PC
  tar -C data/objects --exclude=artifacts/snapshots -czf "$OUT/artifacts.tgz" artifacts
  "${SCP[@]}" "$OUT/artifacts.tgz" "$HOST:/root/"
  "${SSH[@]}" 'set -e
rm -rf /var/lib/tmon/objects/artifacts.new && mkdir -p /var/lib/tmon/objects/artifacts.new
tar -C /var/lib/tmon/objects/artifacts.new -xzf /root/artifacts.tgz
rm -rf /var/lib/tmon/objects/artifacts.old
[ -d /var/lib/tmon/objects/artifacts ] && mv /var/lib/tmon/objects/artifacts /var/lib/tmon/objects/artifacts.old
mv /var/lib/tmon/objects/artifacts.new/artifacts /var/lib/tmon/objects/artifacts
rm -rf /var/lib/tmon/objects/artifacts.new /var/lib/tmon/objects/artifacts.old /root/artifacts.tgz
chown -R tmon:tmon /var/lib/tmon/objects'
}

delta_sync() {
  # 0 = server now matches the PC, 1 = a full copy is needed (the reason is printed)
  local cut fp res
  cut=$("$PY" deploy/syncdb.py deep-from data/tmon-live.sqlite3)
  if "${SSH[@]}" "python3 - fingerprint $SRV_DB --deep-from '$cut'" < deploy/syncdb.py > "$OUT/server-fp.json" 2>"$OUT/server-fp.err"; then
    fp="$OUT/server-fp.json"
  else
    fp=-
  fi
  res=$("$PY" deploy/syncdb.py delta data/tmon-live.sqlite3 "$fp" "$OUT/delta.sqlite3")
  echo "delta: $res" | cut -c1-400
  if "$PY" -c "import json,sys; sys.exit(0 if not json.loads(sys.argv[1])['full'] else 1)" "$res"; then :; else
    echo "full copy needed: $("$PY" -c "import json,sys; print(json.loads(sys.argv[1])['reason'])" "$res")"
    return 1
  fi
  zstd -19 -T0 -q "$OUT/delta.sqlite3" -o "$OUT/delta.sqlite3.zst"
  ls -lh "$OUT/delta.sqlite3.zst"
  "${SCP[@]}" "$OUT/delta.sqlite3.zst" "$HOST:/root/"
  "${SSH[@]}" 'zstd -d -q -f /root/delta.sqlite3.zst -o /var/lib/tmon/delta.sqlite3 && chmod 644 /var/lib/tmon/delta.sqlite3' || return 1
  if "${SSH[@]}" "runuser -u tmon -- python3 - apply $SRV_DB /var/lib/tmon/delta.sqlite3" < deploy/syncdb.py; then
    "${SSH[@]}" 'rm -f /var/lib/tmon/delta.sqlite3 /root/delta.sqlite3.zst'
    return 0
  fi
  echo "the server did not match the PC after applying the delta"
  return 1
}

full_sync() {
"$PY" - "$OUT/tmon-live.sqlite3" "$FEATURE_DATES" <<'EOF'
import sqlite3, sys
dst, keep = sys.argv[1], int(sys.argv[2])
src = sqlite3.connect("file:data/tmon-live.sqlite3?mode=ro", uri=True)
src.execute(f"vacuum into '{dst}'")
c = sqlite3.connect(dst)
cut = c.execute(
    "select min(date) from (select distinct date from features order by date desc limit ?)", (keep,)
).fetchone()[0]
c.execute("delete from features where date < ?", (cut,))
# the batch URLs of the history download are 1.5 KB per price row; keep the endpoint only
for (t,) in c.execute("select name from sqlite_master where type='table'").fetchall():
    if "source_url" in [r[1] for r in c.execute(f'pragma table_info("{t}")')]:
        c.execute(
            f"""update "{t}" set source_url = substr(source_url, 1, instr(source_url, '&a=') + 2) || '...'
                where length(source_url) > 300 and instr(source_url, '&a=') > 0"""
        )
c.commit()
c.execute("vacuum")
ok = c.execute("pragma integrity_check").fetchone()[0]
c.execute("pragma journal_mode=delete")
print("db", ok, "features from", cut)
assert ok == "ok"
EOF
zstd -19 -T0 -q "$OUT/tmon-live.sqlite3" -o "$OUT/tmon-live.sqlite3.zst"
ls -lh "$OUT"
"${SCP[@]}" "$OUT/tmon-live.sqlite3.zst" "$HOST:/root/"
"${SSH[@]}" 'set -e
zstd -d -q -f /root/tmon-live.sqlite3.zst -o /var/lib/tmon/new.sqlite3
python3 -c "import sqlite3,sys; r=sqlite3.connect(\"/var/lib/tmon/new.sqlite3\").execute(\"pragma integrity_check\").fetchone()[0]; print(\"server db\", r); sys.exit(r!=\"ok\")"
systemctl stop tmon-api
mv /var/lib/tmon/new.sqlite3 /var/lib/tmon/tmon-live.sqlite3
rm -f /var/lib/tmon/tmon-live.sqlite3-wal /var/lib/tmon/tmon-live.sqlite3-shm
rm -f /root/tmon-live.sqlite3.zst
chown -R tmon:tmon /var/lib/tmon
systemctl start tmon-api
for i in $(seq 60); do curl -sf -o /dev/null 127.0.0.1:8000/health && break; sleep 1; done  # ~15 s on 2 cores
systemctl is-active tmon-api tmon-web'
}

if [ "$MODE" = "--full" ]; then
  echo "== full copy (asked for)"
  full_sync
elif delta_sync; then
  echo "== delta applied"
else
  echo "== falling back to the full copy"
  full_sync
fi
ship_artifacts
"${SSH[@]}" 'systemctl is-active tmon-api tmon-web
curl -sf 127.0.0.1:8000/freshness | head -c 120; echo'
