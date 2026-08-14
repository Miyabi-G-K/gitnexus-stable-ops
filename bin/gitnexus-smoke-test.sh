#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <repo_path> <repo_name> <symbol_name>" >&2
  exit 1
fi

REPO_PATH="$1"
REPO_NAME="$2"
SYMBOL_NAME="$3"
GITNEXUS_BIN="${GITNEXUS_BIN:-$HOME/.local/bin/gitnexus-stable}"
FORCE_REINDEX="${FORCE_REINDEX:-1}"
ALLOW_DIRTY_REINDEX="${ALLOW_DIRTY_REINDEX:-0}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Source common functions
source "$SCRIPT_DIR/../lib/common.sh"

if [[ ! -x "$GITNEXUS_BIN" ]]; then
  echo "ERROR: gitnexus stable wrapper not found: $GITNEXUS_BIN" >&2
  exit 1
fi

# embedding_flag and is_dirty_repo are provided by lib/common.sh

SMOKE_TMP=$(mktemp -d /tmp/gitnexus-smoke-XXXXXX)
trap 'rm -rf "$SMOKE_TMP"' EXIT

echo "== Smoke Test =="
echo "repo_path: $REPO_PATH"
echo "repo_name: $REPO_NAME"
echo "symbol_name: $SYMBOL_NAME"

if [[ "$FORCE_REINDEX" == "1" ]]; then
  if [[ "$ALLOW_DIRTY_REINDEX" != "1" ]] && is_dirty_repo "$REPO_PATH"; then
    echo "SKIP: analyze --force on dirty worktree $REPO_PATH (set ALLOW_DIRTY_REINDEX=1 to override)"
  else
    analyze_args=(analyze --force)
    embedding_flag="$(embedding_flag "$REPO_PATH")"
    if [[ -n "$embedding_flag" ]]; then
      analyze_args+=("$embedding_flag")
    fi
    injection_flag_value="$(injection_flag)"
    if [[ -n "$injection_flag_value" ]]; then
      analyze_args+=("$injection_flag_value")
    fi
    (cd "$REPO_PATH" && "$GITNEXUS_BIN" "${analyze_args[@]}" >"$SMOKE_TMP/analyze.log" 2>&1)
  fi
fi

(cd "$REPO_PATH" && "$GITNEXUS_BIN" status | tee "$SMOKE_TMP/status.log")
(cd "$REPO_PATH" && "$GITNEXUS_BIN" list >"$SMOKE_TMP/list.log")

context_json="$(cd "$REPO_PATH" && "$GITNEXUS_BIN" context --repo "$REPO_NAME" "$SYMBOL_NAME" 2>&1)"
echo "$context_json" | jq -e '.status == "found"' >/dev/null

cypher_query="MATCH (n) WHERE n.name = '$SYMBOL_NAME' RETURN n.name, n.filePath LIMIT 1"
cypher_json="$(cd "$REPO_PATH" && "$GITNEXUS_BIN" cypher --repo "$REPO_NAME" "$cypher_query" 2>&1)"
echo "$cypher_json" | jq -e '.row_count >= 1' >/dev/null

impact_json="$(cd "$REPO_PATH" && "$SCRIPT_DIR/gitnexus-safe-impact.sh" "$REPO_NAME" "$SYMBOL_NAME")"
echo "$impact_json" | jq -e '.target.name == "'"$SYMBOL_NAME"'"' >/dev/null

echo "PASS: analyze/status/list/context/cypher/impact"
