# gitnexus-stable-ops

**Give AI Agents a 360° View of Your Codebase.**

Stop Copilot and Claude Code from breaking callers they don't know about.
`gitnexus-stable-ops` is a production ops toolkit that keeps [GitNexus](https://github.com/abhigyanpatwari/GitNexus) running reliably across 25+ repositories — zero embedding loss, zero version drift, zero dirty-graph surprises.

[![CI](https://github.com/ShunsukeHayashi/gitnexus-stable-ops/actions/workflows/ci.yml/badge.svg)](https://github.com/ShunsukeHayashi/gitnexus-stable-ops/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/ShunsukeHayashi/gitnexus-stable-ops?style=social)](https://github.com/ShunsukeHayashi/gitnexus-stable-ops)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Featured in GitNexus](https://img.shields.io/badge/GitNexus-Community%20Integration-blue?logo=github)](https://github.com/abhigyanpatwari/GitNexus#community-integrations)

> *"designed for autonomous agent swarms"*
> — [@d3thshot7777](https://github.com/abhigyanpatwari/GitNexus), GitNexus maintainer

**Powering 39+ OpenClaw Agents · 14 upstream PRs → 7 merged · 3+ months production**

[English](./README.md) | [中文](./README_zh.md) | [日本語](./README_ja.md)

---

## Quick Start

```bash
git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops.git
cd gitnexus-stable-ops && make install

# Diagnose a repo
bin/gitnexus-doctor.sh ~/dev/my-repo my-repo MyClassName

# Smart reindex (skips if up-to-date, protects embeddings)
REPO_PATH=~/dev/my-repo bin/gitnexus-auto-reindex.sh

# See what breaks if you change a class
gni impact AuthService
```

```
✅ Direct callers (d=1):  UserController.login, SessionManager.refresh
⚠️  Transitive deps (d=2): 14 files affected
🔴 Risk: HIGH — update callers before merging
```

---

## Why This Exists

GitNexus is one of the most capable open-source code intelligence engines available today. But running it in **production** — across dozens of repositories, with automated reindexing, inside AI agent workflows — exposes four critical operational problems:

| Problem | Impact | This toolkit's fix |
|---------|--------|--------------------|
| **Version drift** | CLI and MCP reference different versions, causing data corruption | Pinned binary (`$GITNEXUS_BIN`) used by all scripts |
| **Embedding loss** | `analyze --force` silently deletes embeddings | Auto-detect existing embeddings, add `--embeddings` flag automatically |
| **Dirty worktree** | Reindexing uncommitted work pollutes the code graph | Skip dirty repos by default (`ALLOW_DIRTY_REINDEX=0`) |
| **Impact instability** | `impact` crashes on arm64 macOS with concurrent queries | Graceful fallback to context-based analysis |

**We discovered and solved these problems running GitNexus on 25+ repos for 3+ months.**

---

## Production Stats

| Metric | Value |
|--------|-------|
| Repositories indexed | **25+** |
| Symbols in knowledge graph | **32,000+** |
| Edges (relationships) | **73,000+** |
| AI agents using the graph | **40** (OpenClaw MAS) |
| Embedding loss incidents | **0** since v1.0 |
| Upstream PRs merged to GitNexus | **7 of 14** submitted |
| Production uptime | **3+ months** |

---

## How AI Agents Use This

```
Agent receives task: "Fix auth bug in service-api"
    |
    +-- 1. gni impact AuthService   --> What breaks if we change it?
    +-- 2. gni context AuthService  --> Get callers, callees, dependencies
    +-- 3. Agent writes code fix
    +-- 4. auto-reindex.sh          --> Graph stays current (post-commit hook)
```

**Key insight**: When AI agents share a code knowledge graph, they avoid breaking callers they don't know about. `gni impact` is the difference between a safe refactor and a 2 AM incident.

```yaml
# Example: OpenClaw 39-agent system
steps:
  - agent: dev-architect
    action: gni impact TargetClass --direction upstream
    purpose: Blast radius before code change

  - agent: dev-coder
    action: gni context TargetClass
    purpose: Understand dependencies before writing fix

  - trigger: post-commit hook
    action: gitnexus-auto-reindex.sh
    purpose: Graph stays current for the next agent
```

---

## Features

| Script | Purpose |
|--------|---------|
| `bin/gni` | Production CLI wrapper — readable output, cypher stderr capture, impact fallback |
| `bin/gitnexus-doctor.sh` | Diagnose version drift, index health, MCP config, embedding status |
| `bin/gitnexus-smoke-test.sh` | End-to-end health check (analyze → status → list → context → cypher → impact) |
| `bin/gitnexus-safe-impact.sh` | Impact analysis with automatic context-based fallback on failure |
| `bin/gitnexus-auto-reindex.sh` | Smart single-repo reindex (stale detection + embedding protection + dirty skip) |
| `bin/gitnexus-reindex.sh` | Batch reindex recently changed repos (cron-friendly) |
| `bin/gitnexus-reindex-all.sh` | Reindex all registered repos with safety defaults |
| `bin/gitnexus-install-hooks.sh` | Install git hooks for auto-reindex on commit/merge |

---

## Safety Defaults

| Feature | Default | Override |
|---------|---------|----------|
| Embedding protection | Auto-detect and preserve | Always on |
| Dirty worktree skip | Skip dirty repos | `ALLOW_DIRTY_REINDEX=1` |
| Impact fallback | Context-based JSON on failure | Always on |
| Version pinning | `$GITNEXUS_BIN` | Set env var |

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `GITNEXUS_BIN` | `~/.local/bin/gitnexus-stable` | Pinned GitNexus CLI path |
| `REGISTRY_PATH` | `~/.gitnexus/registry.json` | Indexed repo registry |
| `ALLOW_DIRTY_REINDEX` | `0` | Allow reindexing dirty worktrees |
| `REPOS_DIR` | `~/dev` | Root directory for batch reindex |
| `LOOKBACK_HOURS` | `24` | How far back to check for changes |

---

## Edge Cases & Lessons Learned

After 3 months of production use:

| Edge case | Status | Notes |
|-----------|--------|-------|
| LadybugDB concurrent query lock errors | ✅ Fixed upstream [PR #425](https://github.com/abhigyanpatwari/GitNexus/pull/425) + local fallback | Use `gitnexus-safe-impact.sh` for older versions |
| Embedding silent deletion on `--force` | ✅ Zero incidents since v1.0 | Auto-detects `meta.json`, adds `--embeddings` |
| Version drift between CLI and MCP | ✅ Pinned binary | All scripts use `$GITNEXUS_BIN` |
| Dirty worktree graph pollution | ✅ Skipped by default | Override: `ALLOW_DIRTY_REINDEX=1` |
| Large monorepo heap exhaustion | ✅ Detected and logged clearly | Set `NODE_OPTIONS=--max-old-space-size=8192` |

---

<details>
<summary>&#9654; Agent Context Graph (v1.3.0) — Index agents, skills, and cluster topology</summary>

Beyond code symbols, gitnexus-stable-ops indexes **agent-level entities** from your workspace — giving LLMs a live map of *who can do what and where*.

### What it indexes

| Entity | Source | Description |
|--------|--------|-------------|
| `Agent` | `KNOWLEDGE/AGENTS_*.md` frontmatter | Named agents with roles, pane IDs, society membership |
| `Skill` | `SKILL/**/*.md` | Skills with priority, keywords, script paths |
| `KnowledgeDoc` | `KNOWLEDGE/**/*.md` | Reference docs and context files |
| `MemoryDoc` | `MEMORY/**/*.md` | Session memories and daily logs |
| `ComputeNode` | `workspace.json nodes[]` | Physical/virtual machines in your cluster |
| `WorkspaceService` | `workspace.json services[]` | Deployed agents/services with model info |

### Progressive Disclosure

| Level | Tokens | Use case |
|-------|--------|----------|
| `--level 1` | ~100 | LLM system prompt overview |
| `--level 2` | ~400 | Default context injection |
| `--level 3` | ~2000 | Deep dive with full edges |

```bash
# Build the agent graph
gni agent-index ~/dev/MY_WORKSPACE --force

# Query at different detail levels
gni aq "deploy agent"   --level 1
gni aq "cc-hayashi"     --level 2
gni aq "announce skill" --level 3

# Auto-generate CLAUDE.md / AGENTS.md
gni cg . --update
```

For the full guide, see [docs/agent-context-graph.md](./docs/agent-context-graph.md).

</details>

---

<details>
<summary>&#9654; Production Deployment — Docker and cron setup</summary>

### Docker

```dockerfile
FROM node:22-slim
RUN npm install -g gitnexus@1.4.6
RUN git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops.git /opt/stable-ops \
    && cd /opt/stable-ops && make install
RUN ln -sf $(which gitnexus) /usr/local/bin/gitnexus-stable
ENV GITNEXUS_BIN=/usr/local/bin/gitnexus-stable
ENV REPOS_DIR=/repos
COPY crontab /etc/cron.d/gitnexus
CMD ["cron", "-f"]
```

### Cron schedule

```cron
# Smart reindex: only repos changed in last 24h
0 3 * * *  REPOS_DIR=/repos bin/gitnexus-reindex.sh >> /var/log/gitnexus-reindex.log
# Weekly full reindex (Sunday 4 AM)
0 4 * * 0  bin/gitnexus-reindex-all.sh >> /var/log/gitnexus-full-reindex.log
# Health check (daily)
30 9 * * * bin/gitnexus-doctor.sh /repos/main-app main-app >> /var/log/gitnexus-doctor.log
```

For the full CI/CD guide, see [docs/ci-cd-integration.md](./docs/ci-cd-integration.md).

</details>

---

## Upstream Contributions

| PR | Title | Status |
|----|-------|--------|
| [#441](https://github.com/abhigyanpatwari/GitNexus/pull/441) | Add `confidence` constant for similarity threshold | ✅ Merged |
| [#451](https://github.com/abhigyanpatwari/GitNexus/pull/451) | Persist chat history across sessions | ✅ Merged |
| [#453](https://github.com/abhigyanpatwari/GitNexus/pull/453) | Add structured debug logger | ✅ Merged |
| [#454](https://github.com/abhigyanpatwari/GitNexus/pull/454) | `detect_changes` — classify by change type | ✅ Merged |
| [#425](https://github.com/abhigyanpatwari/GitNexus/pull/425) | Fix LadybugDB concurrent lock errors with exponential backoff | ✅ Merged |
| [#455](https://github.com/abhigyanpatwari/GitNexus/pull/455) | Align `QueryResult` types with LadybugDB WASM API | 🔄 Review |
| [#458](https://github.com/abhigyanpatwari/GitNexus/pull/458) | Expose per-repo resources in `resources/list` (fix MCP discovery) | 🔄 Review |
| [#443](https://github.com/abhigyanpatwari/GitNexus/pull/443) | Add `maxIterations` to prevent runaway agent loops | 🔄 Review |
| _(+6 more)_ | Error handling, performance, CI stability | 🔄 Review |

---

## Compatibility

| Platform | Status |
|----------|--------|
| macOS (Apple Silicon) | ✅ Primary development platform |
| Linux (Ubuntu, Debian, Fedora) | ✅ Tested |
| Docker | ✅ See deployment section above |
| Windows | ⚠️ Use WSL or Git Bash |

Requires: Bash 4.0+ · Git 2.0+ · jq 1.6+ · Python 3.6+ · Node.js 20+

---

## Documentation

- [Agent Context Graph Guide](docs/agent-context-graph_en.md) — Setup, commands, LLM injection, FAQ
- [Runbook](docs/runbook.md) — Step-by-step operational procedures
- [Architecture](docs/architecture.md) — Design principles and data flow
- [MCP Integration](docs/mcp-integration.md) — MCP server configuration
- [CI/CD Integration](docs/ci-cd-integration.md) — GitHub Actions, GitLab, impact analysis in PRs
- [Enterprise FAQ](docs/enterprise-faq.md) — Docker, K8s, security, SLA

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

All contributions must include tests, follow [Conventional Commits](https://www.conventionalcommits.org/), and pass `make test`.

---

## Enterprise

Running GitNexus at scale in a regulated environment? Miyabi G.K. offers architecture review, custom CI/CD integration, and priority issue resolution.

📧 [shunsuke.hayashi@miyabi-ai.jp](mailto:shunsuke.hayashi@miyabi-ai.jp)
🐦 [@The_AGI_WAY](https://x.com/The_AGI_WAY)

---

## License

**This toolkit: MIT** — covers wrapper scripts, tooling, and documentation only.

[GitNexus](https://github.com/abhigyanpatwari/GitNexus) itself is licensed under [PolyForm NonCommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/). This toolkit calls the GitNexus CLI but does not include or redistribute any GitNexus source code. For commercial use, verify GitNexus licensing independently.

---

**Built by [Miyabi G.K.](https://miyabi-ai.jp)**

🐦 [@The_AGI_WAY](https://x.com/The_AGI_WAY) · 📧 shunsuke.hayashi@miyabi-ai.jp

<sub>Active contributor to [GitNexus](https://github.com/abhigyanpatwari/GitNexus) — 14 PRs submitted, 7 merged.</sub>
