#!/usr/bin/env bash
# gitnexus-agent-index.sh — CLI wrapper for Agent Graph Builder
# Ref: REQUIREMENTS-agent-context-graph-v2.md (FR-003-08)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/../lib"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

_log()  { echo -e "${GREEN}[agent-index]${NC} $*" >&2; }
_warn() { echo -e "${YELLOW}[agent-index]${NC} $*" >&2; }
_err()  { echo -e "${RED}[agent-index]${NC} $*" >&2; }

usage() {
  cat <<EOF
gitnexus-agent-index.sh — Agent Graph Indexer

Usage:
  gitnexus-agent-index.sh [OPTIONS] <repo-path>

Options:
  --force       Clear existing data before rebuild
  --dry-run     Parse only, no database write
  --json        Output stats as JSON
  --db <path>   Custom database path
  -h, --help    Show this help

Examples:
  gitnexus-agent-index.sh ~/dev/HAYASHI_SHUNSUKE
  gitnexus-agent-index.sh --force --json ~/dev/HAYASHI_SHUNSUKE
  gitnexus-agent-index.sh --dry-run ~/dev/HAYASHI_SHUNSUKE
EOF
}

main() {
  local repo_path=""
  local force=""
  local dry_run=""
  local json_flag=""
  local db_flag=""
  local db_path=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force) force="--force"; shift ;;
      --dry-run) dry_run="--dry-run"; shift ;;
      --json) json_flag="--json"; shift ;;
      --db) db_path="$2"; db_flag="--db $2"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      -*) _err "Unknown option: $1"; usage; exit 1 ;;
      *) repo_path="$1"; shift ;;
    esac
  done

  if [[ -z "$repo_path" ]]; then
    _err "Repository path required"
    usage
    exit 1
  fi

  if [[ ! -d "$repo_path" ]]; then
    _err "Directory not found: $repo_path"
    exit 1
  fi

  # Resolve to absolute path
  repo_path="$(cd "$repo_path" && pwd)"

  # Check Python
  if ! command -v python3 >/dev/null 2>&1; then
    _err "python3 not found"
    exit 1
  fi

  _log "Indexing Agent Graph for: $repo_path"

  # Build args
  local args=("build" "$repo_path")
  [[ -n "$force" ]] && args+=("$force")
  [[ -n "$dry_run" ]] && args+=("$dry_run")
  [[ -n "$json_flag" ]] && args+=("$json_flag")
  [[ -n "$db_path" ]] && args+=("--db" "$db_path")

  # Run builder
  python3 "$LIB_DIR/agent_graph_builder.py" "${args[@]}"

  local exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    _log "Agent Graph index complete"
  else
    _err "Agent Graph index failed (exit code: $exit_code)"
  fi
  return $exit_code
}

main "$@"
