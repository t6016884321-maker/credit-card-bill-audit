#!/usr/bin/env bash
# Install this repository as a user-level WorkBuddy skill.
# Usage: ./scripts/install.sh [--force]
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${HOME}/.workbuddy/skills/credit-card-bill-audit"
FORCE="${1:-}"

if [[ -e "$DEST" && "$FORCE" != "--force" ]]; then
  echo "Already installed at: $DEST"
  echo "Re-run with --force to overwrite (your audit_out/ data is never copied)."
  exit 1
fi

mkdir -p "$(dirname "$DEST")"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git/' \
    --exclude 'audit_out/' \
    --exclude 'demo_out/' \
    --exclude 'deliverables/' \
    --exclude 'bills/' \
    --exclude '__pycache__/' \
    --exclude '*.pdf' \
    --exclude '*.eml' \
    --exclude '*.csv' \
    --exclude '.DS_Store' \
    "$SRC/" "$DEST/"
else
  rm -rf "$DEST"
  mkdir -p "$DEST"
  (cd "$SRC" && tar -cf - \
    --exclude='.git' --exclude='audit_out' --exclude='demo_out' \
    --exclude='deliverables' --exclude='bills' --exclude='__pycache__' \
    --exclude='*.pdf' --exclude='*.eml' --exclude='*.csv' .) \
    | (cd "$DEST" && tar -xf -)
fi

echo "Installed skill -> $DEST"
echo ""
echo "Next:"
echo "  python3 -m pip install pymupdf weasyprint"
echo "  python3 $DEST/scripts/run_pipeline.py --out /tmp/ccba_demo --dry-run"
echo ""
echo "In WorkBuddy, just say: 帮我核查信用卡历史账单"
