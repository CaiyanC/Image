#!/usr/bin/env bash
set -euo pipefail

: "${BASE_URL:=http://127.0.0.1:8000}"

curl --fail --silent --show-error "$BASE_URL/api/health/live" >/dev/null
curl --fail --silent --show-error "$BASE_URL/api/health/ready"
