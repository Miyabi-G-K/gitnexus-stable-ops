#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GITNEXUS_BIN="${GITNEXUS_BIN:-$HOME/.local/bin/gitnexus-stable}"
REGISTRY_PATH="${REGISTRY_PATH:-$HOME/.gitnexus/registry.json}"
ALLOW_DIRTY_REINDEX="${ALLOW_DIRTY_REINDEX:-0}"

# Source common functions
source "$SCRIPT_DIR/../lib/common.sh"

if [[ ! -x "$GITNEXUS_BIN" ]]; then
  echo "ERROR: gitnexus stable wrapper not found: $GITNEXUS_BIN" >&2
  exit 1
fi

if [[ ! -f "$REGISTRY_PATH" ]]; then
  echo "ERROR: registry not found: $REGISTRY_PATH" >&2
  exit 1
fi

jq -r '.[].path' "$REGISTRY_PATH" | while IFS= read -r repo_path; do
  [[ -z "$repo_path" ]] && continue
  if [[ ! -d "$repo_path" ]]; then
    echo "SKIP: missing repo path $repo_path" >&2
    continue
  fi

  if [[ "$ALLOW_DIRTY_REINDEX" != "1" ]] && is_dirty_repo "$repo_path"; then
    echo "SKIP: dirty worktree $repo_path (set ALLOW_DIRTY_REINDEX=1 to override)" >&2
    continue
  fi

  analyze_args=(analyze --force)
  embedding_flag_value="$(embedding_flag "$repo_path")"
  if [[ -n "$embedding_flag_value" ]]; then
    analyze_args+=("$embedding_flag_value")
  fi
  injection_flag_value="$(injection_flag)"
  if [[ -n "$injection_flag_value" ]]; then
    analyze_args+=("$injection_flag_value")
  fi

  echo "== Reindex: $repo_path =="
  (
    cd "$repo_path"
    "$GITNEXUS_BIN" "${analyze_args[@]}"
  )
done
