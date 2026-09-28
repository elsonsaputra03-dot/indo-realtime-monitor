#!/usr/bin/env bash
# Cek end-to-end semua source. FAIL = wajib diperbaiki, WARN = periksa (bisa normal).
set -uo pipefail
API=${API:-http://localhost:8000}
FAILED=0
ok(){ echo "  [OK]   $1"; }
warn(){ echo "  [WARN] $1"; }
fail(){ echo "  [FAIL] $1"; FAILED=1; }
jq_py(){ python3 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null || echo 0; }

echo "Smoke test $API"
curl -fsS "$API/api/health" >/dev/null && ok "API health" || fail "API health"

stats=$(curl -fsS "$API/api/ingest/stats" || echo "[]")
for src in bmkg usgs firms openmeteo_aq; do
  line=$(echo "$stats" | python3 -c "
import sys,json
r=[x for x in json.load(sys.stdin) if x['source']=='$src']
print(f\"{r[0]['runs']} {r[0]['errors']} {r[0]['new_records']}\" if r else '0 0 0')" 2>/dev/null || echo "0 0 0")
  read -r runs errs new <<<"$line"
  if [ "$runs" -eq 0 ]; then
    [ "$src" = "firms" ] && warn "firms: belum ada run (FIRMS_MAP_KEY sudah diisi?)" || fail "$src: belum ada ingest run"
  elif [ "$errs" -eq "$runs" ]; then
    fail "$src: semua $runs run error (docker compose logs producer-...)"
  else
    ok "$src: runs=$runs errors=$errs new_records=$new"
  fi
done

n=$(curl -fsS "$API/api/earthquakes?hours=168" | jq_py 'len(d["features"])')
[ "$n" -gt 0 ] && ok "gempa 7 hari: $n" || fail "belum ada data gempa"
n=$(curl -fsS "$API/api/hotspots?hours=48" | jq_py 'len(d["features"])')
[ "$n" -gt 0 ] && ok "titik panas 48 jam: $n" || warn "titik panas 48 jam: 0 (bisa normal di musim hujan / key belum diisi)"
n=$(curl -fsS "$API/api/air-quality/latest" | jq_py 'len(d)')
[ "$n" -gt 0 ] && ok "kota kualitas udara: $n" || fail "belum ada data kualitas udara"
n=$(curl -fsS "$API/api/dq/latest" | jq_py 'len(d)')
[ "$n" -gt 0 ] && ok "DQ checks: $n" || fail "belum ada hasil DQ"

exit $FAILED
