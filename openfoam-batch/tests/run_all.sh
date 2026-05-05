#!/usr/bin/env bash
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
total_failures=0
for f in "${DIR}"/*_test.sh; do
  [[ -f "${f}" ]] || continue
  printf '\n== %s ==\n' "$(basename "${f}")"
  bash "${f}"
  rc=$?
  total_failures=$((total_failures + rc))
done
if [[ "${total_failures}" -gt 0 ]]; then
  printf '\nFAILED: %d test files reported failures\n' "${total_failures}" >&2
  exit 1
fi
printf '\nAll test files passed.\n'
