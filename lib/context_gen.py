#!/usr/bin/env python3
"""
context_gen.py — Auto-generate CLAUDE.md / AGENTS.md from Agent Context Graph

Usage:
  python3 context_gen.py <repo_path> [options]

Options:
  --target   claude|agents|skill|all   何を生成するか (default: all)
  --out-dir  <path>                    出力先 (default: <repo_path>)
  --update                             既存ファイルのセクションを更新
  --dry-run                            ファイルを書かず stdout に出力
  --json                               JSON 形式で出力 (スクリプト向け)
  --force                              既存マーカーを無視して上書き

Generated content (CLAUDE.md section):
  <!-- gitnexus:agent-context:start -->
  ... Agent Context Graph から生成したクラスタ/スキル/サービス情報 ...
  <!-- gitnexus:agent-context:end -->

Generated AGENTS.md:
  全エージェント・スキル・ノードの構造化ドキュメント
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────

DB_SUBPATH = ".gitnexus/agent-graph.db"
WS_JSON_SUBPATH = ".gitnexus/workspace.json"

SECTION_START = "<!-- gitnexus:agent-context:start -->"
SECTION_END   = "<!-- gitnexus:agent-context:end -->"


@dataclass
class GraphData:
    agents: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    knowledge_docs: list[dict] = field(default_factory=list)
    compute_nodes: list[dict] = field(default_factory=list)
    workspace_services: list[dict] = field(default_factory=list)
    skill_categories: dict[str, list[str]] = field(default_factory=dict)
    workspace: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


def load_graph(repo_path: Path) -> GraphData:
    db_path = repo_path / DB_SUBPATH
    ws_path = repo_path / WS_JSON_SUBPATH

    if not db_path.exists():
        raise FileNotFoundError(
            f"Agent Graph DB not found: {db_path}\n"
            f"Run `gni agent-index {repo_path} --force` first."
        )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    def fetchall(sql: str, params=()) -> list[dict]:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    agents = fetchall(
        "SELECT agent_id, name, emoji, role, society, type, pane_id, node_binding FROM agents ORDER BY society, name"
    )
    skills = fetchall(
        "SELECT skill_id, name, category, description, path FROM skills ORDER BY category, name"
    )
    knowledge_docs = fetchall(
        "SELECT doc_id, title, category, path, content_summary FROM knowledge_docs ORDER BY category, title LIMIT 50"
    )
    compute_nodes = fetchall(
        "SELECT node_id, name, role, os, description, ssh_host, ssh_user, ip_address, vpn, workspace_root FROM compute_nodes ORDER BY role"
    )
    workspace_services = fetchall(
        "SELECT service_id, name, service_type, node_id, description, model FROM workspace_services ORDER BY node_id"
    )

    # Stats
    stats: dict[str, int] = {}
    for table in ["agents", "skills", "knowledge_docs", "compute_nodes", "workspace_services"]:
        stats[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    conn.close()

    # Skill categories
    skill_categories: dict[str, list[str]] = {}
    for s in skills:
        cat = s.get("category") or "other"
        skill_categories.setdefault(cat, []).append(s["skill_id"])

    # workspace.json
    workspace: dict = {}
    if ws_path.exists():
        try:
            workspace = json.loads(ws_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return GraphData(
        agents=agents,
        skills=skills,
        knowledge_docs=knowledge_docs,
        compute_nodes=compute_nodes,
        workspace_services=workspace_services,
        skill_categories=skill_categories,
        workspace=workspace,
        stats=stats,
    )


# ─────────────────────────────────────────────────────────────
# Generator helpers
# ─────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _skill_index_lines(g: GraphData, max_per_cat: int = 20) -> list[str]:
    lines: list[str] = []
    for cat, ids in sorted(g.skill_categories.items()):
        shown = ids[:max_per_cat]
        suffix = f" … +{len(ids) - max_per_cat}" if len(ids) > max_per_cat else ""
        lines.append(f"  **{cat}** ({len(ids)}): `{'`, `'.join(shown)}`{suffix}")
    return lines


def _node_table_lines(g: GraphData) -> list[str]:
    lines: list[str] = []
    lines.append("| Role | ID | OS | SSH | IP | Description |")
    lines.append("|------|----|----|-----|----|-------------|")
    for n in sorted(g.compute_nodes, key=lambda x: {"gateway": 0, "primary": 1, "worker": 2}.get(x.get("role", "worker"), 9)):
        ssh = n.get("ssh_host") or "(local)"
        ip  = n.get("ip_address") or "—"
        desc = (n.get("description") or "")[:50]
        lines.append(f"| {n.get('role','')} | {n['node_id']} | {n.get('os','')} | {ssh} | {ip} | {desc} |")
    return lines


def _service_table_lines(g: GraphData) -> list[str]:
    lines: list[str] = []
    lines.append("| Service ID | Name | Type | Node | Model |")
    lines.append("|------------|------|------|------|-------|")
    for s in g.workspace_services:
        lines.append(f"| {s['service_id']} | {s['name']} | {s['service_type']} | {s.get('node_id','—')} | {s.get('model','—')} |")
    return lines


def _agent_table_lines(g: GraphData) -> list[str]:
    lines: list[str] = []
    lines.append("| Agent ID | Name | Role | Society | Pane/Node |")
    lines.append("|----------|------|------|---------|-----------|")
    for a in g.agents:
        name = f"{a.get('emoji','')} {a.get('name','')}".strip()
        node = a.get("node_binding") or a.get("pane_id") or "—"
        lines.append(f"| {a['agent_id']} | {name} | {a.get('role','')} | {a.get('society','')} | {node} |")
    return lines


# ─────────────────────────────────────────────────────────────
# CLAUDE.md section
# ─────────────────────────────────────────────────────────────

def generate_claude_section(g: GraphData, repo_path: Path) -> str:
    """Generate the <!-- gitnexus:agent-context --> section for CLAUDE.md."""
    lines: list[str] = []
    lines.append(SECTION_START)
    lines.append(f"<!-- auto-generated by `gni context-gen` at {_ts()} — do not edit manually -->")
    lines.append("")
    lines.append("## Agent Context (GitNexus)")
    lines.append("")
    lines.append("> このセクションは `gni context-gen --update` で自動更新されます。")
    lines.append("> 手動編集した内容は次回更新時に上書きされます。")
    lines.append("")

    # Cluster topology
    if g.compute_nodes:
        ws = g.workspace
        cluster = ws.get("cluster", {})
        topology = cluster.get("topology", "hub-spoke")
        transport = cluster.get("transport", "tailscale")
        gw_url = cluster.get("labels", {}).get("gateway_url", "—")
        lines.append("### Cluster Topology")
        lines.append("")
        lines.append(f"- **topology**: {topology}  **transport**: {transport}")
        lines.append(f"- **gateway_url**: {gw_url}")
        lines.append(f"- **nodes**: {g.stats.get('compute_nodes', 0)}  **services**: {g.stats.get('workspace_services', 0)}")
        lines.append("")
        lines.extend(_node_table_lines(g))
        lines.append("")

    # Workspace services
    if g.workspace_services:
        lines.append("### Workspace Services")
        lines.append("")
        lines.extend(_service_table_lines(g))
        lines.append("")

    # Agents (from AGENTS.md or agents-related KNOWLEDGE docs)
    if g.agents:
        lines.append("### Agents")
        lines.append("")
        lines.extend(_agent_table_lines(g))
        lines.append("")

    # Skills
    if g.skills:
        lines.append("### Available Skills")
        lines.append("")
        lines.append(f"Total: **{g.stats.get('skills', 0)} skills** ({len(g.skill_categories)} categories)")
        lines.append("")
        lines.extend(_skill_index_lines(g, max_per_cat=15))
        lines.append("")

    # How to query
    lines.append("### Querying the Agent Context Graph")
    lines.append("")
    lines.append("```bash")
    lines.append("# Level 1 — Overview (~100 tokens): What's available?")
    lines.append("gni aq \"<keyword>\" --level 1")
    lines.append("")
    lines.append("# Level 2 — Standard (~400 tokens): Names + roles + descriptions (default)")
    lines.append("gni aq \"deploy\"")
    lines.append("")
    lines.append("# Level 3 — Full (~2000 tokens): Complete detail on demand")
    lines.append("gni aq \"cc-hayashi\" --level 3")
    lines.append("")
    lines.append("# Update this section")
    lines.append(f"gni context-gen {repo_path} --update")
    lines.append("```")
    lines.append("")
    lines.append(SECTION_END)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# AGENTS.md
# ─────────────────────────────────────────────────────────────

def generate_agents_md(g: GraphData, repo_path: Path) -> str:
    """Generate AGENTS.md — full structured agent manifest for AI agents."""
    lines: list[str] = []
    lines.append("# AGENTS.md")
    lines.append(f"<!-- auto-generated by `gni context-gen` at {_ts()} — do not edit manually -->")
    lines.append("")
    lines.append("> **Machine-readable agent manifest** for Codex, Claude Code, and other AI agents.")
    lines.append("> Update with: `gni context-gen --update`")
    lines.append("")

    # Stats summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Agents**: {g.stats.get('agents', 0)}")
    lines.append(f"- **Skills**: {g.stats.get('skills', 0)}")
    lines.append(f"- **Knowledge Docs**: {g.stats.get('knowledge_docs', 0)}")
    lines.append(f"- **Compute Nodes**: {g.stats.get('compute_nodes', 0)}")
    lines.append(f"- **Workspace Services**: {g.stats.get('workspace_services', 0)}")
    lines.append("")

    # Cluster
    if g.compute_nodes:
        ws = g.workspace
        cluster = ws.get("cluster", {})
        lines.append("## Cluster Topology")
        lines.append("")
        topology = cluster.get("topology", "hub-spoke")
        transport = cluster.get("transport", "tailscale")
        lines.append(f"```yaml")
        lines.append(f"topology: {topology}")
        lines.append(f"transport: {transport}")
        gw_url = cluster.get("labels", {}).get("gateway_url", "")
        if gw_url:
            lines.append(f"gateway_url: {gw_url}")
        lines.append("```")
        lines.append("")
        lines.append("### Compute Nodes")
        lines.append("")
        lines.extend(_node_table_lines(g))
        lines.append("")

    # Services section
    if g.workspace_services:
        lines.append("## Workspace Services")
        lines.append("")
        lines.extend(_service_table_lines(g))
        lines.append("")

    # Agents
    if g.agents:
        lines.append("## Agents")
        lines.append("")
        for society in sorted(set(a.get("society", "other") for a in g.agents)):
            society_agents = [a for a in g.agents if a.get("society") == society]
            lines.append(f"### {society.title()} Society ({len(society_agents)})")
            lines.append("")
            for a in society_agents:
                name = f"{a.get('emoji', '')} {a.get('name', '')}".strip()
                lines.append(f"#### {name} (`{a['agent_id']}`)")
                lines.append(f"- **Role**: {a.get('role', '—')}")
                node = a.get("node_binding") or a.get("pane_id") or "—"
                lines.append(f"- **Pane/Node**: {node}")
                lines.append("")

    # Skills
    if g.skills:
        lines.append("## Skills")
        lines.append("")
        lines.append(f"Total: **{g.stats.get('skills', 0)} skills**  |  Invoke: `gni aq \"<keyword>\" --level 2`")
        lines.append("")
        for cat in sorted(g.skill_categories.keys()):
            ids = g.skill_categories[cat]
            lines.append(f"### {cat.title()} ({len(ids)})")
            lines.append("")
            cat_skills = [s for s in g.skills if s.get("category") == cat]
            lines.append("| Skill | Description |")
            lines.append("|-------|-------------|")
            for s in cat_skills:
                desc = (s.get("description") or "—")[:80]
                lines.append(f"| `{s['skill_id']}` | {desc} |")
            lines.append("")

    # Knowledge Docs
    if g.knowledge_docs:
        lines.append("## Knowledge Docs")
        lines.append("")
        # group by category
        cats: dict[str, list[dict]] = {}
        for d in g.knowledge_docs:
            cats.setdefault(d.get("category") or "other", []).append(d)
        for cat, docs in sorted(cats.items()):
            lines.append(f"### {cat.title()} ({len(docs)})")
            lines.append("")
            for d in docs[:20]:
                title = (d.get("title") or d["doc_id"])[:60]
                path  = d.get("path") or ""
                if path:
                    lines.append(f"- **{title}** — `{path}`")
                else:
                    lines.append(f"- **{title}**")
            if len(docs) > 20:
                lines.append(f"- *(+{len(docs) - 20} more)*")
            lines.append("")

    # How to use
    lines.append("## How to Use")
    lines.append("")
    lines.append("```bash")
    lines.append("# Quick lookup (for AI agents in system prompt)")
    lines.append("gni aq \"<keyword>\" --level 1   # ~100 tokens")
    lines.append("gni aq \"deploy\"                 # Level 2, ~400 tokens")
    lines.append("gni aq \"cc-hayashi\" --level 3   # Full detail, ~2000 tokens")
    lines.append("")
    lines.append("# Regenerate this file")
    lines.append(f"gni context-gen {repo_path} --update")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# SKILL index markdown
# ─────────────────────────────────────────────────────────────

def generate_skill_index_md(g: GraphData) -> str:
    """Generate SKILL/_index_generated.md — quick skill reference."""
    lines: list[str] = []
    lines.append("# Skill Index (auto-generated)")
    lines.append(f"<!-- auto-generated by `gni context-gen` at {_ts()} -->")
    lines.append("")
    lines.append(f"Total: **{g.stats.get('skills', 0)} skills** across {len(g.skill_categories)} categories.")
    lines.append("")
    lines.append("## Quick Reference")
    lines.append("")
    for cat in sorted(g.skill_categories.keys()):
        ids = g.skill_categories[cat]
        lines.append(f"- **{cat}** ({len(ids)}): " + ", ".join(f"`{i}`" for i in ids[:10]) + ("…" if len(ids) > 10 else ""))
    lines.append("")
    lines.append("## Full Listing")
    lines.append("")
    for cat in sorted(g.skill_categories.keys()):
        cat_skills = [s for s in g.skills if s.get("category") == cat]
        lines.append(f"### {cat.title()}")
        lines.append("")
        for s in cat_skills:
            desc = (s.get("description") or "")[:80]
            if desc:
                lines.append(f"- **`{s['skill_id']}`** — {desc}")
            else:
                lines.append(f"- **`{s['skill_id']}`**")
        lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# File update helpers
# ─────────────────────────────────────────────────────────────

def _inject_section(existing: str, new_section: str) -> tuple[str, bool]:
    """Replace or append gitnexus section in existing file content."""
    pattern = re.compile(
        r"<!-- gitnexus:agent-context:start -->.*?<!-- gitnexus:agent-context:end -->",
        re.DOTALL,
    )
    if pattern.search(existing):
        updated = pattern.sub(new_section, existing)
        return updated, True
    else:
        sep = "\n\n" if existing.rstrip() else ""
        return existing.rstrip() + sep + "\n" + new_section + "\n", False


def write_or_update(path: Path, content: str, update: bool, dry_run: bool, label: str) -> str:
    """Write/update a file. Returns action taken."""
    if dry_run:
        print(f"\n{'='*60}")
        print(f"[DRY RUN] Would write: {path}")
        print(f"{'='*60}")
        # show first 60 lines
        for line in content.splitlines()[:60]:
            print(line)
        if len(content.splitlines()) > 60:
            print(f"  ... (+{len(content.splitlines()) - 60} more lines)")
        return f"dry-run: {path}"

    if update and path.exists():
        existing = path.read_text(encoding="utf-8")
        new_content, replaced = _inject_section(existing, content)
        if new_content == existing:
            return f"no-change: {path}"
        path.write_text(new_content, encoding="utf-8")
        action = "updated" if replaced else "appended"
        return f"{action}: {path}"
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"created: {path}"


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="context_gen.py",
        description="Auto-generate CLAUDE.md/AGENTS.md from Agent Context Graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          python3 context_gen.py ~/dev/HAYASHI_SHUNSUKE
          python3 context_gen.py . --target claude --update
          python3 context_gen.py . --dry-run
          python3 context_gen.py . --json
        """),
    )
    parser.add_argument("repo_path", nargs="?", default=".",
                        help="Repository root path (default: current dir)")
    parser.add_argument("--target", choices=["claude", "agents", "skill", "all"],
                        default="all", help="What to generate (default: all)")
    parser.add_argument("--out-dir", metavar="PATH",
                        help="Output directory (default: same as repo_path)")
    parser.add_argument("--update", action="store_true",
                        help="Update existing files (inject/replace section)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print output without writing files")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON summary")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite files even if markers are absent")

    args = parser.parse_args(argv)

    repo_path = Path(args.repo_path).expanduser().resolve()
    out_dir   = Path(args.out_dir).expanduser().resolve() if args.out_dir else repo_path

    if not repo_path.exists():
        print(f"ERROR: repo_path not found: {repo_path}", file=sys.stderr)
        return 1

    # Load graph
    try:
        g = load_graph(repo_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    results: dict[str, str] = {}
    update = args.update or args.force

    # --- CLAUDE.md section ---
    if args.target in ("claude", "all"):
        section = generate_claude_section(g, repo_path)
        claude_path = out_dir / "CLAUDE.md"
        if args.target == "claude" and args.dry_run:
            # For `--target claude --dry-run`, print section only
            print(section)
            return 0
        if claude_path.exists() and not update:
            # Safety: don't overwrite existing CLAUDE.md without --update
            results["claude"] = (
                f"skipped: {claude_path} already exists — use --update to inject section"
            )
        else:
            action = write_or_update(
                claude_path, section,
                update=update, dry_run=args.dry_run, label="CLAUDE.md"
            )
            results["claude"] = action

    # --- AGENTS.md ---
    if args.target in ("agents", "all"):
        agents_md = generate_agents_md(g, repo_path)
        agents_path = out_dir / "AGENTS.md"
        action = write_or_update(
            agents_path, agents_md,
            update=False, dry_run=args.dry_run, label="AGENTS.md"
        )
        results["agents"] = action

    # --- SKILL index ---
    if args.target in ("skill", "all"):
        skill_dir = repo_path / "SKILL"
        if skill_dir.exists():
            skill_index = generate_skill_index_md(g)
            skill_path = skill_dir / "_index_generated.md"
            action = write_or_update(
                skill_path, skill_index,
                update=False, dry_run=args.dry_run, label="SKILL/_index_generated.md"
            )
            results["skill"] = action
        else:
            results["skill"] = f"skipped: SKILL/ not found in {repo_path}"

    # Output
    if args.json:
        out = {
            "repo_path": str(repo_path),
            "out_dir":   str(out_dir),
            "generated": results,
            "stats":     g.stats,
            "ts":        _ts(),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif not args.dry_run:
        print(f"\n✅ context-gen complete ({_ts()})")
        print(f"   repo:    {repo_path}")
        print(f"   out_dir: {out_dir}")
        print()
        for k, v in results.items():
            action, _, path = v.partition(": ")
            icon = {"created": "📄", "updated": "✏️", "appended": "➕",
                    "no-change": "✓", "dry-run": "🔍", "skipped": "⏭️"}.get(action, "?")
            print(f"   {icon}  {action:12s}  {path or v}")
        print()
        print(f"   💡 Run `gni aq \"<keyword>\"` to query the agent graph.")
        print(f"   💡 Run `gni context-gen {repo_path} --update` to refresh.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
