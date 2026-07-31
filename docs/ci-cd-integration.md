# CI/CD Integration Guide

Integrate `gitnexus-stable-ops` into your CI/CD pipeline for automated code intelligence.

---

## Table of Contents

1. [GitHub Actions](#github-actions)
2. [GitLab CI/CD](#gitlab-cicd)
3. [Pre-merge Impact Analysis](#pre-merge-impact-analysis)
4. [Post-merge Reindex](#post-merge-reindex)
5. [Smoke Test on Deploy](#smoke-test-on-deploy)
6. [Caching Strategies](#caching-strategies)
7. [Docker-based Pipelines](#docker-based-pipelines)

---

## GitHub Actions

### Post-merge Reindex

Automatically reindex after every merge to `main`:

```yaml
# .github/workflows/gitnexus-reindex.yml
name: GitNexus Reindex

on:
  push:
    branches: [main]

jobs:
  reindex:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for accurate change detection

      - name: Cache GitNexus graph
        uses: actions/cache@v4
        with:
          path: ~/.gitnexus
          key: gitnexus-${{ github.repository }}-${{ github.sha }}
          restore-keys: |
            gitnexus-${{ github.repository }}-

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '22'

      - name: Install GitNexus
        run: npm install -g gitnexus@1.4.6

      - name: Install gitnexus-stable-ops
        run: |
          git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops /opt/stable-ops
          cd /opt/stable-ops && make install

      - name: Smart reindex (skip if up-to-date)
        run: REPO_PATH=$GITHUB_WORKSPACE /opt/stable-ops/bin/gitnexus-auto-reindex.sh
        env:
          GITNEXUS_BIN: ~/.local/bin/gitnexus-stable
          ALLOW_DIRTY_REINDEX: "0"

      - name: Health check
        run: /opt/stable-ops/bin/gitnexus-doctor.sh $GITHUB_WORKSPACE ${{ github.event.repository.name }}
```

### Pre-merge Impact Analysis

Comment blast radius on every PR that touches core symbols:

```yaml
# .github/workflows/gitnexus-impact.yml
name: GitNexus Impact Analysis

on:
  pull_request:
    branches: [main]

permissions:
  pull-requests: write

jobs:
  impact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Restore GitNexus graph cache
        uses: actions/cache/restore@v4
        with:
          path: ~/.gitnexus
          key: gitnexus-${{ github.repository }}-${{ github.base_ref }}

      - name: Install tools
        run: |
          npm install -g gitnexus@1.4.6
          git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops /opt/stable-ops
          cd /opt/stable-ops && make install

      - name: Run impact analysis on changed files
        id: impact
        run: |
          CHANGED=$(git diff --name-only origin/${{ github.base_ref }}...HEAD)
          IMPACT_REPORT="/tmp/impact-report.md"
          echo "## GitNexus Impact Analysis" > $IMPACT_REPORT
          echo "" >> $IMPACT_REPORT
          echo "Changed files: $(echo "$CHANGED" | wc -l)" >> $IMPACT_REPORT
          echo "" >> $IMPACT_REPORT

          for FILE in $CHANGED; do
            SYMBOLS=$(gitnexus list-symbols $FILE 2>/dev/null | head -5)
            for SYM in $SYMBOLS; do
              RESULT=$(/opt/stable-ops/bin/gni impact "$SYM" --json 2>/dev/null)
              RISK=$(echo $RESULT | jq -r '.risk_level // "UNKNOWN"')
              if [ "$RISK" = "HIGH" ] || [ "$RISK" = "CRITICAL" ]; then
                echo "### ⚠️ $SYM ($RISK)" >> $IMPACT_REPORT
                echo "$RESULT" | jq -r '.callers[]? | "- \(.name) (\(.file))"' >> $IMPACT_REPORT
              fi
            done
          done

          echo "report<<EOF" >> $GITHUB_OUTPUT
          cat $IMPACT_REPORT >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT

      - name: Post impact comment
        uses: actions/github-script@v7
        with:
          script: |
            const report = `${{ steps.impact.outputs.report }}`;
            if (report.includes('⚠️')) {
              github.rest.issues.createComment({
                issue_number: context.issue.number,
                owner: context.repo.owner,
                repo: context.repo.repo,
                body: report
              });
            }
```

### Weekly Full Reindex

```yaml
# .github/workflows/gitnexus-weekly.yml
name: GitNexus Weekly Full Reindex

on:
  schedule:
    - cron: '0 4 * * 0'  # Sunday 4 AM UTC

jobs:
  full-reindex:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install tools
        run: |
          npm install -g gitnexus@1.4.6
          git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops /opt/stable-ops
          cd /opt/stable-ops && make install

      - name: Full reindex with embeddings
        run: |
          cd /opt/stable-ops
          FORCE_REINDEX=1 REPO_PATH=$GITHUB_WORKSPACE bin/gitnexus-auto-reindex.sh

      - name: Upload graph artifact
        uses: actions/upload-artifact@v4
        with:
          name: gitnexus-graph-weekly-${{ github.run_id }}
          path: ~/.gitnexus/
          retention-days: 30
```

---

## GitLab CI/CD

```yaml
# .gitlab-ci.yml
stages:
  - analyze
  - reindex
  - verify

variables:
  GITNEXUS_VERSION: "1.4.6"
  GITNEXUS_BIN: "$HOME/.local/bin/gitnexus-stable"

.gitnexus_setup: &gitnexus_setup
  before_script:
    - npm install -g gitnexus@${GITNEXUS_VERSION}
    - git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops /opt/stable-ops
    - cd /opt/stable-ops && make install

impact-analysis:
  stage: analyze
  <<: *gitnexus_setup
  script:
    - REPO_PATH=$CI_PROJECT_DIR /opt/stable-ops/bin/gitnexus-smoke-test.sh
  only:
    - merge_requests
  cache:
    key: gitnexus-${CI_PROJECT_NAME}
    paths:
      - .gitnexus/

post-merge-reindex:
  stage: reindex
  <<: *gitnexus_setup
  script:
    - REPO_PATH=$CI_PROJECT_DIR /opt/stable-ops/bin/gitnexus-auto-reindex.sh
  only:
    - main
  cache:
    key: gitnexus-${CI_PROJECT_NAME}
    paths:
      - .gitnexus/
    policy: push

health-check:
  stage: verify
  <<: *gitnexus_setup
  script:
    - /opt/stable-ops/bin/gitnexus-doctor.sh $CI_PROJECT_DIR $CI_PROJECT_NAME
  allow_failure: true
```

---

## Pre-merge Impact Analysis

### Using `gni` wrapper directly

The `bin/gni` wrapper always returns exit code 0 and valid output even when GitNexus crashes internally, making it pipeline-safe:

```bash
#!/bin/bash
# pre-merge-check.sh — Run before merging any PR

REPO=$1
CHANGED_FILES=$(git diff --name-only origin/main...HEAD)

HIGH_RISK_COUNT=0
for FILE in $CHANGED_FILES; do
  # Get symbols defined in this file
  SYMBOLS=$(gitnexus list-symbols "$FILE" 2>/dev/null)
  for SYM in $SYMBOLS; do
    RISK=$(bin/gni impact "$SYM" --json | jq -r '.risk_level // "LOW"')
    if [[ "$RISK" == "HIGH" || "$RISK" == "CRITICAL" ]]; then
      echo "⚠️  HIGH RISK: $SYM in $FILE"
      HIGH_RISK_COUNT=$((HIGH_RISK_COUNT + 1))
    fi
  done
done

if [ $HIGH_RISK_COUNT -gt 0 ]; then
  echo "Found $HIGH_RISK_COUNT high-risk changes. Review impact analysis above."
  exit 1
fi
echo "✅ No high-risk changes detected"
exit 0
```

---

## Post-merge Reindex

### Git hooks (local)

Install post-commit/post-merge hooks to keep the local graph current:

```bash
# Install hooks for a specific repository
make install-hooks REPO=~/dev/my-repo

# Verify hooks are installed
ls -la ~/dev/my-repo/.git/hooks/post-commit ~/dev/my-repo/.git/hooks/post-merge
```

The hooks call `gitnexus-auto-reindex.sh` in the background (non-blocking):

```bash
# .git/hooks/post-commit (installed by make install-hooks)
#!/bin/bash
GITNEXUS_AUTO_REINDEX=${GITNEXUS_AUTO_REINDEX:-1}
[ "$GITNEXUS_AUTO_REINDEX" = "0" ] && exit 0

REPO_PATH=$(git rev-parse --show-toplevel)
nohup /path/to/gitnexus-stable-ops/bin/gitnexus-auto-reindex.sh \
  >> ~/.gitnexus/hook.log 2>&1 &
exit 0
```

---

## Smoke Test on Deploy

Run a full end-to-end smoke test after deployment to verify the graph is healthy:

```bash
# Deploy pipeline step
./bin/gitnexus-smoke-test.sh ~/production/repo repo-name AuthService

# Expected output (all steps pass):
# ✅ analyze (force)
# ✅ status
# ✅ list
# ✅ context
# ✅ cypher
# ✅ impact
```

In CI:

```yaml
- name: GitNexus smoke test
  run: |
    /opt/stable-ops/bin/gitnexus-smoke-test.sh \
      $GITHUB_WORKSPACE \
      ${{ github.event.repository.name }} \
      ${{ inputs.test_symbol || 'main' }}
  continue-on-error: true  # Non-blocking smoke test
```

---

## Caching Strategies

### GitHub Actions cache key strategy

```yaml
# Hierarchical cache: prefer most specific, fall back to broader
- uses: actions/cache@v4
  with:
    path: ~/.gitnexus
    key: gitnexus-${{ runner.os }}-${{ github.repository }}-${{ github.sha }}
    restore-keys: |
      gitnexus-${{ runner.os }}-${{ github.repository }}-${{ github.ref_name }}-
      gitnexus-${{ runner.os }}-${{ github.repository }}-main-
      gitnexus-${{ runner.os }}-${{ github.repository }}-
```

This allows incremental reindexing on PRs (restored from the base branch cache) while the post-merge workflow saves the updated graph for future PRs.

### Artifact preservation

For teams needing to share the graph across multiple CI workers:

```yaml
# Worker 1: Reindex
- name: Save graph artifact
  uses: actions/upload-artifact@v4
  with:
    name: gitnexus-graph-${{ github.sha }}
    path: ~/.gitnexus/
    retention-days: 7

# Worker 2: Query (reads artifact instead of reindexing)
- name: Restore graph artifact
  uses: actions/download-artifact@v4
  with:
    name: gitnexus-graph-${{ github.sha }}
    path: ~/.gitnexus/
```

---

## Docker-based Pipelines

For teams using Docker runners or self-hosted agents:

```dockerfile
# Dockerfile.gitnexus-ci
FROM node:22-slim

RUN apt-get update && apt-get install -y git jq python3 curl && rm -rf /var/lib/apt/lists/*

# Pin GitNexus version
RUN npm install -g gitnexus@1.4.6

# Install stable-ops
RUN git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops /opt/stable-ops \
    && cd /opt/stable-ops && make install

ENV GITNEXUS_BIN=/root/.local/bin/gitnexus-stable
ENV PATH="/opt/stable-ops/bin:$PATH"

WORKDIR /workspace
```

Usage in GitHub Actions with Docker runner:

```yaml
jobs:
  reindex:
    runs-on: ubuntu-latest
    container:
      image: your-registry/gitnexus-ci:latest
    steps:
      - uses: actions/checkout@v4
      - name: Reindex
        run: gitnexus-auto-reindex.sh
        env:
          REPO_PATH: ${{ github.workspace }}
```

---

## Environment Variables Reference

| Variable | Default | CI Usage |
|----------|---------|---------|
| `GITNEXUS_BIN` | `~/.local/bin/gitnexus-stable` | Pin to specific binary |
| `ALLOW_DIRTY_REINDEX` | `0` | Set `1` only if checking out a dirty worktree |
| `FORCE_REINDEX` | `0` | Set `1` for weekly full reindex |
| `LOOKBACK_HOURS` | `24` | Increase for weekly batch |
| `NODE_OPTIONS` | _(unset)_ | Set `--max-old-space-size=8192` for large repos |
| `GITNEXUS_AUTO_REINDEX` | `1` | Set `0` to disable git hooks temporarily |

---

## Troubleshooting

### Graph is stale after CI run

Verify the cache key is correct and the post-merge reindex ran successfully:

```bash
# Check last index time
cat ~/.gitnexus/meta.json | jq '.lastCommit, .indexedAt'

# Force reindex
FORCE_REINDEX=1 bin/gitnexus-auto-reindex.sh
```

### Embeddings missing in CI

CI environments may not have enough memory for embedding generation. Use `--embeddings` only in scheduled (weekly) reindex jobs, not in every PR check:

```yaml
# PR checks: no embeddings (faster)
- run: REPO_PATH=$GITHUB_WORKSPACE bin/gitnexus-auto-reindex.sh

# Weekly: with embeddings
- run: FORCE_REINDEX=1 REPO_PATH=$GITHUB_WORKSPACE bin/gitnexus-auto-reindex.sh --embeddings
```

### `impact` command crashes in CI

This is the arm64 macOS concurrency issue documented in [Edge Cases](../README.md#edge-cases--lessons-learned). Use `gitnexus-safe-impact.sh` instead of calling `gitnexus impact` directly — it automatically falls back to context-based analysis:

```bash
# ❌ May crash in concurrent CI
gitnexus impact AuthService

# ✅ Safe for CI (never crashes, always returns valid JSON)
bin/gitnexus-safe-impact.sh AuthService
# OR use the gni wrapper:
bin/gni impact AuthService
```

---

*See [Enterprise FAQ](enterprise-faq.md) for Docker/K8s deployment and SLA information.*
