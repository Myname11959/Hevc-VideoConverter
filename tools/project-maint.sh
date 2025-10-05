#!/usr/bin/env bash
set -euo pipefail

# project-maint.sh — orchestratore manutenzione repo (ASCII only)
# - allinea nomi/permessi tool
# - pulizia artefatti .deb (dry-run -> apply)
# - tree della root
# - init git + hook pre-commit Ruff
# - Ruff dry-run
# - safe-commit (branch + apply + commit)
# Opzioni:
#   -y / --yes     esegue senza conferme
#   --no-commit    salta il safe-commit
#   --depth N      profondita' tree (default 5)

YES=0
DO_COMMIT=1
TREE_DEPTH=5

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes) YES=1; shift ;;
    --no-commit) DO_COMMIT=0; shift ;;
    --depth) TREE_DEPTH="${2:-5}"; shift 2 ;;
    *) echo "Argomento sconosciuto: $1"; exit 2 ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || { echo "Impossibile cd in $ROOT"; exit 1; }

LOGDIR="tools/_logs"; mkdir -p "$LOGDIR"
ts() { date +%F-%H%M%S; }
say() { printf '\n== %s ==\n' "$*"; }  # ASCII only

say "Root: $ROOT"
echo "Log dir: $LOGDIR"
echo "Opzioni: YES=$YES, DO_COMMIT=$DO_COMMIT, TREE_DEPTH=$TREE_DEPTH"

# 1) allinea nomi tool e permessi
say "Allineo nomi e permessi tool"
if [[ -f tools/install-precommit-ruff && ! -f tools/install-precommit-ruff.sh ]]; then
  mv tools/install-precommit-ruff tools/install-precommit-ruff.sh
  echo "rinominato: tools/install-precommit-ruff -> tools/install-precommit-ruff.sh"
fi
if [[ -f tools/sfe-commit.sh && ! -f tools/safe-commit.sh ]]; then
  mv tools/sfe-commit.sh tools/safe-commit.sh
  echo "rinominato: tools/sfe-commit.sh -> tools/safe-commit.sh"
fi
chmod +x tools/*.sh 2>/dev/null || true
echo "permessi: resi eseguibili gli .sh in tools/"

# 2) DRY-RUN deb-sanitize
if [[ -x tools/deb-sanitize.sh ]]; then
  say "Pulizia .deb - DRY-RUN"
  bash tools/deb-sanitize.sh | tee "$LOGDIR/deb-sanitize.dryrun.$(ts).log"
  if [[ $YES -eq 1 ]]; then APPLY=1; else
    read -r -p "Applico la pulizia (sposta in packaging/deb-archive/)? [y/N] " yn
    APPLY=0; [[ "$yn" =~ ^[Yy]$ ]] && APPLY=1
  fi
  if [[ $APPLY -eq 1 ]]; then
    say "Pulizia .deb - APPLY"
    bash tools/deb-sanitize.sh --apply | tee "$LOGDIR/deb-sanitize.apply.$(ts).log"
  else
    echo "Pulizia .deb non applicata (rimasto in DRY-RUN)."
  fi
else
  echo "tools/deb-sanitize.sh non trovato: salto pulizia."
fi

# 3) tree della root (ASCII)
say "Genero il tree della root (profondita' $TREE_DEPTH) -> repo-tree.txt"
if [[ -x tools/repo-tree.sh ]]; then
  bash tools/repo-tree.sh . "$TREE_DEPTH" | tee repo-tree.txt
else
  echo "tools/repo-tree.sh non trovato: salto (creo repo-tree.txt placeholder)."
  echo "(manca tools/repo-tree.sh)" > repo-tree.txt
fi

# 4) init git (se serve)
if [[ ! -d .git ]]; then
  if [[ -x tools/init-git.sh ]]; then
    say "Inizializzo git"
    bash tools/init-git.sh . | tee "$LOGDIR/init-git.$(ts).log"
  else
    echo "tools/init-git.sh non trovato: salto init git."
  fi
else
  say "Git gia' inizializzato"
fi

# 5) hook pre-commit Ruff
if [[ -x tools/install-precommit-ruff.sh ]]; then
  say "Installo hook pre-commit Ruff"
  bash tools/install-precommit-ruff.sh | tee "$LOGDIR/precommit.$(ts).log"
else
  echo "tools/install-precommit-ruff.sh non trovato: salto hook."
fi

# 6) Ruff DRY-RUN
if [[ -x tools/ruff-clean.sh ]]; then
  say "Ruff - DRY-RUN (diff)"
  bash tools/ruff-clean.sh | tee "$LOGDIR/ruff-dryrun.$(ts).log"
else
  echo "tools/ruff-clean.sh non trovato: salto ruff."
fi

# 7) Safe commit
if [[ -x tools/safe-commit.sh && $DO_COMMIT -eq 1 ]]; then
  if [[ $YES -eq 1 ]]; then RUN_COMMIT=1; else
    read -r -p "Creo branch e commit automatico Ruff (safe-commit)? [y/N] " yn
    RUN_COMMIT=0; [[ "$yn" =~ ^[Yy]$ ]] && RUN_COMMIT=1
  fi
  if [[ $RUN_COMMIT -eq 1 ]]; then
    say "Safe-commit in corso"
    bash tools/safe-commit.sh | tee "$LOGDIR/safe-commit.$(ts).log"
  else
    echo "Safe-commit saltato."
  fi
else
  echo "tools/safe-commit.sh non trovato o disattivato: salto commit automatico."
fi

say "Fatto. Log in: $LOGDIR"
