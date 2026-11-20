#!/usr/bin/env bash
# Puts a previous release back on the server (the last three are kept in /opt/tmon/releases).
#   bash deploy/rollback.sh          # lists them
#   bash deploy/rollback.sh <commit> # installs that one (the web is rebuilt: about 4 minutes)
# Data is not touched. Fix the cause, commit, push and run release.sh again afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST=root@185.7.172.67
SSH=(ssh -p 1415 -i ~/.ssh/tmon_vps -o BatchMode=yes "$HOST")
SCP=(scp -q -P 1415 -i ~/.ssh/tmon_vps)
if [ $# -eq 0 ]; then
  "${SSH[@]}" 'echo "now: $(cat /opt/tmon/RELEASE)"; ls -1t /opt/tmon/releases/ | sed "s/.tar.gz//"'
  exit 0
fi
"${SCP[@]}" deploy/remote-install.sh deploy/install-monitor.sh "$HOST:/root/"
"${SSH[@]}" "test -f /opt/tmon/releases/$1.tar.gz && bash /root/remote-install.sh /opt/tmon/releases/$1.tar.gz $1; rm -f /root/remote-install.sh /root/install-monitor.sh"
echo "rolled back to $1"
