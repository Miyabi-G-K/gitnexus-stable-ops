#!/usr/bin/env bash
# Unit tests for git hooks and install-hooks script
# Run: bash tests/test_hooks.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_SCRIPT="$OPS_ROOT/bin/gitnexus-install-hooks.sh"

TESTS_PASSED=0
TESTS_FAILED=0
TEST_TEMP_DIR=""

# Colors
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
  local expected="$1"
  local actual="$2"
  local test_name="${3:-assertion}"

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

assert_success() {
  local test_name="$1"
  echo -e "${GREEN}✓${NC} $test_name"
  TESTS_PASSED=$((TESTS_PASSED + 1))
}

assert_file_exists() {
  local filepath="$1"
  local test_name="$2"

  if [[ -f "$filepath" ]]; then
    echo -e "${GREEN}✓${NC} $test_name"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} $test_name"
    echo "  File not found: $filepath"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

assert_file_executable() {
  local filepath="$1"
  local test_name="$2"

  if [[ -x "$filepath" ]]; then
    echo -e "${GREEN}✓${NC} $test_name"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}✗${NC} $test_name"
    echo "  File not executable: $filepath"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# Create a temporary git repo for testing
create_test_repo() {
  local repo_dir="$TEST_TEMP_DIR/$1"
  mkdir -p "$repo_dir"
  (cd "$repo_dir" && git init -q && git config user.email "test@test.com" && git config user.name "Test" && touch README.md && git add . && git commit -q -m "init")
  echo "$repo_dir"
}

# --- Test: install-hooks creates post-commit and post-merge ---
test_install_creates_hooks() {
  local repo
  repo=$(create_test_repo "install-test")

  bash "$INSTALL_SCRIPT" "$repo" >/dev/null 2>&1

  assert_file_exists "$repo/.git/hooks/post-commit" "install-hooks creates post-commit"
  assert_file_exists "$repo/.git/hooks/post-merge" "install-hooks creates post-merge"
  assert_file_executable "$repo/.git/hooks/post-commit" "post-commit is executable"
  assert_file_executable "$repo/.git/hooks/post-merge" "post-merge is executable"
}

# --- Test: existing hooks are backed up ---
test_existing_hooks_backed_up() {
  local repo
  repo=$(create_test_repo "backup-test")

  # Create existing hooks
  mkdir -p "$repo/.git/hooks"
  echo "#!/bin/bash" > "$repo/.git/hooks/post-commit"
  echo "echo original" >> "$repo/.git/hooks/post-commit"
  echo "#!/bin/bash" > "$repo/.git/hooks/post-merge"
  echo "echo original" >> "$repo/.git/hooks/post-merge"

  bash "$INSTALL_SCRIPT" "$repo" >/dev/null 2>&1

  assert_file_exists "$repo/.git/hooks/post-commit.bak" "existing post-commit backed up"
  assert_file_exists "$repo/.git/hooks/post-merge.bak" "existing post-merge backed up"

  # Verify backup content
  local bak_content
  bak_content=$(cat "$repo/.git/hooks/post-commit.bak")
  if echo "$bak_content" | grep -q "echo original"; then
    assert_success "backup contains original content"
  else
    echo -e "${RED}✗${NC} backup contains original content"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# --- Test: GITNEXUS_AUTO_REINDEX=0 makes hook exit immediately ---
test_auto_reindex_disabled() {
  local repo
  repo=$(create_test_repo "disable-test")

  bash "$INSTALL_SCRIPT" "$repo" >/dev/null 2>&1

  # Run the hook with GITNEXUS_AUTO_REINDEX=0
  local exit_code=0
  (cd "$repo" && GITNEXUS_AUTO_REINDEX=0 bash .git/hooks/post-commit) || exit_code=$?

  assert_equals "0" "$exit_code" "hook exits 0 when GITNEXUS_AUTO_REINDEX=0"
}

# --- Test: hook exits 0 when reindex script not found ---
test_reindex_script_not_found() {
  local repo
  repo=$(create_test_repo "notfound-test")

  # Create a minimal hook that won't find the reindex script
  mkdir -p "$repo/.git/hooks"
  cat > "$repo/.git/hooks/post-commit" << 'HOOKEOF'
#!/usr/bin/env bash
[[ "${GITNEXUS_AUTO_REINDEX:-1}" == "0" ]] && exit 0

REINDEX_SCRIPT="/nonexistent/path/gitnexus-auto-reindex.sh"
[[ ! -x "$REINDEX_SCRIPT" ]] && exit 0

REPO_PATH="$(git rev-parse --show-toplevel 2>/dev/null)" \
  nohup "$REINDEX_SCRIPT" >/dev/null 2>&1 &
HOOKEOF
  chmod +x "$repo/.git/hooks/post-commit"

  local exit_code=0
  (cd "$repo" && GITNEXUS_STABLE_OPS="/nonexistent" bash .git/hooks/post-commit) || exit_code=$?

  assert_equals "0" "$exit_code" "hook exits 0 when reindex script not found"
}

# --- Test: install-hooks fails on non-git directory ---
test_install_fails_non_git() {
  local non_git_dir="$TEST_TEMP_DIR/not-a-repo"
  mkdir -p "$non_git_dir"

  local exit_code=0
  bash "$INSTALL_SCRIPT" "$non_git_dir" >/dev/null 2>&1 || exit_code=$?

  if [[ "$exit_code" -ne 0 ]]; then
    assert_success "install-hooks fails on non-git directory"
  else
    echo -e "${RED}✗${NC} install-hooks fails on non-git directory"
    echo "  Expected non-zero exit code, got 0"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# --- Test: installed hook contains OPS_ROOT path ---
test_installed_hook_has_ops_path() {
  local repo
  repo=$(create_test_repo "path-test")

  bash "$INSTALL_SCRIPT" "$repo" >/dev/null 2>&1

  if grep -q "$OPS_ROOT" "$repo/.git/hooks/post-commit"; then
    assert_success "installed hook contains GITNEXUS_STABLE_OPS path"
  else
    echo -e "${RED}✗${NC} installed hook contains GITNEXUS_STABLE_OPS path"
    echo "  OPS_ROOT ($OPS_ROOT) not found in hook"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi
}

# Run tests
echo "Running tests for git hooks..."
echo

setup

test_install_creates_hooks
test_existing_hooks_backed_up
test_auto_reindex_disabled
test_reindex_script_not_found
test_install_fails_non_git
test_installed_hook_has_ops_path

echo
echo "=========================================="
echo -e "Tests passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests failed: ${RED}$TESTS_FAILED${NC}"
echo "=========================================="

if [[ $TESTS_FAILED -gt 0 ]]; then
  exit 1
fi
