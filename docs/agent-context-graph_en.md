# Agent Context Graph

> **Language**: [English](./agent-context-graph_en.md) | [日本語](./agent-context-graph.md)

**Added in gitnexus-stable-ops v1.6.0.** A knowledge graph of agents, skills, nodes, and services — completely independent from the code symbol graph (GitNexus core graph).

## Overview

```
                  ┌──────────────────────┐
  Code Graph      │ ~/.gitnexus/         │  ← GitNexus core graph
  (32K+ symbols)  │  KuzuDB / LadybugDB  │    gni query/context/impact
                  └──────────────────────┘

                  ┌──────────────────────┐
  Agent Graph     │ .gitnexus/           │  ← Agent Context Graph
  (270+ nodes)    │  agent-graph.db      │    gni ai/as/aq/cg
                  └──────────────────────┘
```

**The two graphs operate independently.** You can use the code graph and agent graph simultaneously.

---

## 5-Minute Quickstart

How to set up the Agent Context Graph in a new workspace.

### Step 1: Create workspace.json (1 min)

```bash
mkdir -p ~/dev/MY_WORKSPACE/.gitnexus
cat > ~/dev/MY_WORKSPACE/.gitnexus/workspace.json << 'EOF'
{
  "version": "1.1",
  "workspace_root": "MY_WORKSPACE",
  "description": "My multi-agent workspace",
  "nodes": [
    {
      "id": "local",
      "name": "Local Machine",
      "role": "primary",
      "os": "macos",
      "description": "Development machine",
      "access": {"type": "local"},
      "workspace_root": "/Users/me/dev/MY_WORKSPACE",
      "services": ["my-agent"]
    }
  ],
  "services": [
    {
      "id": "my-agent",
      "name": "My Agent",
      "type": "agent",
      "node": "local",
      "description": "Main development agent",
      "skill_refs": ["SKILL/"],
      "labels": {"model": "claude-sonnet-4-6"}
    }
  ],
  "knowledge_refs": {
    "skills_dir": "SKILL",
    "memory_dir": "MEMORY",
    "knowledge_dir": "KNOWLEDGE"
  }
}
EOF
```

### Step 2: Create a SKILL/ directory (1 min)

```bash
mkdir -p ~/dev/MY_WORKSPACE/SKILL/infra
cat > ~/dev/MY_WORKSPACE/SKILL/infra/deploy.md << 'EOF'
# Deploy Skill

**Version**: 1.0.0
**Triggers**: deploy, release, publish, ship

## Overview
Handles deployment to production environments.

## Usage
1. Confirm all tests pass
2. Run `npm run build`
3. Trigger deploy with `git push origin main`
EOF
```

### Step 3: Build the graph (1 min)

```bash
cd ~/dev/MY_WORKSPACE
gni agent-index . --force

# Example output:
# ==================================================
# Agent Graph Build Complete
# ==================================================
#   Agents:           1
#   Skills:           1
#   Compute Nodes:    1
#   WS Services:      1
#   Total Nodes:      4
#   Edges:            1
#   Time:             12ms
```

### Step 4: Verify it works (1 min)

```bash
# Check stats
gni agent-status
# → Agents: 1, Skills: 1, Total Nodes: 4

# Run a query
gni aq "deploy"
# → ## Agent Context [Standard] query:'deploy'
#   ### Skills
#   - **deploy** — Handles deployment to production environments.
```

### Step 5: Inject into Claude Code (1 min)

```bash
# Auto-inject a section into CLAUDE.md
gni context-gen . --target claude --update

# Or manually get context for use in a system prompt
gni aq "deploy" --level 1  # ~100 tokens compact summary
```

---

## Setup for Existing Workspaces

```bash
# 1. Build the agent graph (first time only)
gni agent-index ~/dev/MY_WORKSPACE --force

# 2. Check stats
gni agent-status

# 3. Run queries
gni aq "deploy"

# 4. Generate CLAUDE.md / AGENTS.md
gni context-gen . --target agents
gni context-gen . --target claude --update
```

---

## Command Reference

### `gni agent-index` (alias: `ai`)

Builds or updates the Agent Context Graph.

```bash
gni ai [repo-path] [--force] [--dry-run] [--json]
```

| Option | Description |
|--------|-------------|
| `--force` | Full rebuild (drops and recreates the existing DB) |
| `--dry-run` | Preview changes only (does not update DB) |
| `--json` | Output build results as JSON |

**What gets indexed**:

| Category | Source | DB Table |
|----------|--------|----------|
| Agents | `AGENTS.md` / `docs/*.md` / `.claude/` | `agents` |
| Skills | `SKILL/**/*.md` / `.claude/skills/` | `skills` |
| Knowledge Docs | `KNOWLEDGE/**/*.md` / `docs/**/*.md` | `knowledge_docs` |
| Memory Docs | `MEMORY/**/*.md` / `.claude/projects/*/memory/` | `memory_docs` |
| Compute Nodes | `.gitnexus/workspace.json` → `nodes[]` | `compute_nodes` |
| Workspace Services | `.gitnexus/workspace.json` → `services[]` | `workspace_services` |

### `gni agent-status` (alias: `as`)

Displays graph statistics.

```bash
gni as [repo-path]
```

Example output:
```
Agent Context Graph: /path/to/.gitnexus/agent-graph.db
  Agents:             5
  Skills:            79
  Knowledge Docs:   108
  Memory Docs:        0
  Compute Nodes:      5
  Workspace Services: 4
  Edges:             26
  Build time:       47ms
```

### `gni agent-query` (alias: `aq`)

Searches agent context. Controls token budget via **Progressive Disclosure**.

```bash
gni aq "<query>" [--level 1|2|3] [--format progressive|json|markdown] [--repo path]
```

#### Progressive Disclosure Levels

| Level | Tokens | Content | Use Case |
|-------|--------|---------|----------|
| 1 | ~100 tokens | IDs and counts only | Quick overview at the start of a system prompt |
| 2 | ~400 tokens | Names, roles, attributes (default) | Standard prompt injection |
| 3 | ~2000 tokens | Full info + all edges | On-demand deep dive |

```bash
# Level 1 — "what's available" (system prompt header)
gni aq "announce" --level 1
# → skills: [announce, macbook-local-announce]
#   skill: 2 matched (~100 tokens)

# Level 2 — default (standard injection)
gni aq "deploy"
# → ## Agent Context [Standard] query:'deploy'
#   ### Skills
#   - **agent-skill-bus** — ...
#   (~400 tokens)

# Level 3 — full detail (on-demand)
gni aq "cc-hayashi" --level 3
# → Full detail with all edges (~2000 tokens)
```

#### Injecting into an LLM

```python
# Python example
import subprocess

def get_agent_context(query: str, level: int = 1) -> str:
    """Get context to inject into a Claude system prompt."""
    result = subprocess.check_output(
        ["gni", "aq", query, "--level", str(level), "--format", "progressive"],
        text=True
    )
    return result

query = "deploy"
level1 = get_agent_context(query, level=1)  # ~100 tokens

system_prompt = f"""
You are an AI assistant for this development workspace.

{level1}  # ← inject here (~100 tokens)

If you need more detail about a specific agent or skill,
ask the user to run: gni aq "<keyword>" --level 3
"""
```

### `gni context-gen` (alias: `cg`)

Auto-generates CLAUDE.md / AGENTS.md / skill index from the agent graph.

```bash
gni context-gen [repo-path] [options]
```

| Option | Description |
|--------|-------------|
| `--target claude\|agents\|skill\|all` | What to generate (default: all) |
| `--update` | Update sections in existing files |
| `--dry-run` | Print to stdout without writing files |
| `--json` | Output a JSON summary |
| `--out-dir <path>` | Output directory |

#### Workflow

```bash
# Initial setup
gni ai . --force          # 1. Build graph
gni cg . --dry-run        # 2. Preview output
gni cg . --target agents  # 3. Generate AGENTS.md (for Codex)
gni cg . --target claude --update  # 4. Inject section into CLAUDE.md

# Periodic refresh
gni ai . --force && gni cg . --target claude --update
```

#### Generated Files

**CLAUDE.md** — a section wrapped in `<!-- gitnexus:agent-context:start/end -->`:

```markdown
<!-- gitnexus:agent-context:start -->
## Agent Context (GitNexus)

### Cluster Topology
| Role | ID | OS | SSH | IP | Description |
...

### Available Skills
**business** (15): `asset-creation`, ...
...

### Querying the Agent Context Graph
gni aq "deploy"   # Standard (~400 tokens)
<!-- gitnexus:agent-context:end -->
```

**AGENTS.md** — full manifest for Codex and other AI agents:

```markdown
# AGENTS.md
## Summary
- Agents: 5, Skills: 79, ...

## Cluster Topology
...

## Agents
### Development Society (5)
#### 🍁 Kaede (`kaede`)
- Role: CodeGen / Developer
...

## Skills
### Business (15)
| Skill | Description |
...
```

**SKILL/_index_generated.md** — quick skill reference

---

## workspace.json v1.1 Schema

Full schema for `.gitnexus/workspace.json`.

### Top-Level Fields

```json
{
  "version": "1.1",              // Schema version (required)
  "workspace_root": "NAME",      // Workspace name (required)
  "description": "...",          // Optional

  "symlinks": [...],             // Symlink definitions (optional)
  "sub_repos": [...],            // Sub-repositories (optional)
  "nodes": [...],                // Compute nodes (required)
  "services": [...],             // Workspace services (required)
  "knowledge_refs": {...},       // Knowledge directory mappings (required)
  "cluster": {...},              // Cluster config (optional)
  "index_policy": {...}          // Index policy (optional)
}
```

### nodes[] — Compute Nodes

```json
{
  "id": "gateway",              // Unique ID (required)
  "name": "Windows Gateway",   // Display name (required)
  "role": "gateway|worker|primary",  // Node role (required)
  "os": "windows|macos|linux", // OS (required)
  "description": "...",        // Optional
  "access": {
    "type": "local|ssh",       // Access method (required)
    "host": "win-ts",          // SSH hostname (required for ssh)
    "user": "username"         // SSH user (optional)
  },
  "network": {
    "ip": "100.86.157.40",     // Tailscale/private IP (optional)
    "labels": {"vpn": "tailscale"}
  },
  "workspace_root": "/path/to/ws",  // Workspace path on this node (optional)
  "services": ["main", "x-ops"],    // Service IDs running on this node
  "labels": {
    "node_version": "v25.7.0",      // Arbitrary key-value labels
    "openclaw_version": "2026.3.11"
  }
}
```

**Role values**:

| Role | Description | Typical Node |
|------|-------------|--------------|
| `primary` | Main dev machine (local execution) | MacBook Pro |
| `gateway` | OpenClaw Gateway (agent orchestrator) | Windows PC |
| `worker` | Worker Node (distributed execution) | Mac mini |

### services[] — Workspace Services

```json
{
  "id": "cc-hayashi",           // Unique ID (required)
  "name": "Claude Code Hayashi",// Display name (required)
  "type": "agent|server|tool",  // Service type (required)
  "node": "macbook",            // Reference to nodes[].id (required)
  "description": "...",         // Optional
  "skill_refs": ["SKILL/"],     // SKILL paths to reference (optional)
  "memory_refs": ["MEMORY/"],   // MEMORY paths to reference (optional)
  "labels": {
    "model": "claude-sonnet-4-6",  // Arbitrary labels
    "heartbeat_interval": "4h"
  }
}
```

### knowledge_refs — Knowledge Directory Mappings

```json
{
  "skills_dir": "SKILL",        // Root dir for skill definitions (required)
  "memory_dir": "MEMORY",       // Memory / learning records dir
  "knowledge_dir": "KNOWLEDGE", // Knowledge base dir
  "scripts_dir": "scripts",     // Scripts dir
  "config_dir": "config"        // Config files dir
}
```

---

## Defining Agents and Skills

### SKILL/ Directory Structure

```
SKILL/
├── README.md               # Skill catalog overview
├── _index_generated.md     # GitNexus-generated index
│
├── personal/               # Personal skills
│   ├── task-tracker.md
│   └── schedule-manager.md
│
├── infra/                  # Infrastructure skills
│   ├── gitnexus.md
│   ├── claude-code-ops.md
│   └── agent-skill-bus.md
│
├── business/               # Business skills
├── content/                # Content skills
└── communication/          # Communication skills
```

### Writing Skill Definition Files

The Agent Context Graph extracts metadata from skill `.md` files:

```markdown
# Skill Name

**Version**: 1.0.0
**Created**: 2026-03-17
**Triggers**: deploy, release, publish, ship

## Overview

Describe this skill in 1-2 sentences. This text becomes the `description`
shown in `gni aq` Level 2 output.

## Usage
...
```

**Important fields**:

| Field | Role | Effect on Search |
|-------|------|-----------------|
| `# Title` | Skill name (`name`) | Affects BM25 score |
| `**Triggers**: ...` | Keywords (`keywords`) | Primary FTS5 search target |
| First sentence after `## Overview` | Description (`description`) | Shown in Level 2 output |
| File path | Category inference | Type weight calculation |

### Where Agent Definitions Come From

The Agent Context Graph auto-extracts agent info from:

- `AGENTS.md` — agent society definitions
- `.claude/CLAUDE.md` — when it contains agent info
- `docs/*.md` — documents with role definitions
- `.gitnexus/workspace.json` → `services[]` — agents defined as services

---

## Integration with Claude Code, Codex, and OpenClaw

### Claude Code Integration

**Auto-inject into system prompt**:

```bash
# Add/update Agent Context Graph section in CLAUDE.md
gni context-gen . --target claude --update

# Generated section:
# <!-- gitnexus:agent-context:start -->
# ## Agent Context (GitNexus)
# ### Cluster Topology
# | Role | ID | OS | SSH | Description |
# ...
# ### Available Skills
# business (15): `asset-creation`, ...
# <!-- gitnexus:agent-context:end -->
```

**Get Level 1 context from Python**:

```python
import subprocess

def get_agent_context(query: str, level: int = 1) -> str:
    """Get context to inject into a Claude system prompt."""
    result = subprocess.check_output(
        ["gni", "aq", query, "--level", str(level), "--format", "progressive"],
        text=True
    )
    return result

query = "deploy"
ctx = get_agent_context(query, level=1)

system_prompt = f"""You are an AI assistant for this workspace.

## Available Agent Context
{ctx}

If you need more detail, ask the user to run:
  gni aq "{query}" --level 3
"""
```

**Example command output**:

```bash
$ gni aq "announce" --level 1
## Agent Context [Overview] query:'announce'
skills: [announce, macbook-local-announce]
skill: 2 matched
~1534 tokens (savings: 99.2%)

$ gni aq "deploy" --level 2
## Agent Context [Standard] query:'deploy'

### Agents
- **Botan** — Deploy / Release

~200 tokens | savings: 99.9%

$ gni aq "cc-hayashi" --level 3
# Agent Context: cc-hayashi

**Agents**: Nagarerrun, Kaede, Sakura, Tsubaki, Botan
**Skills**: agent-skill-bus, claude-code-ops, codex-workers, ...
**Tokens**: ~4898 (savings: 97.5%)
```

### Codex Integration

Codex runs in an isolated sandbox, so embed context at task submission time:

```bash
# Get context before submitting a task to Codex
CONTEXT=$(gni aq "implementation task" --level 2)

# Include context in Codex's system prompt / task message
tmux send-keys -t %305 "[TASK] Please implement the feature

## Agent Context
${CONTEXT}

## Requirements
- Requirement 1
- Requirement 2

When complete, report [DONE] to %0" Enter
```

### OpenClaw Integration

Include `gni aq` output in OpenClaw agent system prompts:

```bash
#!/bin/bash
# scripts/update-heartbeat-with-context.sh

WORKSPACE="/Users/me/dev/MY_WORKSPACE"
HEARTBEAT="$WORKSPACE/HEARTBEAT.md"

# Get latest context
CONTEXT=$(gni aq "recent tasks" --level 2 --repo "$WORKSPACE")

# Update the context section in HEARTBEAT.md
python3 -c "
import re
content = open('$HEARTBEAT').read()
new_section = '''<!-- agent-context:start -->
## Agent Context
$CONTEXT
<!-- agent-context:end -->'''
updated = re.sub(
    r'<!-- agent-context:start -->.*<!-- agent-context:end -->',
    new_section, content, flags=re.DOTALL
)
open('$HEARTBEAT', 'w').write(updated)
print('Updated HEARTBEAT.md with agent context')
"
```

**Periodic refresh (cron)**:

```bash
# crontab -e
# Rebuild agent graph every morning at 6:00 and update HEARTBEAT.md
0 6 * * * cd ~/dev/MY_WORKSPACE && gni ai . --force && \
  ~/dev/MY_WORKSPACE/scripts/update-heartbeat-with-context.sh
```

---

## Code Graph vs. Agent Graph

| Use Case | Command | Graph |
|----------|---------|-------|
| Analyze function impact | `gni impact <symbol>` | Code graph |
| Look up API usage | `gni context <symbol>` | Code graph |
| Inspect an agent's node | `gni aq "agent-name" --level 2` | Agent graph |
| Look up how to use a skill | `gni aq "skill-name" --level 3` | Agent graph |
| Inject into LLM prompt | `gni aq "<keyword>" --level 1` | Agent graph |
| Update CLAUDE.md | `gni cg . --update` | Agent graph |

---

## FAQ

**Q: `gni agent-status` shows Memory Docs: 0**

A: This is a known issue in builds before v1.6.0. Run a full rebuild with `--force`:
```bash
gni ai . --force
gni as
# → Memory Docs: 25
```

**Q: `gni aq "cc-hayashi"` can't find the agent (hyphenated query)**

A: Hyphens (`-`) are treated as operators in FTS5. Use a space-separated query or search by keyword:
```bash
gni aq "cc hayashi"   # ✅ space-separated
gni aq "claude code"  # ✅ keyword search
gni aq "cc-hayashi"   # ⚠️ may cause FTS5 parse error
```

**Q: What's the difference between incremental build and `--force`?**

| Mode | Behavior | When to Use |
|------|----------|-------------|
| `gni ai .` | Nodes via `INSERT OR REPLACE`, edges cleared and rebuilt | Normal updates |
| `gni ai . --force` | DB completely dropped and recreated | After schema changes, for a clean rebuild |
| `gni ai . --dry-run` | Preview without updating DB | Checking changes |

**Q: `gni agent-status` shows fewer skills than expected**

A: Skills with duplicate `skill_id` slugs are overwritten via `INSERT OR REPLACE`. Check the actual detected count with `--dry-run`:
```bash
gni ai . --dry-run
# Skills: 83  ← count detected in dry-run
gni as
# Skills: 79  ← unique skill_id count (4 duplicates overwritten)
```

**Q: `_index_generated.md` is being indexed as a skill**

A: This is intentional. The skill index file itself becomes searchable in the graph (under the `unknown` category). To exclude it, add it to `.gitnexusignore`:
```bash
echo "SKILL/_index_generated.md" >> .gitnexusignore
```

**Q: FTS5 is not available (SQLite version issue)**

A: SQLite 3.35+ with FTS5 is required. Use the `node:sqlite` module with Node.js v24+:
```bash
node --version   # v24+ required
python3 -c "import sqlite3; print(sqlite3.sqlite_version)"  # check 3.35+
```

**Q: `gni aq` doesn't work well with non-English queries**

A: `_preprocess_query()` applies bigram splitting for CJK text. Queries with 2+ hiragana/katakana/kanji characters are automatically split into bigrams:
```
"openclaw agent"
  → "openclaw" + bigrams of "agent" (CJK characters only)
```
Single-character queries may not match. Use 2+ characters for best results.

**Q: Using the agent graph and GitNexus code graph together**

A: The two graphs are completely independent and can be used simultaneously:
```bash
# Code graph: analyze function impact
gni impact validateUser --direction upstream

# Agent graph: get context
gni aq "validate" --level 2

# Combined: understand code while accessing agent context
gni aq "deploy" --level 1 && gni context deploy --format short
```

---

## Troubleshooting

### Agent Graph DB Not Found

```
ERROR: Agent Graph DB not found: ...
Run `gni agent-index <repo> --force` first.
```

**Fix**: Run `gni ai . --force` to build the graph.

### Memory Docs Shows 0

Incremental builds reuse the existing DB, so new memory files may not be detected.
Run `gni ai . --force` for a full rebuild.

### `_index_generated` Recognized as a Skill

When `SKILL/_index_generated.md` is created, the next `gni ai --force` will index it as a skill (`unknown` category). This is intentional — the skill index itself becomes searchable in the agent graph.
