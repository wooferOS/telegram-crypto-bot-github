#!/usr/bin/env bash
set -euo pipefail
SINCE_EPOCH="$(date -d 'today 00:00' +%s)"

hdr(){ printf "\n== %s ==\n" "$1"; }

hdr "Timezone & clock"
timedatectl | awk -F': ' 'NR==1||/Time zone/||/System clock synchronized/{print $0}'

hdr "Timers (next/last fire)"
for r in asia us; do
  echo "-- $r --"
  systemctl show "dev3-convert@${r}.timer" \
    -p ActiveState -p Persistent -p NextElapseUSecRealtime -p LastTriggerUSecRealtime \
    | sed '/=/!d'
done

hdr "Timer events today (Triggered)"
for r in asia us; do
  echo "-- $r --"
  journalctl -u "dev3-convert@${r}.timer" --since "@${SINCE_EPOCH}" --no-pager \
    | awk '/Triggered/ {print}' || true
done

hdr "Service runs today (config log + 4 phases per cycle)"
for r in asia us; do
  echo "-- $r --"
  J="$(journalctl -u "dev3-convert@${r}.service" --since "@${SINCE_EPOCH}" --no-pager)"
  cfgs="$(printf "%s" "$J" | grep -c 'config in use:')"
  phases="$(printf "%s" "$J" | grep -c " app\.run(region=${r}, phase=")"
  cycles=$(( phases / 4 ))
  ok_ph=$([ $(( phases % 4 )) -eq 0 ] && echo OK || echo BROKEN)
  ok_cfg=$([ "$cfgs" -eq "$cycles" ] && echo OK || echo MISMATCH)
  printf "cycles=%d  phases=%d  cfg_logs=%d  phases%%4=%s  cfg_vs_cycles=%s\n" \
         "$cycles" "$phases" "$cfgs" "$ok_ph" "$ok_cfg"
done

hdr "Errors/Warnings (today)"
for r in asia us; do
  echo "-- $r --"
  journalctl -u "dev3-convert@${r}.service" --since "@${SINCE_EPOCH}" --no-pager \
    | grep -Ei 'ERROR|CRITICAL|Traceback|failed|exception|timeout|429|rate.?limit' || echo "no errors"
done

hdr "Journald throttling (suppressed msgs)"
for r in asia us; do
  echo "-- $r --"
  journalctl -u "dev3-convert@${r}.service" --since "@${SINCE_EPOCH}" --no-pager \
    | grep -E 'Suppressed [0-9]+ messages' || echo "no suppression"
done

hdr "OnCalendar sanity (what's next)"
echo "asia:"; systemd-analyze calendar "Mon..Fri 03:05"; systemd-analyze calendar "Mon..Fri 10:30"
echo "us:";   systemd-analyze calendar "Mon..Fri 16:35"; systemd-analyze calendar "Mon..Fri 23:05"
