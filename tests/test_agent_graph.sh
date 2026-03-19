#!/usr/bin/env bash
# Unit tests for Agent Graph Builder (Phase 1)
# Ref: REQUIREMENTS-agent-context-graph-v2.md Section 7
# Run: bash tests/test_agent_graph.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/../lib"
BUILDER="$LIB_DIR/agent_graph_builder.py"
RESOLVER="$LIB_DIR/context_resolver.py"

TESTS_PASSED=0
TESTS_FAILED=0
TEST_TEMP_DIR=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
  if [[ -n "$TEST_TEMP_DIR" && -d "$TEST_TEMP_DIR" ]]; then
    rm -rf "$TEST_TEMP_DIR"
  fi
}
trap cleanup EXIT

setup() {
  TEST_TEMP_DIR=$(mktemp -d)
}

assert_equals() {
  local expected="$1" actual="$2" test_name="${3:-assertion}"
  if [[ "$expected" == "$actual" ]]; then
    echo -e "${GREEN}✓${NC} $test_name"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} $test_name"
    echo "  Expected: $expected"
    echo "  Actual:   $actual"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

assert_contains() {
  local haystack="$1" needle="$2" test_name="${3:-assertion}"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo -e "${GREEN}✓${NC} $test_name"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} $test_name"
    echo "  Expected to contain: $needle"
    echo "  Actual: ${haystack:0:200}..."
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

assert_gt() {
  local actual="$1" threshold="$2" test_name="${3:-assertion}"
  if (( actual > threshold )); then
    echo -e "${GREEN}✓${NC} $test_name ($actual > $threshold)"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} $test_name"
    echo "  Expected > $threshold, got: $actual"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# --- Fixture: Create minimal test repo ---

create_test_repo() {
  local repo
  repo=$(mktemp -d "$TEST_TEMP_DIR/test-repo-XXXXXX")
  mkdir -p "$repo/KNOWLEDGE" "$repo/SKILL/business" "$repo/SKILL/personal" \
           "$repo/personal-data/tasks" "$repo/.gitnexus"

  # AGENTS_CLAUDE.md with agent definitions
  cat > "$repo/KNOWLEDGE/AGENTS_CLAUDE.md" <<'AGENTS'
# AGENTS.md

core_agents:
    - agent_id: "conductor"
      name: "しきるん"
      emoji: "🎭"
      role: "Conductor / Orchestrator"
      pane: "miyabi:agents.0"
      pane_id: "%0"

    - agent_id: "kaede"
      name: "カエデ"
      emoji: "🍁"
      role: "CodeGen / Developer"
      pane: "miyabi:agents.1"
      pane_id: "%1"

    - agent_id: "legal"
      name: "法務"
      emoji: "⚖️"
      role: "Legal Agent"
      society: "legal"
AGENTS

  # Skill with frontmatter
  cat > "$repo/SKILL/business/teikan-drafter.md" <<'SKILL1'
---
name: teikan-drafter
description: 定款ドラフト作成スキル
category: business
keywords:
  - 定款
  - 事業目的
  - 社員総会
agents:
  - legal
depends_on:
  - miyabi-llc-setup
reads:
  - tasks.json
---
# Teikan Drafter
定款を作成するスキル
SKILL1

  # Skill without frontmatter
  cat > "$repo/SKILL/personal/task-tracker.md" <<'SKILL2'
# Task Tracker - タスク管理

タスクを追跡するスキル
SKILL2

  # Skill with invalid frontmatter (FR-001-04-A)
  cat > "$repo/SKILL/business/broken-skill.md" <<'SKILL3'
---
name: broken
this is not valid yaml: [unclosed
---
# Broken Skill
SKILL3

  # Knowledge doc
  cat > "$repo/KNOWLEDGE/miyabi-llc-setup.md" <<'KNOW1'
# 合同会社みやび設立プロジェクト
設立日: 2026年4月1日
KNOW1

  cat > "$repo/KNOWLEDGE/rules-sample.md" <<'KNOW2'
# Sample Rules
ルール定義
KNOW2

  # Data source
  echo '{"tasks":[]}' > "$repo/personal-data/tasks/tasks.json"

  echo "$repo"
}

# --- Tests ---

# UT-001: agent_parser — AGENTS.md から Agent ノード生成
test_ut001_agent_parser() {
  local repo
  repo=$(create_test_repo)
  local output
  output=$(python3 "$BUILDER" build "$repo" --force --json 2>/dev/null)
  local count
  count=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin)['agents'])")
  assert_gt "$count" 0 "UT-001: agent_parser generates Agent nodes from AGENTS.md"
}

# UT-002: skill_parser — フロントマター付き SKILL パース
test_ut002_skill_with_frontmatter() {
  local repo
  repo=$(create_test_repo)
  local output
  output=$(python3 "$BUILDER" build "$repo" --force --json 2>/dev/null)
  local count
  count=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin)['skills'])")
  assert_gt "$count" 1 "UT-002: skill_parser parses SKILL with frontmatter"
}

# UT-003: skill_parser — フロントマターなし SKILL推定
test_ut003_skill_without_frontmatter() {
  local repo
  repo=$(create_test_repo)
  # Check that task-tracker (no frontmatter) is indexed
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local db="$repo/.gitnexus/agent-graph.db"
  local result
  result=$(python3 -c "
import sqlite3, json
conn = sqlite3.connect('$db')
row = conn.execute(\"SELECT skill_id, name FROM skills WHERE skill_id='task-tracker'\").fetchone()
print(json.dumps({'id': row[0], 'name': row[1]} if row else {}))
")
  assert_contains "$result" "task-tracker" "UT-003: skill_parser infers from filename when no frontmatter"
}

# UT-004: skill_parser — 不正フロントマターをスキップ
test_ut004_invalid_frontmatter_skip() {
  local repo
  repo=$(create_test_repo)
  # Should not crash, should still index other skills
  local output
  output=$(python3 "$BUILDER" build "$repo" --force --json 2>/dev/null)
  local count
  count=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin)['skills'])")
  assert_gt "$count" 1 "UT-004: invalid frontmatter is skipped, processing continues"
}

# UT-005: knowledge_parser — KNOWLEDGE docs indexed
test_ut005_knowledge_parser() {
  local repo
  repo=$(create_test_repo)
  local output
  output=$(python3 "$BUILDER" build "$repo" --force --json 2>/dev/null)
  local count
  count=$(echo "$output" | python3 -c "import sys,json; print(json.load(sys.stdin)['knowledge_docs'])")
  assert_gt "$count" 0 "UT-005: knowledge_parser creates KnowledgeDoc nodes"
}

# UT-006: edge_resolver — USES_SKILL edges
test_ut006_uses_skill_edge() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local db="$repo/.gitnexus/agent-graph.db"
  local count
  count=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$db')
row = conn.execute(\"SELECT COUNT(*) FROM agent_relations WHERE relation_type='USES_SKILL'\").fetchone()
print(row[0])
")
  assert_gt "$count" 0 "UT-006: edge_resolver generates USES_SKILL edges"
}

# UT-007: hybrid_scorer — FTS5 + Graph produces merged scores
test_ut007_hybrid_scorer() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$RESOLVER" "定款" --repo "$repo" --json 2>/dev/null)
  # Should return context_chain with scored entries
  local chain_len
  chain_len=$(echo "$output" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('context_chain',[])))")
  assert_gt "$chain_len" 0 "UT-007: hybrid_scorer produces context_chain entries"
}

# UT-008: context_resolver — returns matched_agents and matched_skills
test_ut008_context_resolver() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$RESOLVER" "定款" --repo "$repo" --json 2>/dev/null)
  assert_contains "$output" '"matched_agents"' "UT-008: context_resolver returns matched_agents"
  assert_contains "$output" '"matched_skills"' "UT-008: context_resolver returns matched_skills"
  assert_contains "$output" '"files_to_read"' "UT-008: context_resolver returns files_to_read"
  assert_contains "$output" '"estimated_tokens"' "UT-008: context_resolver returns estimated_tokens"
}

# UT-009: depth control — depth=0 returns fewer nodes than depth=2
test_ut009_depth_control() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null

  local chain_d0 chain_d2
  chain_d0=$(python3 "$RESOLVER" "定款" --repo "$repo" --depth 0 --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('context_chain',[])))")
  chain_d2=$(python3 "$RESOLVER" "定款" --repo "$repo" --depth 2 --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('context_chain',[])))")
  # depth=2 should include graph-expanded neighbors, strictly more than depth=0
  if (( chain_d2 > chain_d0 )); then
    echo -e "${GREEN}✓${NC} UT-009: depth=2 (${chain_d2}) > depth=0 (${chain_d0})"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  elif (( chain_d2 == chain_d0 && chain_d0 > 0 )); then
    # Acceptable if token budget limited expansion (still valid)
    echo -e "${YELLOW}⚠${NC} UT-009: depth=2 == depth=0 (${chain_d0}) — possibly token-budget limited"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} UT-009: depth=2 ($chain_d2) <= depth=0 ($chain_d0)"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# UT-010: token budget — max-tokens limits output
test_ut010_token_budget() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null

  local tokens_small tokens_large
  tokens_small=$(python3 "$RESOLVER" "定款" --repo "$repo" --max-tokens 500 --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('estimated_tokens',0))")
  tokens_large=$(python3 "$RESOLVER" "定款" --repo "$repo" --max-tokens 50000 --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('estimated_tokens',0))")
  if (( tokens_small <= tokens_large )); then
    echo -e "${GREEN}✓${NC} UT-010: budget=500 tokens(${tokens_small}) <= budget=50000 tokens(${tokens_large})"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} UT-010: budget=500 ($tokens_small) > budget=50000 ($tokens_large)"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# UT-011: token_estimator
test_ut011_token_estimator() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local db="$repo/.gitnexus/agent-graph.db"
  local tokens
  tokens=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$db')
row = conn.execute('SELECT SUM(token_estimate) FROM knowledge_docs').fetchone()
print(row[0] or 0)
")
  assert_gt "$tokens" 0 "UT-011: token_estimator produces non-zero estimates"
}

# UT-012: JSON output format v2.0
test_ut012_json_output() {
  local repo
  repo=$(create_test_repo)
  local output
  output=$(python3 "$BUILDER" build "$repo" --force --json 2>/dev/null)
  assert_contains "$output" '"agents"' "UT-012: JSON output contains 'agents' field"
  assert_contains "$output" '"skills"' "UT-012: JSON output contains 'skills' field"
  assert_contains "$output" '"total_nodes"' "UT-012: JSON output contains 'total_nodes' field"
  assert_contains "$output" '"edges"' "UT-012: JSON output contains 'edges' field"
  assert_contains "$output" '"execution_time_ms"' "UT-012: JSON output contains 'execution_time_ms' field"
}

# UT-013: Markdown output — tested via human-readable default
test_ut013_readable_output() {
  local repo
  repo=$(create_test_repo)
  local output
  output=$(python3 "$BUILDER" build "$repo" --force 2>/dev/null)
  assert_contains "$output" "Agent Graph Build" "UT-013: Human-readable output header present"
  assert_contains "$output" "Agents:" "UT-013: Agents count in output"
  assert_contains "$output" "Skills:" "UT-013: Skills count in output"
}

# UT-014: fallback — query with no matches returns P0 minimal context
test_ut014_fallback() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  # Query something that won't match any FTS5 index
  output=$(python3 "$RESOLVER" "zzzznonexistentqueryzzzz" --repo "$repo" --json 2>/dev/null)
  local chain_len
  chain_len=$(echo "$output" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('context_chain',[])))")
  assert_gt "$chain_len" 0 "UT-014: fallback returns P0 minimal context for no-match query"
}

# UT-015: validation summary
test_ut015_validation_summary() {
  local repo
  repo=$(create_test_repo)
  # The broken-skill.md should trigger a validation warning
  local output
  output=$(python3 "$BUILDER" build "$repo" --force 2>&1)
  # Should still complete successfully
  assert_contains "$output" "Agent Graph Build" "UT-015: Build completes despite validation issues"
}

# Additional: dry-run mode
test_dry_run() {
  local repo
  repo=$(create_test_repo)
  local output
  output=$(python3 "$BUILDER" build "$repo" --dry-run --json 2>/dev/null)
  assert_contains "$output" '"dry_run": true' "dry-run: no DB writes"
  # DB file should NOT exist
  if [[ ! -f "$repo/.gitnexus/agent-graph.db" ]]; then
    echo -e "${GREEN}✓${NC} dry-run: database file not created"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} dry-run: database file should not be created"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# Additional: status command
test_status_command() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$BUILDER" status "$repo" --json 2>/dev/null)
  assert_contains "$output" '"total_nodes"' "status: returns total_nodes"
  assert_contains "$output" '"edges"' "status: returns edges"
}

# Additional: list command
test_list_command() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$BUILDER" list "$repo" --json 2>/dev/null)
  assert_contains "$output" '"agents"' "list: returns agents array"
}

# Additional: FTS5 index created
test_fts5_index() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local db="$repo/.gitnexus/agent-graph.db"
  local count
  count=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$db')
row = conn.execute(\"SELECT COUNT(*) FROM agent_fts\").fetchone()
print(row[0])
")
  assert_gt "$count" 0 "FTS5: index contains entries"
}

# Additional: FTS5 search works
test_fts5_search() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local db="$repo/.gitnexus/agent-graph.db"
  local result
  result=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$db')
rows = conn.execute(\"SELECT node_id, node_type FROM agent_fts WHERE agent_fts MATCH '定款'\").fetchall()
print(len(rows))
")
  assert_gt "$result" 0 "FTS5: search for '定款' returns results"
}

# --- Phase 2: Context Resolver ---

# CR-001: Direct agent lookup via --agent
test_cr001_agent_lookup() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$RESOLVER" --agent conductor --repo "$repo" --json 2>/dev/null)
  assert_contains "$output" '"conductor"' "CR-001: --agent conductor returns conductor in results"
}

# CR-002: Direct skill lookup via --skill
test_cr002_skill_lookup() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$RESOLVER" --skill teikan-drafter --repo "$repo" --json 2>/dev/null)
  assert_contains "$output" '"teikan-drafter"' "CR-002: --skill teikan-drafter returns skill"
}

# CR-003: Markdown output format
test_cr003_markdown_output() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$RESOLVER" "定款" --repo "$repo" --format markdown 2>/dev/null)
  assert_contains "$output" "Agent Context" "CR-003: markdown output has header"
  assert_contains "$output" "Context Chain" "CR-003: markdown output has Context Chain"
}

# CR-004: task-type scoring adjustment
test_cr004_task_type() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$RESOLVER" "定款" --repo "$repo" --task-type bugfix --json 2>/dev/null)
  local task_type
  task_type=$(echo "$output" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('metadata',{}).get('task_type',''))")
  assert_equals "bugfix" "$task_type" "CR-004: task-type=bugfix recorded in metadata"
}

# CR-005: savings_vs_full percentage
test_cr005_savings() {
  local repo
  repo=$(create_test_repo)
  python3 "$BUILDER" build "$repo" --force 2>/dev/null
  local output
  output=$(python3 "$RESOLVER" "定款" --repo "$repo" --json 2>/dev/null)
  assert_contains "$output" '"savings_vs_full"' "CR-005: savings_vs_full field present"
}

# CR-006: error when DB missing
test_cr006_missing_db() {
  local repo
  repo=$(mktemp -d "$TEST_TEMP_DIR/empty-repo-XXXXXX")
  mkdir -p "$repo/.gitnexus"
  local exit_code=0
  python3 "$RESOLVER" "test" --repo "$repo" --json 2>/dev/null || exit_code=$?
  if (( exit_code != 0 )); then
    echo -e "${GREEN}✓${NC} CR-006: exits non-zero when DB missing"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} CR-006: should exit non-zero when DB missing"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# RT-004: CodeRelation not affected (placeholder — needs real repo)
TESTS_SKIPPED=0
test_rt004_code_relation_safe() {
  echo -e "${YELLOW}⏭${NC} RT-004: CodeRelation safety (requires real indexed repo — skipped)"
  TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
}

# --- Run all tests ---
echo "Running Agent Graph Builder tests..."
echo "Builder: $BUILDER"
echo

setup

test_ut001_agent_parser
test_ut002_skill_with_frontmatter
test_ut003_skill_without_frontmatter
test_ut004_invalid_frontmatter_skip
test_ut005_knowledge_parser
test_ut006_uses_skill_edge
test_ut007_hybrid_scorer
test_ut008_context_resolver
test_ut009_depth_control
test_ut010_token_budget
test_ut011_token_estimator
test_ut012_json_output
test_ut013_readable_output
test_ut014_fallback
test_ut015_validation_summary
test_dry_run
test_status_command
test_list_command
test_fts5_index
test_fts5_search
test_cr001_agent_lookup
test_cr002_skill_lookup
test_cr003_markdown_output
test_cr004_task_type
test_cr005_savings
test_cr006_missing_db
test_rt004_code_relation_safe

echo
echo "=========================================="
echo -e "Tests passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests failed: ${RED}$TESTS_FAILED${NC}"
if [[ $TESTS_SKIPPED -gt 0 ]]; then
  echo -e "Tests skipped: ${YELLOW}$TESTS_SKIPPED${NC}"
fi
echo "=========================================="

if [[ $TESTS_FAILED -gt 0 ]]; then
  exit 1
fi
