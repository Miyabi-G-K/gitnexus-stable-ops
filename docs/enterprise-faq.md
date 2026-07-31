# Enterprise FAQ — gitnexus-stable-ops

Frequently asked questions from enterprise evaluators and engineering teams.

---

## Table of Contents

1. [Deployment & Infrastructure](#deployment--infrastructure)
2. [Scalability & Performance](#scalability--performance)
3. [CI/CD Integration](#cicd-integration)
4. [AI Agent Orchestration](#ai-agent-orchestration)
5. [Edge Cases & Production Hardening](#edge-cases--production-hardening)
6. [Security & Compliance](#security--compliance)
7. [Support & SLA](#support--sla)

---

## Deployment & Infrastructure

**Q: What is the minimum viable deployment for a team of 5 engineers?**

A: Single Docker container with a mounted volume for `~/.gitnexus`:

```yaml
services:
  gitnexus:
    image: node:22-slim
    command: >
      bash -c "npm install -g gitnexus@1.4.6 &&
               git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops /opt/stable-ops &&
               cd /opt/stable-ops && make install && cron -f"
    volumes:
      - ./repos:/repos:ro
      - gitnexus-data:/root/.gitnexus
    restart: unless-stopped
volumes:
  gitnexus-data:
```

For a team, mount repositories as read-only (`/repos:ro`) and share the `gitnexus-data` volume. Reindexing can run on a dedicated service separate from query serving.

---

**Q: How do we run this on Kubernetes?**

A: Kubernetes support is in the v1.4 roadmap. Currently the recommended K8s approach is:

1. Run a dedicated pod for indexing (CronJob, runs daily)
2. Mount a shared PVC for `~/.gitnexus` (ReadWriteMany)
3. Query-serving agents mount the same PVC read-only

```yaml
# CronJob for nightly reindex
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gitnexus-reindex
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: reindex
            image: your-registry/gitnexus-stable-ops:latest
            command: ["bin/gitnexus-reindex.sh"]
            env:
            - name: REPOS_DIR
              value: /repos
            volumeMounts:
            - name: gitnexus-data
              mountPath: /root/.gitnexus
          volumes:
          - name: gitnexus-data
            persistentVolumeClaim:
              claimName: gitnexus-data-pvc
```

Native K8s operator planned for v2.0 (Q4 2026).

---

**Q: Does the toolkit support air-gapped / offline deployments?**

A: Yes. Requirements are:

- GitNexus binary pinned locally (`~/.local/bin/gitnexus-stable`) — no internet required at runtime
- KuzuDB graph database is fully local (`~/.gitnexus/`)
- No external API calls during analysis or query
- `GITNEXUS_BIN` can point to a private registry download or manually installed binary

For air-gapped environments, pre-install the GitNexus binary and toolkit on an internal image registry.

---

**Q: How much disk space does the graph database consume?**

A: Based on our 25+ repository production deployment:

| Repository Size | Symbols | Edges | KuzuDB Size |
|----------------|---------|-------|-------------|
| Small (<10K files) | ~1,200 | ~3,000 | ~80 MB |
| Medium (10K-50K files) | ~5,000 | ~12,000 | ~350 MB |
| Large (50K-100K files) | ~15,000 | ~35,000 | ~1.2 GB |
| Our 25-repo aggregate | 32,000+ | 73,000+ | ~4 GB |

Embeddings add approximately 1.5× to the base graph size.

---

## Scalability & Performance

**Q: How does reindexing time scale with repository size?**

A: Empirically measured on our production repositories:

| Repo Size | First Analyze | Incremental | With Embeddings |
|-----------|--------------|-------------|-----------------|
| ~1K files | 30s | 5s | +60s |
| ~10K files | 4m | 30s | +8m |
| ~50K files | 18m | 2m | +35m |
| ~100K files | 45m | 5m | +90m |

For repos with 100K+ files, set `NODE_OPTIONS="--max-old-space-size=8192"`. Incremental reindexing (via `gitnexus-auto-reindex.sh`) only processes changed files since last commit — dramatically faster than full reindex.

---

**Q: Can multiple agents query the graph concurrently?**

A: Read queries are safe to parallelize. The known limitation is **concurrent `impact` queries on arm64 macOS**, where KuzuDB connections are not thread-safe and SIGSEGV can occur. Our `gitnexus-safe-impact.sh` wraps all impact queries with:

1. Retry with exponential backoff (3 attempts)
2. Graceful fallback to `context`-based analysis if `impact` crashes
3. Structured JSON output in both cases — callers receive consistent data

This issue was reported upstream as [PR #425](https://github.com/abhigyanpatwari/GitNexus/pull/425).

On Linux (Docker, cloud), concurrent queries work without issue.

---

**Q: What is the query latency for `context` and `impact` operations?**

A: From our production measurements (40 agents, 32K+ symbols):

| Operation | P50 | P95 | P99 |
|-----------|-----|-----|-----|
| `context` | 120ms | 380ms | 850ms |
| `impact` (shallow, d=1) | 200ms | 600ms | 1.4s |
| `impact` (deep, d=3) | 450ms | 1.2s | 3.1s |
| `cypher` (simple) | 80ms | 250ms | 600ms |
| `cypher` (complex) | 350ms | 900ms | 2.5s |

Latency increases proportionally with graph size. For teams with 50+ repositories, consider partitioning the graph by domain (see Architecture doc).

---

## CI/CD Integration

**Q: How do we integrate this into our GitHub Actions pipeline?**

A: Add a reindex step post-merge. A GitHub Actions composite action is in the v1.4 roadmap; until then:

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
    - name: Install GitNexus
      run: npm install -g gitnexus@1.4.6

    - name: Install gitnexus-stable-ops
      run: |
        git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops /opt/stable-ops
        cd /opt/stable-ops && make install

    - name: Smart reindex
      run: REPO_PATH=$GITHUB_WORKSPACE bin/gitnexus-auto-reindex.sh
      working-directory: /opt/stable-ops

    - name: Upload graph artifact
      uses: actions/upload-artifact@v4
      with:
        name: gitnexus-graph-${{ github.sha }}
        path: ~/.gitnexus/
        retention-days: 7
```

---

**Q: Can we use this for pre-merge impact analysis in PRs?**

A: Yes. This is one of the highest-value use cases. Add a PR check that runs `gni impact` on all changed symbols and posts the blast radius as a PR comment:

```yaml
- name: Impact Analysis
  run: |
    CHANGED=$(git diff --name-only origin/main...HEAD)
    for SYMBOL in $(extract-symbols $CHANGED); do
      bin/gni impact "$SYMBOL" --direction upstream --json >> /tmp/impact.json
    done
    gh pr comment ${{ github.event.pull_request.number }} \
      --body "$(cat /tmp/impact.json | format-impact-comment)"
```

The `gni` wrapper in this toolkit always returns valid JSON (never crashes), making it suitable for CI pipelines. The `gitnexus-safe-impact.sh` fallback ensures the check never blocks a pipeline due to a KuzuDB crash.

---

**Q: What happens if the graph index becomes stale during a long CI run?**

A: `gitnexus-auto-reindex.sh` compares `meta.json.lastCommit` against `HEAD`. If the graph is current, it skips reindexing with exit code 0. This idempotency makes it safe to call on every CI run — the tool self-detects whether a reindex is needed.

The stale detection checks:
1. `meta.json.lastCommit == git rev-parse HEAD`
2. File modification times of tracked source files vs. last index timestamp

If either check fails, a full reindex runs automatically.

---

## AI Agent Orchestration

**Q: How do your 40 agents coordinate access to the knowledge graph?**

A: Our OpenClaw MAS (Multi-Agent System) uses a **read-many, write-one** model:

```
           ┌─────────────────────────┐
           │   All 40 Agents         │
           │   (read-only queries)   │
           └──────────┬──────────────┘
                      │ Concurrent reads
                      ▼
           ┌─────────────────────────┐
           │   KuzuDB Graph          │
           │   (.gitnexus/)          │
           └──────────┬──────────────┘
                      │ Single writer
                      ▼
           ┌─────────────────────────┐
           │  Auto-Reindex Service   │
           │  (post-commit hook)     │
           │  gitnexus-auto-reindex  │
           └─────────────────────────┘
```

Agents never write to the graph — only the `gitnexus-auto-reindex.sh` service does, triggered by post-commit/post-merge git hooks. This prevents write contention entirely.

---

**Q: How do agents know when the graph is stale and needs a refresh?**

A: Each agent that detects a stale graph can trigger reindexing via the git hook mechanism:

```bash
# Any agent can check staleness
gni status $REPO_PATH | jq '.stale'

# If stale, trigger reindex (non-blocking)
REPO_PATH=$TARGET_REPO bin/gitnexus-auto-reindex.sh &
```

In our production setup, `dev-architect` and `guardian` agents check graph freshness before any impact analysis call, and trigger `gitnexus-auto-reindex.sh` if the graph is more than 1 commit behind HEAD.

---

**Q: Can the toolkit work with agents using different LLM providers (OpenAI, Gemini, etc.)?**

A: The toolkit is provider-agnostic. All GitNexus data is exposed via:

1. **CLI** — shell commands any agent can invoke
2. **MCP server** — `lib/mcp_server.py` speaks the Model Context Protocol, compatible with any MCP client (Claude, OpenAI Assistants with tools, Gemini with function calling)
3. **JSON output** — every `gni` command can output `--json` for programmatic consumption

Our 40 agents run on Claude (Anthropic), Gemini, and local models interchangeably, all reading from the same GitNexus graph.

---

## Edge Cases & Production Hardening

**Q: What happens if `gitnexus analyze` crashes halfway through?**

A: GitNexus writes to a temp directory and atomically moves the result to the final location. A crashed analyze does not corrupt the existing graph — the previous index remains intact. `gitnexus-auto-reindex.sh` detects incomplete indexes by comparing the `meta.json.lastCommit` field against the current HEAD and will retry.

---

**Q: We had a situation where embeddings disappeared after a team member ran `gitnexus analyze --force`. How do we prevent this?**

A: This is the most critical production failure mode we document. The fix is already in `gitnexus-auto-reindex.sh`:

```bash
# Auto-detect existing embeddings
HAS_EMBEDDINGS=$(jq -r '.stats.embeddings // 0' ~/.gitnexus/meta.json)
if [ "$HAS_EMBEDDINGS" -gt 0 ]; then
    ANALYZE_FLAGS="$ANALYZE_FLAGS --embeddings"
fi
```

To retroactively protect your team:
1. Use `bin/gitnexus-auto-reindex.sh` instead of calling `gitnexus analyze` directly
2. Add a git hook: `make install-hooks REPO=~/dev/your-repo`
3. Add a CI check: run `bin/gitnexus-doctor.sh` after every analyze to verify embedding count is non-zero

We have had **zero embedding loss incidents** since deploying this protection in v1.0.

---

**Q: How do you handle monorepos with 100K+ files?**

A: Set `NODE_OPTIONS="--max-old-space-size=8192"` in your shell or Docker environment. The scripts inherit this variable automatically. For extremely large repos:

1. Consider analyzing sub-directories as separate "repos" (`gitnexus analyze --path ./packages/core`)
2. Use the `LOOKBACK_HOURS` variable to limit batch reindex scope
3. Schedule weekly full reindex; incremental auto-reindex handles daily changes efficiently

---

**Q: We use monorepo tooling (Nx, Turborepo, Bazel). Does this work?**

A: Yes. GitNexus analyzes the underlying TypeScript/JavaScript/Python/Rust source regardless of build tooling. The `bin/` scripts use standard git operations to detect changes, which work correctly with all monorepo layouts.

Known limitation: `detect_changes` works at the file level. Package-level dependency graphs from Nx/Turborepo/Bazel are not currently cross-referenced. Upstream PR [#454](https://github.com/abhigyanpatwari/GitNexus/pull/454) adds change-type classification which partially addresses this.

---

## Security & Compliance

**Q: Does the toolkit send any data to external services?**

A: No. All analysis is local:

- GitNexus runs entirely locally (KuzuDB is embedded, no server)
- No telemetry, no external API calls during analysis or query
- The `gni` CLI only communicates with the local GitNexus process
- Embeddings (if enabled) are generated and stored locally

The only network access in this toolkit is:
1. `git clone` during installation
2. `npm install -g gitnexus` during installation

Neither occurs at runtime.

---

**Q: Our security team requires all tools to have SBOM. Is one available?**

A: Not yet. We plan to generate SBOM artifacts as part of the v1.3 Docker image release (Q2 2026). For current deployments, the dependency tree is minimal:

- Runtime: `gitnexus` (npm package, PolyForm NonCommercial licensed), `bash`, `jq`, `git`, `python3`
- No additional npm packages are installed by this toolkit

---

**Q: What is the license situation for commercial use?**

A: This toolkit (`gitnexus-stable-ops`) is MIT licensed and can be used commercially without restriction. However, **GitNexus itself** is licensed under [PolyForm NonCommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/), which **prohibits commercial use** without a separate commercial license from the GitNexus maintainers.

For commercial deployments, contact:
- GitNexus author: [@abhigyanpatwari](https://github.com/abhigyanpatwari) for a GitNexus commercial license
- Miyabi G.K.: [shunsuke.hayashi@miyabi-ai.jp](mailto:shunsuke.hayashi@miyabi-ai.jp) for deployment assistance and integration consulting

---

## Support & SLA

**Q: What support options are available?**

Miyabi G.K. offers:

| Tier | Response | Includes |
|------|----------|---------|
| **Community** | Best-effort | GitHub Issues, public discussions |
| **Professional** | 48h business hours | Deployment review, integration guidance, email |
| **Enterprise** | 8h business hours | Custom SLA, dedicated Slack, architecture review, CI/CD integration |

Contact: [shunsuke.hayashi@miyabi-ai.jp](mailto:shunsuke.hayashi@miyabi-ai.jp) / [@The_AGI_WAY](https://x.com/The_AGI_WAY)

---

**Q: How stable is the toolkit? What is the production track record?**

A: As of March 2026:

| Metric | Value |
|--------|-------|
| Production deployment | 3+ months continuous |
| Repositories indexed | 25+ |
| Embedding loss incidents | **0** since v1.0 |
| Breaking changes | 0 (v1.x is stable) |
| Upstream PRs merged | 7 of 13 submitted |
| Automated test coverage | All scripts covered by `make test` |

We maintain a **no-breaking-changes policy** for v1.x. Any behavior change that could affect existing deployments will be versioned as v2.0 with a migration guide.

---

**Q: Is there a changelog or migration guide?**

A: See [CHANGELOG.md](../CHANGELOG.md) for release history and [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.

---

*For questions not covered here, open a [GitHub Issue](https://github.com/ShunsukeHayashi/gitnexus-stable-ops/issues) or contact [shunsuke.hayashi@miyabi-ai.jp](mailto:shunsuke.hayashi@miyabi-ai.jp).*
