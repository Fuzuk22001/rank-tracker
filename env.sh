#!/bin/bash
# Load secrets from the macOS Keychain. Usage: source env.sh
# SP-API keys are shared with the amazon-sp-api-mcp sync (service "amazon-sp-api-mcp").
# DataForSEO keys live under service "rank-tracker" (added with setup-keys.sh).

_kc() { security find-generic-password -s "$1" -a "$2" -w 2>/dev/null; }

export SPAPI_LWA_CLIENT_ID="$(_kc amazon-sp-api-mcp SP_API_CLIENT_ID)"
export SPAPI_LWA_CLIENT_SECRET="$(_kc amazon-sp-api-mcp SP_API_CLIENT_SECRET)"
export SPAPI_REFRESH_TOKEN="$(_kc amazon-sp-api-mcp SP_API_REFRESH_TOKEN)"
export DATAFORSEO_LOGIN="$(_kc rank-tracker DATAFORSEO_LOGIN)"
export DATAFORSEO_PASSWORD="$(_kc rank-tracker DATAFORSEO_PASSWORD)"

for _v in SPAPI_LWA_CLIENT_ID SPAPI_LWA_CLIENT_SECRET SPAPI_REFRESH_TOKEN DATAFORSEO_LOGIN DATAFORSEO_PASSWORD; do
  [ -n "${!_v}" ] || echo "env.sh: $_v not found in Keychain" >&2
done
unset _v
