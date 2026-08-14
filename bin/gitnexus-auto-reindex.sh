#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_PATH="${REPO_PATH:-$PWD}"
GITNEXUS_BIN="${GITNEXUS_BIN:-$HOME/.local/bin/gitnexus-stable}"
USER_LOG_FILE="${LOG_FILE:-}"
LOG_FILE="${USER_LOG_FILE:-/tmp/gitnexus-auto-reindex-$(basename "$REPO_PATH").log}"
META_FILE="$REPO_PATH/.gitnexus/meta.json"
MAX_LOG_LINES="${MAX_LOG_LINES:-1000}"
ACTION="run"

# Source common functions
source "$SCRIPT_DIR/../lib/common.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
  local level="$1"
  shift
  local timestamp
  timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
  local msg="[$timestamp] [$level] $*"
  echo "$msg" >> "$LOG_FILE"
  case "$level" in
    INFO)  echo -e "${GREEN}$msg${NC}" ;;
    WARN)  echo -e "${YELLOW}$msg${NC}" ;;
    ERROR) echo -e "${RED}$msg${NC}" ;;
    *)     echo "$msg" ;;
  esac
}

rotate_log() {
  if [[ -f "$LOG_FILE" ]]; then
    local lines
    lines=$(wc -l < "$LOG_FILE")
    if (( lines > MAX_LOG_LINES )); then
      tail -n "$MAX_LOG_LINES" "$LOG_FILE" > "${LOG_FILE}.tmp"
      mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
  fi
}

get_index_status() {
  if [[ ! -f "$META_FILE" ]]; then
    echo "NOT_FOUND"
    return
  fi

  local indexed_commit
  indexed_commit=$(python3 -c "import json; print(json.load(open('$META_FILE')).get('lastCommit',''))" 2>/dev/null || echo "")
  local current_commit
  current_commit=$(cd "$REPO_PATH" && git rev-parse HEAD 2>/dev/null || echo "")

  if [[ -z "$indexed_commit" || -z "$current_commit" ]]; then
    echo "ERROR"
    return
  fi

  if [[ "$indexed_commit" == "$current_commit" ]]; then
    echo "CURRENT"
  else
    echo "STALE"
  fi
}

run_reindex() {
  local force="${1:-false}"
  local status

  status=$(get_index_status)
  if [[ "$status" == "CURRENT" && "$force" != "true" ]]; then
    log INFO "index is already current"
    return 0
  fi

  if [[ ! -x "$GITNEXUS_BIN" ]]; then
    log ERROR "gitnexus stable wrapper not found: $GITNEXUS_BIN"
    return 1
  fi

  local analyze_args=(analyze)
  if [[ "$force" == "true" ]]; then
    analyze_args+=(--force)
  fi
  local maybe_embeddings
  maybe_embeddings="$(embedding_flag "$REPO_PATH")"
  if [[ -n "$maybe_embeddings" ]]; then
    analyze_args+=("$maybe_embeddings")
  fi
  local maybe_injection
  maybe_injection="$(injection_flag)"
  if [[ -n "$maybe_injection" ]]; then
    analyze_args+=("$maybe_injection")
  fi

  log INFO "running: $GITNEXUS_BIN ${analyze_args[*]}"
  (
    cd "$REPO_PATH"
    "$GITNEXUS_BIN" "${analyze_args[@]}"
  )
}

for arg in "$@"; do
  case "$arg" in
    --check)
      ACTION="check"
      ;;
    --force)
      ACTION="force"
      ;;
    *)
      REPO_PATH="$arg"
      LOG_FILE="${USER_LOG_FILE:-/tmp/gitnexus-auto-reindex-$(basename "$REPO_PATH").log}"
      META_FILE="$REPO_PATH/.gitnexus/meta.json"
      ;;
  esac
done

mkdir -p "$(dirname "$LOG_FILE")"
rotate_log

case "$ACTION" in
  check)
    echo "$(get_index_status)"
    ;;
  force)
    run_reindex true
    ;;
  *)
    run_reindex false
    ;;
esac
