#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C.UTF-8

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

LOGDIR="tools/_logs"
mkdir -p "$LOGDIR"
ROOTLOG="ruff-session.$(date +%F-%H%M%S).log"

# 1) Scrivi/aggiorna pyproject.toml (config compatibile Ruff recente)
cat > pyproject.toml <<'PYEOF'
[tool.ruff]
target-version = "py39"
line-length = 99
extend-exclude = ["packaging", "_backup", "_export"]

[tool.ruff.lint]
select = ["E", "F", "W"]

[tool.ruff.lint.per-file-ignores]
"hevc_gui/gui/main_window.py" = ["E402"]
"main.py" = ["E402"]
"hevc_gui/core/loudness.py" = ["E741"]
PYEOF

{
  echo "== $(date) =="
  echo "Root: $ROOT"
  echo "pyproject.toml scritto."

  # 2) Ruff DRY-RUN (diff)
  echo; echo ">> Ruff DRY-RUN"
  bash tools/ruff-clean.sh | tee "$LOGDIR/ruff-dryrun.$(date +%F-%H%M%S).log"

  # 3) Ruff APPLY (format + fix)
  echo; echo ">> Ruff APPLY"
  bash tools/ruff-clean.sh --apply | tee "$LOGDIR/ruff-apply.$(date +%F-%H%M%S).log"

  # 4) Safe commit (branch con secondi, niente collisioni)
  echo; echo ">> Safe-commit"
  bash tools/safe-commit.sh | tee "$LOGDIR/safe-commit.$(date +%F-%H%M%S).log"

  echo; echo "== DONE =="
} 2>&1 | tee "$ROOTLOG"

echo
echo "Log riepilogo in root: $ROOTLOG"
echo "Log dettagli in: $LOGDIR"
