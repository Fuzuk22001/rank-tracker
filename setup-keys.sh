#!/bin/bash
# One-off: store the DataForSEO API login and password in the macOS Keychain.
set -euo pipefail
read -rp "DataForSEO API login: " login
read -rsp "DataForSEO API password (hidden): " password; echo
security add-generic-password -U -s rank-tracker -a DATAFORSEO_LOGIN -w "$login"
security add-generic-password -U -s rank-tracker -a DATAFORSEO_PASSWORD -w "$password"
echo "Saved to Keychain (service: rank-tracker)."
