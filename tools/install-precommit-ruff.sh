cat > tools/install-precommit-ruff.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

HOOK=".git/hooks/pre-commit"
mkdir -p .git/hooks

cat > "$HOOK" <<'HEOF'
#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

if [[ "${SKIP_RUFF:-0}" == "1" ]]; then
  exit 0
fi

mapfile -t files < <(git diff --cached --name-only --diff-filter=ACM | grep -E '\.py$' || true)
[[ ${#files[@]} -eq 0 ]] && exit 0

if command -v ruff >/dev/null 2>&1; then
  RUFF="ruff"
elif python - <<<'import ruff' >/dev/null 2>&1; then
  RUFF="python -m ruff"
else
  echo "[pre-commit] Ruff non trovato. Salto controllo." >&2
  exit 0
fi

echo "[pre-commit] Ruff format..."
$RUFF format --force-exclude --quiet "${files[@]}" || true
git add -- "${files[@]}"

echo "[pre-commit] Ruff check --fix..."
$RUFF check --force-exclude --fix "${files[@]}" || true
git add -- "${files[@]}"

echo "[pre-commit] Verifica finale..."
if ! $RUFF check --force-exclude "${files[@]}"; then
  echo
  echo "Ruff ha rilevato problemi non auto-fissati."
  echo "Correggi e riprova, oppure: git commit --no-verify"
  exit 1
fi

echo "OK: Ruff pulito. Procedo col commit."
exit 0
HEOF

chmod +x "$HOOK"
echo "OK: Hook pre-commit installato in $HOOK"
EOF
chmod +x tools/install-precommit-ruff.sh

