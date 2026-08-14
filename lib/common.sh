#!/usr/bin/env bash
# Common functions for gitnexus-stable-ops scripts

# Check if a repository has embeddings enabled
# Usage: _has_embeddings "/path/to/repo"
# Returns: 0 if embeddings exist (count > 0), 1 otherwise
_has_embeddings() {
  local dir="$1"
  local meta="$dir/.gitnexus/meta.json"
  [[ -f "$meta" ]] || return 1
  local count
  count=$(jq -r '.stats.embeddings // 0' "$meta" 2>/dev/null || echo 0)
  [[ "$count" =~ ^[0-9]+$ ]] && (( count > 0 ))
}

# Get --embeddings flag if repo has embeddings
# Usage: embedding_flag "/path/to/repo"
# Output: "--embeddings" if embeddings exist, empty otherwise
embedding_flag() {
  local repo_path="${1:-.}"
  local meta_path="$repo_path/.gitnexus/meta.json"
  if [[ ! -f "$meta_path" ]]; then
    return 0
  fi

  local embedding_count
  embedding_count="$(jq -r '.stats.embeddings // 0' "$meta_path" 2>/dev/null || echo 0)"
  if [[ "$embedding_count" =~ ^[0-9]+$ ]] && (( embedding_count > 0 )); then
    echo "--embeddings"
  fi
}

# Check if a repository has uncommitted changes
# Usage: is_dirty_repo "/path/to/repo"
# Returns: 0 if dirty (has changes), 1 if clean
is_dirty_repo() {
  local repo_path="$1"
  [[ -d "$repo_path/.git" ]] || return 1
  [[ -n "$(git -C "$repo_path" status --porcelain --untracked-files=normal 2>/dev/null)" ]]
}

# Skip repositories with no commits (git init only)
# Usage: skip_empty_repo "/path/to/repo"
# Returns: 0 if should skip (empty), 1 if has commits
skip_empty_repo() {
  local repo_path="$1"
  [[ -d "$repo_path/.git" ]] || return 0
  ! (cd "$repo_path" && git rev-parse HEAD >/dev/null 2>&1)
}

# Get --index-only flag unless context-file injection is explicitly opted in.
#
# A bare `gitnexus analyze` writes AGENTS.md, CLAUDE.md and
# .claude/skills/gitnexus/ into the target repo. In unattended paths (git
# hooks, cron) that silently rewrites tracked, human-authored files on every
# commit, which is why injection is opt-in here and off by default —
# same stance as ALLOW_DIRTY_REINDEX and FORCE_REINDEX.
#
# Interactive `gitnexus analyze` is unaffected; this only governs the
# automated wrappers in bin/.
#
# Usage: injection_flag
# Output: "--index-only" unless GITNEXUS_INJECT_CONTEXT_FILES=1
injection_flag() {
  [[ "${GITNEXUS_INJECT_CONTEXT_FILES:-0}" == "1" ]] || echo "--index-only"
}
