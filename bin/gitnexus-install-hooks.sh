#!/usr/bin/env bash
# Install GitNexus git hooks into a target repository
# Usage: bin/gitnexus-install-hooks.sh [/path/to/repo]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_SRC="$OPS_ROOT/hooks"
TARGET_REPO="${1:-.}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Resolve absolute path
TARGET_REPO="$(cd "$TARGET_REPO" && pwd)"

# Verify .git directory exists
if [[ ! -d "$TARGET_REPO/.git" ]]; then
  echo -e "${RED}Error: $TARGET_REPO is not a git repository${NC}" >&2
  exit 1
fi

HOOKS_DST="$TARGET_REPO/.git/hooks"
mkdir -p "$HOOKS_DST"

HOOK_NAMES=("post-commit" "post-merge")
INSTALLED=0

for hook_name in "${HOOK_NAMES[@]}"; do
  src="$HOOKS_SRC/$hook_name"
  dst="$HOOKS_DST/$hook_name"

  if [[ ! -f "$src" ]]; then
    echo -e "${RED}Error: source hook not found: $src${NC}" >&2
    continue
  fi

  # Backup existing hook
  if [[ -f "$dst" ]]; then
    cp "$dst" "${dst}.bak"
    echo -e "${YELLOW}Backed up existing $hook_name → ${hook_name}.bak${NC}"
  fi

  # Copy hook
  cp "$src" "$dst"

  # Embed GITNEXUS_STABLE_OPS path (macOS-compatible sed)
  sed -i.tmp "s|GITNEXUS_STABLE_OPS:-|GITNEXUS_STABLE_OPS:-$OPS_ROOT|" "$dst"
  rm -f "${dst}.tmp"

  chmod +x "$dst"
  INSTALLED=$((INSTALLED + 1))
  echo -e "${GREEN}Installed $hook_name → $HOOKS_DST/$hook_name${NC}"
done

echo ""
echo -e "${GREEN}Done: $INSTALLED hook(s) installed to $TARGET_REPO${NC}"
echo "Disable auto-reindex: export GITNEXUS_AUTO_REINDEX=0"
