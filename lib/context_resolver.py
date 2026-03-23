#!/usr/bin/env python3
"""
Context Resolver — Phase 2
Resolves natural-language queries to relevant Agent Graph nodes
using hybrid scoring (BM25 + GraphDistance + TypeWeight).

Ref: REQUIREMENTS-agent-context-graph-v2.md (FR-002, FR-003)
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("context-resolver")

# --- Scoring Constants ---

# Hybrid Score = W_BM25 * BM25 + W_GRAPH * GraphScore + W_TYPE * TypeWeight
W_BM25 = 0.5
W_GRAPH = 0.3
W_TYPE = 0.2

# Type weights (higher = more relevant for context)
TYPE_WEIGHTS = {
    "Skill": 1.0,
    "Agent": 0.9,
    "KnowledgeDoc": 0.7,
    "DataSource": 0.5,
    "ExternalService": 0.3,
}

# Task type → type weight adjustments
TASK_TYPE_ADJUSTMENTS = {
    "bugfix": {"Skill": 0.8, "KnowledgeDoc": 1.0, "DataSource": 0.7},
    "feature": {"Skill": 1.0, "Agent": 1.0, "KnowledgeDoc": 0.6},
    "refactor": {"Skill": 0.9, "KnowledgeDoc": 0.5, "DataSource": 0.3},
}

# Default token budget
DEFAULT_MAX_TOKENS = 5000
DEFAULT_DEPTH = 2
BYTES_PER_TOKEN = 3.7


@dataclass
class ScoredNode:
    node_id: str
    node_type: str
    name: str
    score: float
    depth: int
    path: str = ""
    token_estimate: int = 0
    description: str = ""
    keywords: str = ""


@dataclass
class ContextResult:
    version: str = "2.0"
    query: str = ""
    matched_agents: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    context_chain: list[dict] = field(default_factory=list)
    files_to_read: list[str] = field(default_factory=list)
    estimated_tokens: int = 0
    savings_vs_full: str = "0%"
    metadata: dict = field(default_factory=dict)
    is_fallback: bool = False  # True when no query match found; showing default context


# --- Query Preprocessing ---

# Common Japanese single-character particles to strip from queries.
# Note: multi-char particles like "から", "まで", "より" are handled by bigram splitting.
_JA_PARTICLES = {"を", "は", "が", "の", "で", "に", "へ", "と", "も", "か"}

def _preprocess_query(query: str) -> str:
    """Preprocess a query for FTS5: split Japanese, remove particles, join with OR."""
    raw = query.strip()
    if not raw:
        return ""

    # Split on whitespace first
    parts = raw.split()
    tokens: list[str] = []

    for part in parts:
        # Check if part contains CJK characters
        cjk_chars = re.findall(r'[\u3000-\u9fff\uf900-\ufaff]+', part)
        if cjk_chars:
            for chunk in cjk_chars:
                # Remove particles and extract content characters
                cleaned = "".join(c for c in chunk if c not in _JA_PARTICLES)
                if len(cleaned) >= 2:
                    # Generate bigrams for better FTS5 matching
                    for i in range(len(cleaned) - 1):
                        bigram = cleaned[i:i+2]
                        tokens.append(bigram)
                elif cleaned:
                    tokens.append(cleaned)
            # Also keep any non-CJK parts
            non_cjk = re.sub(r'[\u3000-\u9fff\uf900-\ufaff]+', ' ', part).strip()
            if non_cjk:
                tokens.extend(non_cjk.split())
        else:
            tokens.append(part)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return " OR ".join(unique) if unique else raw


# --- FTS5 Search ---

def fts5_search(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[ScoredNode]:
    """Search Agent Graph FTS5 index with BM25 ranking."""
    results = []

    fts_query = query.strip()
    if not fts_query:
        return results

    # Try raw query first, then preprocessed
    for attempt_query in [fts_query, _preprocess_query(fts_query)]:
        if not attempt_query:
            continue
        try:
            rows = conn.execute(
                """
                SELECT node_id, node_type, name, keywords, description,
                       bm25(agent_fts) AS rank
                FROM agent_fts
                WHERE agent_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (attempt_query, limit),
            ).fetchall()
            if rows:
                break
        except sqlite3.OperationalError:
            continue
    else:
        # Final fallback: split on spaces, OR-join
        terms = fts_query.split()
        fts_or = " OR ".join(terms) if len(terms) > 1 else fts_query
        try:
            rows = conn.execute(
                """
                SELECT node_id, node_type, name, keywords, description,
                       bm25(agent_fts) AS rank
                FROM agent_fts
                WHERE agent_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_or, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.warning("FTS5 search failed for query: %s", fts_query)
            return results

    for row in rows:
        # BM25 returns negative values (lower = better match)
        # Normalize: convert to 0-1 range where 1 is best
        bm25_raw = abs(row[5]) if row[5] else 0
        bm25_score = min(1.0, bm25_raw / 10.0) if bm25_raw > 0 else 0

        results.append(ScoredNode(
            node_id=row[0],
            node_type=row[1],
            name=row[2],
            score=bm25_score,
            depth=0,
            keywords=row[3] or "",
            description=row[4] or "",
        ))

    return results


# --- Graph Traversal ---

def expand_neighbors(
    conn: sqlite3.Connection,
    node_id: str,
    node_type: str,
    depth: int,
    max_depth: int,
    visited: set[str],
    repo_root: Optional[Path] = None,
) -> list[ScoredNode]:
    """DFS expansion: find neighbors of a node via agent_relations."""
    if depth >= max_depth:
        return []

    neighbors = []
    key = f"{node_type}:{node_id}"
    if key in visited:
        return []
    visited.add(key)

    # Find outgoing edges
    rows = conn.execute(
        """
        SELECT target_id, target_type, relation_type, weight
        FROM agent_relations
        WHERE source_id = ? AND source_type = ?
        """,
        (node_id, node_type),
    ).fetchall()

    # Find incoming edges
    rows += conn.execute(
        """
        SELECT source_id, source_type, relation_type, weight
        FROM agent_relations
        WHERE target_id = ? AND target_type = ?
        """,
        (node_id, node_type),
    ).fetchall()

    for row in rows:
        neighbor_id = row[0]
        neighbor_type = row[1]
        edge_weight = row[3] if row[3] else 1.0

        nkey = f"{neighbor_type}:{neighbor_id}"
        if nkey in visited:
            continue

        # Graph distance score: decays with depth
        graph_score = edge_weight / (depth + 1)

        # Look up node details
        name, path, token_est, desc = _lookup_node(conn, neighbor_id, neighbor_type, repo_root)

        neighbors.append(ScoredNode(
            node_id=neighbor_id,
            node_type=neighbor_type,
            name=name,
            score=graph_score,
            depth=depth + 1,
            path=path,
            token_estimate=token_est,
            description=desc,
        ))

        # Recurse
        neighbors.extend(
            expand_neighbors(conn, neighbor_id, neighbor_type,
                             depth + 1, max_depth, visited, repo_root)
        )

    return neighbors


def _lookup_node(
    conn: sqlite3.Connection,
    node_id: str,
    node_type: str,
    repo_root: Optional[Path] = None,
) -> tuple[str, str, int, str]:
    """Look up node name, path, token estimate, and description.

    Returns (name, path, token_estimate, description).
    """
    if node_type == "Agent":
        row = conn.execute(
            "SELECT name, '', 0, COALESCE(role, '') FROM agents WHERE agent_id = ?",
            (node_id,),
        ).fetchone()
    elif node_type == "Skill":
        row = conn.execute(
            "SELECT name, path, 0, COALESCE(description, '') FROM skills WHERE skill_id = ?",
            (node_id,),
        ).fetchone()
        if row:
            # Estimate tokens from file
            path = row[1]
            token_est = _estimate_tokens_from_path(path, repo_root)
            return row[0], path, token_est, row[3]
    elif node_type == "KnowledgeDoc":
        row = conn.execute(
            "SELECT title, path, token_estimate, COALESCE(content_summary, '') "
            "FROM knowledge_docs WHERE doc_id = ?",
            (node_id,),
        ).fetchone()
    elif node_type == "DataSource":
        row = conn.execute(
            "SELECT name, path, 0, '' FROM data_sources WHERE ds_id = ?", (node_id,)
        ).fetchone()
    elif node_type == "ExternalService":
        row = conn.execute(
            "SELECT name, '', 0, '' FROM external_services WHERE svc_id = ?", (node_id,)
        ).fetchone()
    else:
        row = None

    if row:
        return row[0], row[1], row[2], row[3]
    return node_id, "", 0, ""


def _estimate_tokens_from_path(rel_path: str, repo_root: Optional[Path] = None) -> int:
    """Estimate tokens from a file path, resolving relative to repo_root if given."""
    candidates = []
    if repo_root:
        candidates.append(repo_root / rel_path)
    candidates.append(Path(rel_path))

    for p in candidates:
        if p.exists():
            try:
                return int(p.stat().st_size / BYTES_PER_TOKEN)
            except OSError:
                pass
    return 200  # Default estimate for unknown files


# --- Hybrid Scoring ---

def compute_hybrid_scores(
    fts_results: list[ScoredNode],
    graph_results: list[ScoredNode],
    task_type: Optional[str] = None,
) -> list[ScoredNode]:
    """Merge FTS5 and graph results with hybrid scoring."""
    merged: dict[str, ScoredNode] = {}

    # Add FTS5 results (depth=0, BM25 score)
    for node in fts_results:
        key = f"{node.node_type}:{node.node_id}"
        type_weight = TYPE_WEIGHTS.get(node.node_type, 0.5)
        if task_type and task_type in TASK_TYPE_ADJUSTMENTS:
            adj = TASK_TYPE_ADJUSTMENTS[task_type]
            type_weight = adj.get(node.node_type, type_weight)

        node.score = W_BM25 * node.score + W_TYPE * type_weight
        merged[key] = node

    # Add/merge graph results
    for node in graph_results:
        key = f"{node.node_type}:{node.node_id}"
        type_weight = TYPE_WEIGHTS.get(node.node_type, 0.5)
        if task_type and task_type in TASK_TYPE_ADJUSTMENTS:
            adj = TASK_TYPE_ADJUSTMENTS[task_type]
            type_weight = adj.get(node.node_type, type_weight)

        graph_component = W_GRAPH * node.score
        type_component = W_TYPE * type_weight

        if key in merged:
            # Combine: existing BM25 component + graph component
            existing = merged[key]
            existing.score += graph_component
            if node.path and not existing.path:
                existing.path = node.path
            if node.token_estimate and not existing.token_estimate:
                existing.token_estimate = node.token_estimate
            if node.depth < existing.depth:
                existing.depth = node.depth
        else:
            node.score = graph_component + type_component
            merged[key] = node

    # Sort by score (descending)
    result = sorted(merged.values(), key=lambda n: n.score, reverse=True)
    return result


# --- Context Assembly ---

def assemble_context(
    conn: sqlite3.Connection,
    query: str,
    agent_name: Optional[str] = None,
    skill_name: Optional[str] = None,
    depth: int = DEFAULT_DEPTH,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    task_type: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> ContextResult:
    """Main entry: resolve query to context chain with token budget."""
    start_time = time.time()
    result = ContextResult(query=query)

    # Step 1: Determine entry points
    fts_results: list[ScoredNode] = []
    direct_nodes: list[ScoredNode] = []

    if agent_name:
        # Direct agent lookup
        row = conn.execute(
            "SELECT agent_id, name FROM agents WHERE agent_id = ? OR name = ?",
            (agent_name, agent_name),
        ).fetchone()
        if row:
            direct_nodes.append(ScoredNode(
                node_id=row[0], node_type="Agent", name=row[1],
                score=1.0, depth=0,
            ))
    elif skill_name:
        # Direct skill lookup
        row = conn.execute(
            "SELECT skill_id, name, path FROM skills WHERE skill_id = ? OR name = ?",
            (skill_name, skill_name),
        ).fetchone()
        if row:
            token_est = _estimate_tokens_from_path(row[2], repo_root) if row[2] else 200
            direct_nodes.append(ScoredNode(
                node_id=row[0], node_type="Skill", name=row[1],
                score=1.0, depth=0, path=row[2], token_estimate=token_est,
            ))
    else:
        # FTS5 search
        fts_results = fts5_search(conn, query)

    # Step 2: Graph expansion from entry points
    visited: set[str] = set()
    graph_results: list[ScoredNode] = []

    entry_nodes = direct_nodes if direct_nodes else fts_results[:5]
    for node in entry_nodes:
        neighbors = expand_neighbors(
            conn, node.node_id, node.node_type,
            depth=0, max_depth=depth, visited=visited,
            repo_root=repo_root,
        )
        graph_results.extend(neighbors)

        # Ensure entry node has path info and description
        if not node.path or not node.description:
            name, path, token_est, desc = _lookup_node(conn, node.node_id, node.node_type, repo_root)
            if not node.path:
                node.path = path
                node.token_estimate = token_est
            if not node.description and desc:
                node.description = desc

    # Step 3: Hybrid scoring
    all_results = fts_results + direct_nodes
    scored = compute_hybrid_scores(all_results, graph_results, task_type)

    # Step 4: Apply token budget
    total_tokens = 0
    selected: list[ScoredNode] = []
    for node in scored:
        node_tokens = node.token_estimate or 200
        if total_tokens + node_tokens > max_tokens and selected:
            break
        selected.append(node)
        total_tokens += node_tokens

    # Step 5: Fallback — if nothing found, return P0 minimal context
    is_fallback = False
    if not selected:
        selected = _fallback_context(conn, repo_root)
        total_tokens = sum(n.token_estimate or 200 for n in selected)
        is_fallback = True

    # Step 6: Build result
    files = []
    agents_found = set()
    skills_found = set()

    for node in selected:
        chain_entry = {
            "type": node.node_type,
            "name": node.name,
            "node_id": node.node_id,
            "score": round(node.score, 3),
            "depth": node.depth,
        }
        # Include description when available (populated by FTS5 search results)
        if node.description:
            chain_entry["description"] = node.description
        if node.path:
            chain_entry["path"] = node.path
            chain_entry["token_estimate"] = node.token_estimate
            if node.path not in files and node.node_type in ("Skill", "KnowledgeDoc"):
                files.append(node.path)

        result.context_chain.append(chain_entry)

        if node.node_type == "Agent":
            agents_found.add(node.name)
        elif node.node_type == "Skill":
            skills_found.add(node.node_id)

    result.matched_agents = sorted(agents_found)
    result.matched_skills = sorted(skills_found)
    result.files_to_read = files
    result.estimated_tokens = total_tokens

    # Calculate savings
    total_possible = _count_total_tokens(conn)
    if total_possible > 0:
        pct = (1 - total_tokens / total_possible) * 100
        result.savings_vs_full = f"{pct:.1f}%"

    result.metadata = {
        "execution_time_ms": int((time.time() - start_time) * 1000),
        "total_nodes_explored": len(visited) + len(all_results),
        "depth": depth,
        "max_tokens": max_tokens,
        "task_type": task_type or "general",
    }

    return result


def _fallback_context(conn: sqlite3.Connection, repo_root: Optional[Path] = None) -> list[ScoredNode]:
    """P0 minimal context: return top agents and most-connected skills."""
    fallback = []

    # All agents — include role as description so Level 2 can display it
    for row in conn.execute(
        "SELECT agent_id, name, COALESCE(role, '') FROM agents LIMIT 5"
    ).fetchall():
        fallback.append(ScoredNode(
            node_id=row[0], node_type="Agent", name=row[1],
            score=0.5, depth=0, description=row[2],
        ))

    # Top skills by edge count — include description for Level 2 display
    rows = conn.execute(
        """
        SELECT s.skill_id, s.name, s.path, COUNT(ar.relation_id) as edge_count,
               COALESCE(s.description, '') as description
        FROM skills s
        LEFT JOIN agent_relations ar ON s.skill_id = ar.target_id
        GROUP BY s.skill_id
        ORDER BY edge_count DESC
        LIMIT 5
        """
    ).fetchall()
    for row in rows:
        token_est = _estimate_tokens_from_path(row[2], repo_root) if row[2] else 200
        fallback.append(ScoredNode(
            node_id=row[0], node_type="Skill", name=row[1],
            score=0.3, depth=1, path=row[2], token_estimate=token_est,
            description=row[4],
        ))

    return fallback


def _count_total_tokens(conn: sqlite3.Connection) -> int:
    """Count total tokens across all indexed files."""
    row = conn.execute(
        "SELECT SUM(token_estimate) FROM knowledge_docs"
    ).fetchone()
    knowledge_tokens = row[0] or 0

    # Estimate skill tokens (not stored in DB, use default)
    row = conn.execute("SELECT COUNT(*) FROM skills").fetchone()
    skill_count = row[0] or 0
    skill_tokens = skill_count * 500  # Rough estimate

    return knowledge_tokens + skill_tokens


# --- Progressive Disclosure Output (Level 1/2/3) ---

def format_progressive(result: ContextResult, level: int = 2) -> str:
    """Format context result using Progressive Disclosure at the specified level.

    Progressive Disclosure levels:
      Level 1 (Overview)  — ~100 tokens  — IDs and counts only
      Level 2 (Standard)  — ~400 tokens  — Names, roles, key attributes (default)
      Level 3 (Full)      — ~2000 tokens — Complete info + all edges + files

    Designed for LLM system prompt injection:
      - Use Level 1 for "what exists" broad context awareness
      - Use Level 2 as default system prompt context
      - Use Level 3 when the LLM needs to act on a specific node
    """
    level = max(1, min(3, level))
    lines = []

    if level == 1:
        # --- Level 1: Overview --- IDs and counts only
        lines.append(f"## Agent Context [Overview] query:{result.query!r}")
        if result.is_fallback:
            lines.append("*(no direct match — showing default context)*")
        if result.matched_agents:
            lines.append(f"agents: [{', '.join(result.matched_agents)}]")
        if result.matched_skills:
            truncated = result.matched_skills[:6]
            suffix = f"  +{len(result.matched_skills)-6} more" if len(result.matched_skills) > 6 else ""
            lines.append(f"skills: [{', '.join(truncated)}]{suffix}")
        by_type: dict[str, list[str]] = {}
        for entry in result.context_chain:
            t = entry.get("type", "?")
            by_type.setdefault(t, []).append(entry.get("name", entry.get("node_id", "?")))
        for t, names in by_type.items():
            lines.append(f"{t.lower()}: {len(names)} matched")
        lines.append(f"~{result.estimated_tokens} tokens (savings: {result.savings_vs_full})")

    elif level == 2:
        # --- Level 2: Standard --- Names, roles, key attributes
        lines.append(f"## Agent Context [Standard] query:{result.query!r}")
        if result.is_fallback:
            lines.append("")
            lines.append("> No direct match found — showing default workspace context.")
        lines.append("")
        if result.matched_agents:
            lines.append("### Agents")
            # Build lookup by both node_id and name for robust matching
            chain_by_id = {e.get("node_id"): e for e in result.context_chain}
            chain_by_name = {e.get("name"): e for e in result.context_chain}
            for agent_ref in result.matched_agents:
                # matched_agents stores .name values; look up by name first
                entry = chain_by_name.get(agent_ref) or chain_by_id.get(agent_ref)
                if entry:
                    name = entry.get("name", agent_ref)
                    desc = entry.get("description", "")
                    desc_str = f" — {desc[:60]}" if desc else ""
                    lines.append(f"- **{name}**{desc_str}")
                else:
                    lines.append(f"- **{agent_ref}**")
        if result.matched_skills:
            lines.append("")
            lines.append("### Skills")
            chain_by_id = {e.get("node_id"): e for e in result.context_chain}
            for skill_id in result.matched_skills[:8]:
                entry = chain_by_id.get(skill_id)
                if entry:
                    desc = entry.get("description", "")
                    desc_str = f" — {desc[:60]}" if desc else ""
                    lines.append(f"- **{skill_id}**{desc_str}")
                else:
                    lines.append(f"- **{skill_id}**")
            if len(result.matched_skills) > 8:
                lines.append(f"  *(+{len(result.matched_skills)-8} more — use level=3 for full list)*")
        lines.append("")
        lines.append(f"~{result.estimated_tokens} tokens | savings: {result.savings_vs_full}")

    else:
        # --- Level 3: Full --- Complete info + all edges + files (delegates to format_markdown)
        lines.append(format_markdown(result))
        lines.append("")
        lines.append("*(Progressive Disclosure Level 3 — full detail)*")

    return "\n".join(lines)


# --- Markdown Output ---

def format_markdown(result: ContextResult) -> str:
    """Format context result as Markdown."""
    lines = []
    lines.append(f"# Agent Context: {result.query}")
    lines.append("")

    if result.matched_agents:
        lines.append(f"**Agents**: {', '.join(result.matched_agents)}")
    if result.matched_skills:
        lines.append(f"**Skills**: {', '.join(result.matched_skills)}")
    lines.append(f"**Tokens**: ~{result.estimated_tokens} (savings: {result.savings_vs_full})")
    lines.append("")

    if result.files_to_read:
        lines.append("## Files to Read")
        lines.append("")
        for f in result.files_to_read:
            lines.append(f"- `{f}`")
        lines.append("")

    if result.context_chain:
        lines.append("## Context Chain")
        lines.append("")
        lines.append("| Type | Name | Score | Depth |")
        lines.append("|------|------|-------|-------|")
        for entry in result.context_chain:
            lines.append(
                f"| {entry['type']} | {entry['name']} | "
                f"{entry['score']:.3f} | {entry['depth']} |"
            )
        lines.append("")

    return "\n".join(lines)


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description="Context Resolver — Resolve queries to Agent Graph context"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Natural language query")
    parser.add_argument("--repo", type=Path, default=Path.cwd(),
                        help="Repository root (default: CWD)")
    parser.add_argument("--db", type=Path, default=None,
                        help="Database path (default: REPO/.gitnexus/agent-graph.db)")
    parser.add_argument("--agent", type=str, default=None,
                        help="Direct agent lookup by ID or name")
    parser.add_argument("--skill", type=str, default=None,
                        help="Direct skill lookup by ID or name")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH,
                        help=f"Graph traversal depth (default: {DEFAULT_DEPTH})")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help=f"Token budget (default: {DEFAULT_MAX_TOKENS})")
    parser.add_argument("--task-type", type=str, default=None,
                        choices=["bugfix", "feature", "refactor"],
                        help="Task type for scoring adjustment")
    parser.add_argument("--format", type=str, default="json",
                        choices=["json", "markdown", "progressive"],
                        help="Output format (default: json)")
    parser.add_argument("--json", action="store_true",
                        help="Shorthand for --format json")
    parser.add_argument("--level", type=int, default=2,
                        choices=[1, 2, 3],
                        help="Progressive Disclosure level: 1=Overview, 2=Standard, 3=Full (default: 2)")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if os.environ.get("DEBUG") else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    repo_root = args.repo.resolve()
    db_path = args.db or (repo_root / ".gitnexus" / "agent-graph.db")

    if not db_path.exists():
        print(json.dumps({"error": "Agent Graph not found. Run: gni agent-index"}),
              file=sys.stderr)
        sys.exit(1)

    # Need a query, agent, or skill
    query = args.query
    if not query and not args.agent and not args.skill:
        parser.print_help()
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    try:
        result = assemble_context(
            conn=conn,
            query=query,
            agent_name=args.agent,
            skill_name=args.skill,
            depth=args.depth,
            max_tokens=args.max_tokens,
            task_type=args.task_type,
            repo_root=repo_root,
        )
    finally:
        conn.close()

    output_format = "json" if args.json else args.format
    if output_format == "progressive":
        print(format_progressive(result, level=args.level))
    elif output_format == "markdown":
        print(format_markdown(result))
    else:
        # Convert dataclass to dict
        out = {
            "version": result.version,
            "query": result.query,
            "matched_agents": result.matched_agents,
            "matched_skills": result.matched_skills,
            "context_chain": result.context_chain,
            "files_to_read": result.files_to_read,
            "estimated_tokens": result.estimated_tokens,
            "savings_vs_full": result.savings_vs_full,
            "metadata": result.metadata,
        }
        if args.level != 2:
            out["disclosure_level"] = args.level
        print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
