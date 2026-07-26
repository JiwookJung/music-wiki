#!/bin/sh
# OKF 스펙 최신화: 원본이 갱신되면 로컬 사본(docs/okf/SPEC.md)을 업데이트하고 변경점을 보여준다.
set -e
URL="https://raw.githubusercontent.com/GoogleCloudPlatform/knowledge-catalog/main/okf/SPEC.md"
DST="$(dirname "$0")/../docs/okf/SPEC.md"
TMP="$(mktemp)"
curl -sL "$URL" -o "$TMP"
if [ ! -s "$TMP" ]; then echo "다운로드 실패"; exit 1; fi
if diff -q "$DST" "$TMP" >/dev/null 2>&1; then
  echo "OKF 스펙: 변경 없음 ($(grep -m1 -oE 'v[0-9.]+' "$DST" 2>/dev/null || echo '버전 미상'))"
else
  echo "OKF 스펙 변경 감지 — 주요 diff:"
  diff "$DST" "$TMP" | head -30 || true
  cp "$TMP" "$DST"
  echo "업데이트 완료: $DST (git diff 확인 후 커밋하세요)"
fi
rm -f "$TMP"
