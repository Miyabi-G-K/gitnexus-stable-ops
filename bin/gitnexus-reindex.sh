#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
GITNEXUS_BIN="${GITNEXUS_BIN:-$HOME/.local/bin/gitnexus-stable}"
REPOS_DIR="${REPOS_DIR:-$HOME/dev}"
LOOKBACK_HOURS="${LOOKBACK_HOURS:-24}"
LOG="${LOG:-/tmp/gitnexus-reindex.log}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_GRAPH_META="${RUN_GRAPH_META:-0}"
CHANGED=0
TOTAL=0
SKIPPED=0
FAILED=0

# Source common functions
source "$SCRIPT_DIR/../lib/common.sh"

if [[ ! -x "$GITNEXUS_BIN" ]]; then
  echo "ERROR: gitnexus stable wrapper not found: $GITNEXUS_BIN" >&2
  exit 1
fi

_reindex_dir() {
  local dir="$1"
  [[ -d "$dir/.git" ]] || return 0

  # Skip repos with no commits (git init only)
  if skip_empty_repo "$dir"; then
    return 0
  fi

  TOTAL=$((TOTAL + 1))

  local repo commits
  repo=$(basename "$dir")
  commits=$(cd "$dir" && git log --since="${LOOKBACK_HOURS}h" --oneline 2>/dev/null | wc -l | tr -d ' ')

  if [[ "$commits" -gt 0 ]]; then
    echo "CHANGED $repo: $commits commits in ${LOOKBACK_HOURS}h" >> "$LOG"
    local analyze_args=(analyze --force)
    if _has_embeddings "$dir"; then
      analyze_args+=(--embeddings)
    fi
    local injection_flag_value
    injection_flag_value="$(injection_flag)"
    if [[ -n "$injection_flag_value" ]]; then
      analyze_args+=("$injection_flag_value")
    fi
    if (cd "$dir" && "$GITNEXUS_BIN" "${analyze_args[@]}" >> "$LOG" 2>&1); then
      CHANGED=$((CHANGED + 1))
    else
      FAILED=$((FAILED + 1))
    fi
  else
    SKIPPED=$((SKIPPED + 1))
  fi
}

echo "=== GitNexus Re-index $(date) ===" > "$LOG"

for dir in "$REPOS_DIR"/*/; do
  [[ -d "$dir" ]] || continue
  _reindex_dir "$dir"
done

for category in "$REPOS_DIR"/0[1-9]-*/; do
  [[ -d "$category" ]] || continue
  for subdir in "$category"/*/; do
    [[ -d "$subdir" ]] || continue
    _reindex_dir "$subdir"
  done
done

echo "=== Summary: changed=$CHANGED skipped=$SKIPPED failed=$FAILED total=$TOTAL ===" >> "$LOG"

if [[ "$RUN_GRAPH_META" == "1" && "$CHANGED" -gt 0 ]]; then
  "$SCRIPT_DIR/graph-meta-update.sh" >> "$LOG" 2>&1 || true
fi

cat "$LOG"
