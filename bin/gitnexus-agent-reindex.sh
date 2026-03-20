#!/usr/bin/env bash
# Agent Graph reindex — rebuild agent-graph.db for a repository
# Usage: bin/gitnexus-agent-reindex.sh [/path/to/repo] [--force] [--json]
#
# Detects if SKILL/, AGENTS.md, or KNOWLEDGE/ have changed since last build
# and only rebuilds when necessary (unless --force).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_GRAPH_PY="$OPS_ROOT/lib/agent_graph_builder.py"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

_log()  { echo -e "${GREEN}[agent-reindex]${NC} $*" >&2; }
_warn() { echo -e "${YELLOW}[agent-reindex]${NC} $*" >&2; }
_err()  { echo -e "${RED}[agent-reindex]${NC} $*" >&2; }

REPO_PATH=""
FORCE=0
JSON_OUTPUT=0
EXTRA_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --json) JSON_OUTPUT=1; EXTRA_ARGS+=("--json"); shift ;;
    -*) EXTRA_ARGS+=("$1"); shift ;;
    *)
      if [[ -z "$REPO_PATH" ]]; then
        REPO_PATH="$1"
      fi
      shift
      ;;
  esac
done

REPO_PATH="${REPO_PATH:-$(pwd)}"

if [[ ! -d "$REPO_PATH" ]]; then
  _err "Directory not found: $REPO_PATH"
  exit 1
fi

REPO_PATH="$(cd "$REPO_PATH" && pwd)"
DB_PATH="$REPO_PATH/.gitnexus/agent-graph.db"
STAMP_FILE="$REPO_PATH/.gitnexus/agent-graph.stamp"

# Check if rebuild is needed
needs_rebuild() {
  [[ $FORCE -eq 1 ]] && return 0
  [[ ! -f "$DB_PATH" ]] && return 0
  [[ ! -f "$STAMP_FILE" ]] && return 0

  local stamp_time
  stamp_time=$(stat -c "%Y" "$STAMP_FILE" 2>/dev/null || stat -f "%m" "$STAMP_FILE" 2>/dev/null || echo 0)

  # Check SKILL/, KNOWLEDGE/, AGENTS.md for changes
  local changed=0
  for dir in "SKILL" "KNOWLEDGE" "AGENT"; do
    if [[ -d "$REPO_PATH/$dir" ]]; then
      while IFS= read -r -d '' f; do
        local ft
        ft=$(stat -c "%Y" "$f" 2>/dev/null || stat -f "%m" "$f" 2>/dev/null || echo 0)
        if [[ "$ft" -gt "$stamp_time" ]]; then
          changed=1
          break
        fi
      done < <(find "$REPO_PATH/$dir" -type f -name "*.md" -print0 2>/dev/null)
      [[ $changed -eq 1 ]] && break
    fi
  done

  # Also check AGENTS.md at root
  if [[ $changed -eq 0 && -f "$REPO_PATH/AGENTS.md" ]]; then
    local at
    at=$(stat -c "%Y" "$REPO_PATH/AGENTS.md" 2>/dev/null || stat -f "%m" "$REPO_PATH/AGENTS.md" 2>/dev/null || echo 0)
    [[ "$at" -gt "$stamp_time" ]] && changed=1
  fi

  # Check personal-data changes
  if [[ $changed -eq 0 && -d "$REPO_PATH/personal-data" ]]; then
    while IFS= read -r -d '' f; do
      local ft
      ft=$(stat -c "%Y" "$f" 2>/dev/null || stat -f "%m" "$f" 2>/dev/null || echo 0)
      if [[ "$ft" -gt "$stamp_time" ]]; then
        changed=1
        break
      fi
    done < <(find "$REPO_PATH/personal-data" -type f -name "*.json" -print0 2>/dev/null)
  fi

  return $((1 - changed))
}

if ! needs_rebuild; then
  _log "Agent Graph is up-to-date (use --force to rebuild)"
  if [[ $JSON_OUTPUT -eq 1 ]]; then
    echo '{"status": "up-to-date", "skipped": true}'
  fi
  exit 0
fi

_log "Rebuilding Agent Graph for $REPO_PATH"

# Run the builder
BUILD_ARGS=(build "$REPO_PATH" --force)
[[ $JSON_OUTPUT -eq 1 ]] && BUILD_ARGS+=(--json)

if python3 "$AGENT_GRAPH_PY" "${BUILD_ARGS[@]}"; then
  # Update stamp file
  mkdir -p "$(dirname "$STAMP_FILE")"
  touch "$STAMP_FILE"
  _log "Agent Graph rebuilt successfully"
else
  _err "Agent Graph rebuild failed"
  exit 1
fi
