#!/usr/bin/env bash
# Fail if any package in frontend/package-lock.json has a license outside the ADR 0010 policy.
# "A OR B" passes if any option is allowed; otherwise every license named must be allowed.
set -euo pipefail

lockfile="${1:-frontend/package-lock.json}"
allowed=" MIT ISC Apache-2.0 BSD-2-Clause BSD-3-Clause 0BSD MPL-2.0 CC0-1.0 CC-BY-4.0 BlueOak-1.0.0 Python-2.0 Unlicense Zlib "

is_allowed() { [[ "$allowed" == *" $1 "* ]]; }

failed=0
while IFS=$'\t' read -r pkg license; do
  tokens=$(tr -d '()' <<<"$license" | sed -e 's/ OR / /g' -e 's/ AND / /g')
  ok=1
  if [[ "$license" == *" OR "* ]]; then
    ok=0
    for t in $tokens; do is_allowed "$t" && ok=1; done
  else
    for t in $tokens; do is_allowed "$t" || ok=0; done
  fi
  if [[ $ok -eq 0 ]]; then
    echo "::error::License not allowed by ADR 0010: ${pkg#node_modules/} ($license)"
    failed=1
  fi
done < <(jq -r '.packages | to_entries[] | select(.key != "") | [.key, (.value.license // "UNKNOWN")] | @tsv' "$lockfile")

if [[ $failed -eq 0 ]]; then echo "All npm package licenses allowed."; fi
exit "$failed"
