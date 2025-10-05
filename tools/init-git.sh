#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

if [ -d .git ]; then
  echo "Git già inizializzato in $(pwd)"
  exit 0
fi

# init (usa -b main se disponibile)
if git init -b main >/dev/null 2>&1; then
  :
else
  git init
  git checkout -b main
fi

# .gitignore minimale per Python/PyQt/ruff
cat > .gitignore <<'EOF'
# Python
__pycache__/
*.py[cod]
*.so
*.pyd
*.pyo
*.egg-info/
.build/
dist/
build/

# Virtual env
.venv/
venv/

# Tools / cache
.ruff_cache/
.mypy_cache/
.pytest_cache/

# IDE
.idea/
.vscode/

# OS
.DS_Store
Thumbs.db
EOF

git add .gitignore
git commit -m "chore: add .gitignore"
echo "OK: repo git inizializzata su branch 'main'."

