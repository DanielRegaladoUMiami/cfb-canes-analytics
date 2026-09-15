#!/usr/bin/env bash
# Repair an editable install that iCloud broke.
#
# This repo lives under ~/Desktop, which iCloud Drive syncs. When iCloud manages a file
# it sets the macOS UF_HIDDEN flag on it. Python 3.12.3+ and 3.13 deliberately SKIP
# hidden .pth files in site-packages, and uv installs the project as an editable .pth,
# so the package silently stops importing:
#
#     ModuleNotFoundError: No module named 'cfb_canes_analytics'
#
# ...even though `uv sync` reports everything installed. Clearing the flag fixes it
# until iCloud touches the files again.
#
# Permanent fixes, in order of preference:
#   1. export UV_PROJECT_ENVIRONMENT=.venv.nosync in ~/.zshrc — iCloud ignores any
#      directory whose name ends in .nosync, so the venv stops being synced at all.
#   2. Move the repos out of ~/Desktop (and out of iCloud's Desktop & Documents sync).
#
# Tests are unaffected: pyproject sets pytest's pythonpath to src.
set -euo pipefail
cd "$(dirname "$0")/.."
shopt -s nullglob
files=(.venv/lib/python*/site-packages/*.pth)
if [ ${#files[@]} -eq 0 ]; then
  echo "no .pth files found — run 'uv sync' first" >&2
  exit 1
fi
chflags nohidden "${files[@]}"
echo "cleared hidden flag on ${#files[@]} .pth file(s)"
.venv/bin/python -c "import cfb_canes_analytics; print('import OK:', cfb_canes_analytics.__file__)"
