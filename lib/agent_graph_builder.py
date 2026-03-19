#!/usr/bin/env python3
"""
Agent Graph Builder — Phase 1 Indexer
Parses Agent/Skill/Knowledge/DataSource definitions and builds
a SQLite-backed Agent Context Graph with FTS5 search.

Ref: REQUIREMENTS-agent-context-graph-v2.md (FR-001)
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent-graph-builder")

# --- Data Classes ---

@dataclass
class AgentNode:
    agent_id: str
    name: str
    role: str
    society: str
    type: str  # local / openclaw / acp
    emoji: str = ""
    pane_id: str = ""
    node_binding: str = ""
    keywords: list[str] = field(default_factory=list)

@dataclass
class SkillNode:
    skill_id: str
    name: str
    category: str
    path: str
    version: str = ""
    priority: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    external_services: list[str] = field(default_factory=list)

@dataclass
class KnowledgeDocNode:
    doc_id: str
    title: str
    path: str
    category: str
    type: str = "markdown"
    content_summary: str = ""
    token_estimate: int = 0
    last_modified: str = ""

@dataclass
class DataSourceNode:
    ds_id: str
    name: str
    path: str
    schema_type: str = "JSON"
    is_ssot: bool = False
    write_cli: str = ""

@dataclass
class ExternalServiceNode:
    svc_id: str
    name: str
    api_url: str = ""
    auth_type: str = ""

@dataclass
class AgentRelation:
    source_id: str
    source_type: str
    target_id: str
    target_type: str
    relation_type: str
    weight: float = 1.0

# --- Constants ---

BYTES_PER_TOKEN = 3.7

CATEGORY_MAP = {
    "business": "business",
    "communication": "communication",
    "content": "content",
    "infra": "infra",
    "openclaw": "openclaw",
    "personal": "personal",
}

# SSOT data sources (known from Master Data Policy)
SSOT_SOURCES = {
    "tasks.json": "AGENT/task-sync.sh",
    "memos.json": "",
    "schedules.json": "",
    "projects.json": "",
}

KNOWN_SERVICES = [
    ExternalServiceNode("github", "GitHub API", "https://api.github.com", "token"),
    ExternalServiceNode("discord", "Discord API", "https://discord.com/api", "bot_token"),
    ExternalServiceNode("telegram", "Telegram Bot API", "https://api.telegram.org", "bot_token"),
    ExternalServiceNode("anthropic", "Anthropic Claude API", "https://api.anthropic.com", "api_key"),
    ExternalServiceNode("gemini", "Google Gemini API", "https://generativelanguage.googleapis.com", "api_key"),
    ExternalServiceNode("voicevox", "VOICEVOX API", "http://localhost:50021", "none"),
    ExternalServiceNode("openclaw", "OpenClaw Gateway", "wss://aai.tailba4b9d.ts.net", "token"),
    ExternalServiceNode("stripe", "Stripe API", "https://api.stripe.com", "api_key"),
    ExternalServiceNode("teachable", "Teachable API", "https://developers.teachable.com", "api_key"),
    ExternalServiceNode("n8n", "n8n Workflow Engine", "http://localhost:5678", "api_key"),
    ExternalServiceNode("oura", "Oura Ring API", "https://api.ouraring.com", "token"),
]

# --- Parsers ---

def estimate_tokens(file_path: Path) -> int:
    """Estimate token count from file size (FR-002 / 5.3)."""
    try:
        size = file_path.stat().st_size
        return int(size / BYTES_PER_TOKEN)
    except OSError:
        return 0


def parse_yaml_frontmatter(content: str) -> Optional[dict]:
    """Extract YAML frontmatter from markdown content.

    Returns None if no frontmatter or parse error (FR-001-04-A).
    """
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    fm_text = content[3:end].strip()
    # Simple YAML parser (no external dependency)
    result = {}
    current_key = None
    current_list = None
    for line in fm_text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # List item
        if stripped.startswith("- "):
            if current_key and current_list is not None:
                val = stripped[2:].strip().strip('"').strip("'")
                current_list.append(val)
            continue
        # Key-value
        if ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            value = parts[1].strip().strip('"').strip("'")
            current_key = key
            if not value:
                # Start of a list
                current_list = []
                result[key] = current_list
            else:
                current_list = None
                # Handle inline lists: [a, b, c]
                if value.startswith("[") and value.endswith("]"):
                    items = [v.strip().strip('"').strip("'")
                             for v in value[1:-1].split(",") if v.strip()]
                    result[key] = items
                else:
                    result[key] = value
    return result


def parse_agents_md(file_path: Path) -> list[AgentNode]:
    """Parse AGENTS_CLAUDE.md to extract agent definitions (FR-001-01-A).

    The file contains YAML-like structure with agent_id, name, role, etc.
    """
    agents = []
    if not file_path.exists():
        logger.warning("Agents file not found: %s", file_path)
        return agents

    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    current_agent: dict = {}
    in_agent_block = False
    current_list_key = None
    current_list: list[str] = []

    def _flush_agent():
        if current_agent.get("agent_id"):
            # Build keywords from role + name
            kw = current_agent.get("keywords", [])
            if not kw:
                kw = []
                if current_agent.get("name"):
                    kw.append(current_agent["name"])
                if current_agent.get("role"):
                    kw.extend(current_agent["role"].replace("/", " ").split())
            agents.append(AgentNode(
                agent_id=current_agent.get("agent_id", ""),
                name=current_agent.get("name", ""),
                role=current_agent.get("role", ""),
                society=current_agent.get("society", "development"),
                type=current_agent.get("type", "local"),
                emoji=current_agent.get("emoji", ""),
                pane_id=current_agent.get("pane_id", ""),
                keywords=kw,
            ))

    for line in lines:
        stripped = line.strip()

        # Detect agent_id (start of new agent block)
        # Handle both `agent_id: "x"` and `- agent_id: "x"` (YAML list item)
        m = re.match(r'-\s*agent_id:\s*["\']?(\w[\w-]*)["\']?', stripped) or \
            re.match(r'agent_id:\s*["\']?(\w[\w-]*)["\']?', stripped)
        if m:
            # Flush previous
            if current_list_key and current_list:
                current_agent[current_list_key] = current_list
            _flush_agent()
            current_agent = {"agent_id": m.group(1)}
            in_agent_block = True
            current_list_key = None
            current_list = []
            continue

        if not in_agent_block:
            continue

        # Detect section break (non-indented non-empty line that's not a field)
        if stripped and not stripped.startswith("-") and ":" not in stripped:
            if not line.startswith(" ") and not line.startswith("\t"):
                if current_list_key and current_list:
                    current_agent[current_list_key] = current_list
                _flush_agent()
                current_agent = {}
                in_agent_block = False
                current_list_key = None
                current_list = []
                continue

        # Key-value in agent block
        for field_name in ("name", "emoji", "role", "pane", "pane_id",
                           "society", "type", "node_binding"):
            pattern = rf'{field_name}:\s*["\']?(.*?)["\']?\s*$'
            fm = re.match(pattern, stripped)
            if fm:
                current_agent[field_name] = fm.group(1).strip().strip('"').strip("'")
                current_list_key = None
                break

        # Detect list start (e.g., keywords:)
        km = re.match(r'(keywords|responsibilities|capabilities):\s*$', stripped)
        if km:
            current_list_key = km.group(1)
            current_list = []
            continue

        # List item
        if stripped.startswith("- ") and current_list_key:
            val = stripped[2:].strip().strip('"').strip("'")
            current_list.append(val)

    # Flush last
    if current_list_key and current_list:
        current_agent[current_list_key] = current_list
    _flush_agent()

    return agents


def parse_skills(skill_dir: Path, repo_root: Path) -> list[SkillNode]:
    """Parse SKILL/**/*.md files (FR-001-01-B, FR-004).

    Handles both frontmatter-enabled and plain files.
    """
    skills = []
    if not skill_dir.exists():
        logger.warning("SKILL directory not found: %s", skill_dir)
        return skills

    validation_errors = []

    for md_file in sorted(skill_dir.rglob("*.md")):
        # Skip index/catalog files
        if md_file.name in ("README.md", "SKILL_CATALOG.md", "INDEX.md", "_index.md"):
            continue

        rel_path = str(md_file.relative_to(repo_root))
        content = md_file.read_text(encoding="utf-8", errors="replace")

        # Parse frontmatter
        fm = None
        try:
            fm = parse_yaml_frontmatter(content)
        except Exception as e:
            # FR-001-04-A: Skip invalid frontmatter, continue processing
            validation_errors.append(f"  {rel_path}: frontmatter parse error: {e}")

        # Determine category from directory structure
        parent_name = md_file.parent.name
        category = CATEGORY_MAP.get(parent_name, "unknown")
        if category == "unknown" and md_file.parent.parent.name in CATEGORY_MAP:
            category = CATEGORY_MAP[md_file.parent.parent.name]

        # Build skill from frontmatter or filename
        skill_id = md_file.stem
        name = skill_id

        if fm:
            name = fm.get("name", skill_id)
            category = fm.get("category", category)
            keywords = fm.get("keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]
            # Also use triggers as keywords
            triggers = fm.get("triggers", [])
            if isinstance(triggers, str):
                triggers = [triggers]
            keywords = list(set(keywords + triggers))
        else:
            # FR-004-02: No frontmatter — infer from filename
            keywords = [skill_id.replace("-", " ")]
            # Extract first heading as description
            for line in content.split("\n"):
                if line.startswith("# "):
                    name = line[2:].strip()
                    break

        skills.append(SkillNode(
            skill_id=skill_id,
            name=name,
            category=category,
            path=rel_path,
            version=fm.get("version", "") if fm else "",
            priority=fm.get("priority", "") if fm else "",
            description=fm.get("description", "") if fm else "",
            keywords=keywords,
            scripts=fm.get("scripts", []) if fm else [],
            tags=fm.get("tags", []) if fm else [],
            agents=fm.get("agents", []) if fm else [],
            depends_on=fm.get("depends_on", []) if fm else [],
            reads=fm.get("reads", []) if fm else [],
            writes=fm.get("writes", []) if fm else [],
            external_services=fm.get("external_services", []) if fm else [],
        ))

    if validation_errors:
        logger.warning("Frontmatter validation issues (%d):", len(validation_errors))
        for err in validation_errors:
            logger.warning(err)

    return skills


def parse_knowledge(knowledge_dir: Path, repo_root: Path) -> list[KnowledgeDocNode]:
    """Parse KNOWLEDGE/**/*.md files (FR-001-01-C)."""
    docs = []
    if not knowledge_dir.exists():
        logger.warning("KNOWLEDGE directory not found: %s", knowledge_dir)
        return docs

    for md_file in sorted(knowledge_dir.rglob("*.md")):
        if md_file.name in ("README.md", "INDEX.md"):
            continue

        rel_path = str(md_file.relative_to(repo_root))

        # Determine category from parent directory
        parent = md_file.parent.name
        if parent == "KNOWLEDGE":
            category = "root"
        elif parent in ("rules", "skills", "projects", "system",
                         "environment", "knowledgebase", "tmux"):
            category = parent
        else:
            category = parent

        # Get modification time
        try:
            mtime = md_file.stat().st_mtime
            last_modified = time.strftime("%Y-%m-%d", time.localtime(mtime))
        except OSError:
            last_modified = ""

        token_est = estimate_tokens(md_file)

        # Extract first heading as title
        title = md_file.stem
        try:
            first_lines = md_file.read_text(encoding="utf-8", errors="replace").split("\n")[:5]
            for line in first_lines:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        except OSError:
            pass

        docs.append(KnowledgeDocNode(
            doc_id=md_file.stem,
            title=title,
            path=rel_path,
            category=category,
            type="markdown",
            token_estimate=token_est,
            last_modified=last_modified,
        ))

    return docs


def parse_data_sources(data_dir: Path, repo_root: Path) -> list[DataSourceNode]:
    """Parse personal-data/**/*.json files (FR-001-01-D).

    NFR-005-01: Only store path, not file contents.
    """
    sources = []
    if not data_dir.exists():
        logger.warning("personal-data directory not found: %s", data_dir)
        return sources

    for json_file in sorted(data_dir.rglob("*.json")):
        rel_path = str(json_file.relative_to(repo_root))
        name = json_file.name
        ds_id = json_file.stem

        # Make ds_id unique by including parent dirs
        parent_parts = json_file.relative_to(data_dir).parent.parts
        if parent_parts:
            ds_id = "-".join(parent_parts) + "-" + ds_id

        is_ssot = name in SSOT_SOURCES
        write_cli = SSOT_SOURCES.get(name, "")

        sources.append(DataSourceNode(
            ds_id=ds_id,
            name=name,
            path=rel_path,
            schema_type="JSON",
            is_ssot=is_ssot,
            write_cli=write_cli,
        ))

    return sources


# --- Edge Resolution ---

def resolve_edges(
    agents: list[AgentNode],
    skills: list[SkillNode],
    knowledge: list[KnowledgeDocNode],
    data_sources: list[DataSourceNode],
    services: list[ExternalServiceNode],
) -> list[AgentRelation]:
    """Resolve edges between nodes (FR-001-02)."""
    edges: list[AgentRelation] = []
    skill_map = {s.skill_id: s for s in skills}
    knowledge_map = {k.doc_id: k for k in knowledge}
    ds_map = {d.ds_id: d for d in data_sources}
    ds_by_name = {d.name: d for d in data_sources}
    svc_map = {s.svc_id: s for s in services}

    # FR-001-02-A: Agent → Skill (USES_SKILL)
    # From skill frontmatter `agents` field
    for skill in skills:
        for agent_ref in skill.agents:
            # Match by agent_id or name
            matched = None
            for a in agents:
                if agent_ref.lower() in (a.agent_id.lower(), a.name.lower()):
                    matched = a
                    break
            if matched:
                edges.append(AgentRelation(
                    source_id=matched.agent_id,
                    source_type="Agent",
                    target_id=skill.skill_id,
                    target_type="Skill",
                    relation_type="USES_SKILL",
                ))

    # FR-001-02-B: Skill → KnowledgeDoc (DEPENDS_ON)
    for skill in skills:
        for dep in skill.depends_on:
            dep_stem = Path(dep).stem if "/" in dep else dep
            if dep_stem in knowledge_map:
                edges.append(AgentRelation(
                    source_id=skill.skill_id,
                    source_type="Skill",
                    target_id=dep_stem,
                    target_type="KnowledgeDoc",
                    relation_type="DEPENDS_ON",
                ))

    # FR-001-02-C: Skill → DataSource (READS_DATA / WRITES_DATA)
    for skill in skills:
        for read_path in skill.reads:
            name = Path(read_path).name
            ds = ds_by_name.get(name)
            if ds:
                edges.append(AgentRelation(
                    source_id=skill.skill_id,
                    source_type="Skill",
                    target_id=ds.ds_id,
                    target_type="DataSource",
                    relation_type="READS_DATA",
                ))
        for write_path in skill.writes:
            name = Path(write_path).name
            ds = ds_by_name.get(name)
            if ds:
                edges.append(AgentRelation(
                    source_id=skill.skill_id,
                    source_type="Skill",
                    target_id=ds.ds_id,
                    target_type="DataSource",
                    relation_type="WRITES_DATA",
                ))

    # FR-001-02-D: Skill → ExternalService (CALLS_SERVICE)
    for skill in skills:
        for svc_ref in skill.external_services:
            if svc_ref.lower() in svc_map:
                edges.append(AgentRelation(
                    source_id=skill.skill_id,
                    source_type="Skill",
                    target_id=svc_ref.lower(),
                    target_type="ExternalService",
                    relation_type="CALLS_SERVICE",
                ))

    # FR-001-02-E: Skill → Skill (COMPOSES) — inferred from keywords overlap
    # This is lightweight inference: if skill A's name appears in skill B's depends_on
    for skill in skills:
        for dep in skill.depends_on:
            if dep in skill_map and dep != skill.skill_id:
                edges.append(AgentRelation(
                    source_id=skill.skill_id,
                    source_type="Skill",
                    target_id=dep,
                    target_type="Skill",
                    relation_type="COMPOSES",
                ))

    # FR-001-02-F (heuristic): Infer USES_SKILL from agent routing_table / role keywords
    # If no explicit agents field, match skills to agents by category/keyword overlap
    if not any(s.agents for s in skills):
        # Build keyword sets per agent from role text
        agent_keywords: dict[str, set[str]] = {}
        for a in agents:
            kw_set = set()
            for kw in a.keywords:
                kw_set.update(kw.lower().split())
            role_words = a.role.lower().replace("/", " ").replace("-", " ").split()
            kw_set.update(role_words)
            agent_keywords[a.agent_id] = kw_set

        # Category → likely agent mapping (heuristic)
        category_agent_map = {
            "infra": ["kade", "kaede"],
            "business": ["maestro", "conductor"],
            "content": ["nagare", "nagarerrun"],
            "communication": ["maestro", "conductor"],
            "personal": ["maestro", "conductor"],
            "openclaw": ["kade", "kaede"],
        }

        seen_edges: set[tuple[str, str]] = set()
        for skill in skills:
            # Try category-based mapping
            candidate_ids = category_agent_map.get(skill.category, [])
            for cid in candidate_ids:
                for a in agents:
                    if a.agent_id == cid:
                        key = (a.agent_id, skill.skill_id)
                        if key not in seen_edges:
                            edges.append(AgentRelation(
                                source_id=a.agent_id,
                                source_type="Agent",
                                target_id=skill.skill_id,
                                target_type="Skill",
                                relation_type="USES_SKILL",
                                weight=0.5,
                            ))
                            seen_edges.add(key)
                        break

            # Try keyword overlap matching (skill keywords vs agent role keywords)
            skill_kw_set = set()
            for kw in skill.keywords:
                skill_kw_set.update(kw.lower().split())
            skill_kw_set.update(skill.skill_id.lower().replace("-", " ").split())

            for a in agents:
                key = (a.agent_id, skill.skill_id)
                if key in seen_edges:
                    continue
                overlap = skill_kw_set & agent_keywords.get(a.agent_id, set())
                if len(overlap) >= 2:
                    edges.append(AgentRelation(
                        source_id=a.agent_id,
                        source_type="Agent",
                        target_id=skill.skill_id,
                        target_type="Skill",
                        relation_type="USES_SKILL",
                        weight=0.3,
                    ))
                    seen_edges.add(key)

    return edges


# --- Database ---

SCHEMA_SQL = """
-- Node tables
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    emoji TEXT DEFAULT '',
    role TEXT NOT NULL,
    society TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'local',
    pane_id TEXT DEFAULT '',
    node_binding TEXT DEFAULT '',
    keywords TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    path TEXT NOT NULL,
    version TEXT DEFAULT '',
    priority TEXT DEFAULT '',
    description TEXT DEFAULT '',
    keywords TEXT DEFAULT '[]',
    scripts TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS knowledge_docs (
    doc_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    path TEXT NOT NULL,
    category TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'markdown',
    content_summary TEXT DEFAULT '',
    token_estimate INTEGER NOT NULL DEFAULT 0,
    last_modified TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS data_sources (
    ds_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    schema_type TEXT NOT NULL DEFAULT 'JSON',
    is_ssot INTEGER NOT NULL DEFAULT 0,
    write_cli TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS external_services (
    svc_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_url TEXT DEFAULT '',
    auth_type TEXT DEFAULT ''
);

-- Edge table (AgentRelation — completely separate from CodeRelation)
CREATE TABLE IF NOT EXISTS agent_relations (
    relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at TEXT DEFAULT ''
);

-- FTS5 virtual table for keyword search (Phase 2 ready)
-- tokenize=unicode61 handles Japanese text
CREATE VIRTUAL TABLE IF NOT EXISTS agent_fts USING fts5(
    node_id,
    node_type,
    name,
    keywords,
    description,
    tokenize='unicode61'
);

-- Index for edge queries
CREATE INDEX IF NOT EXISTS idx_agent_relations_source
    ON agent_relations(source_id, source_type);
CREATE INDEX IF NOT EXISTS idx_agent_relations_target
    ON agent_relations(target_id, target_type);
CREATE INDEX IF NOT EXISTS idx_agent_relations_type
    ON agent_relations(relation_type);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize Agent Graph SQLite database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def clear_agent_graph(conn: sqlite3.Connection):
    """Clear all Agent Graph data (for full rebuild)."""
    for table in ("agent_fts", "agent_relations", "external_services",
                   "data_sources", "knowledge_docs", "skills", "agents"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def insert_nodes(
    conn: sqlite3.Connection,
    agents: list[AgentNode],
    skills: list[SkillNode],
    knowledge: list[KnowledgeDocNode],
    data_sources: list[DataSourceNode],
    services: list[ExternalServiceNode],
):
    """Insert all nodes into the database."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Agents
    for a in agents:
        conn.execute(
            "INSERT OR REPLACE INTO agents VALUES (?,?,?,?,?,?,?,?,?)",
            (a.agent_id, a.name, a.emoji, a.role, a.society, a.type,
             a.pane_id, a.node_binding, json.dumps(a.keywords, ensure_ascii=False)),
        )
        # FTS5
        conn.execute(
            "INSERT INTO agent_fts VALUES (?,?,?,?,?)",
            (a.agent_id, "Agent", a.name,
             " ".join(a.keywords), a.role),
        )

    # Skills
    for s in skills:
        conn.execute(
            "INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s.skill_id, s.name, s.category, s.path, s.version, s.priority,
             s.description, json.dumps(s.keywords, ensure_ascii=False),
             json.dumps(s.scripts), json.dumps(s.tags)),
        )
        conn.execute(
            "INSERT INTO agent_fts VALUES (?,?,?,?,?)",
            (s.skill_id, "Skill", s.name,
             " ".join(s.keywords), s.description),
        )

    # Knowledge
    for k in knowledge:
        conn.execute(
            "INSERT OR REPLACE INTO knowledge_docs VALUES (?,?,?,?,?,?,?,?)",
            (k.doc_id, k.title, k.path, k.category, k.type,
             k.content_summary, k.token_estimate, k.last_modified),
        )
        conn.execute(
            "INSERT INTO agent_fts VALUES (?,?,?,?,?)",
            (k.doc_id, "KnowledgeDoc", k.title, "", ""),
        )

    # DataSources
    for d in data_sources:
        conn.execute(
            "INSERT OR REPLACE INTO data_sources VALUES (?,?,?,?,?,?)",
            (d.ds_id, d.name, d.path, d.schema_type,
             1 if d.is_ssot else 0, d.write_cli),
        )

    # External Services
    for svc in services:
        conn.execute(
            "INSERT OR REPLACE INTO external_services VALUES (?,?,?,?)",
            (svc.svc_id, svc.name, svc.api_url, svc.auth_type),
        )

    conn.commit()


def insert_edges(conn: sqlite3.Connection, edges: list[AgentRelation]):
    """Insert all edges into the database."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    for e in edges:
        conn.execute(
            "INSERT INTO agent_relations "
            "(source_id, source_type, target_id, target_type, relation_type, weight, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (e.source_id, e.source_type, e.target_id, e.target_type,
             e.relation_type, e.weight, ts),
        )
    conn.commit()


# --- Main Builder ---

def build_agent_graph(
    repo_root: Path,
    db_path: Path,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Build the complete Agent Context Graph.

    Returns a statistics dict.
    """
    start_time = time.time()

    # Locate source directories
    agents_file = repo_root / "KNOWLEDGE" / "AGENTS_CLAUDE.md"
    if not agents_file.exists():
        # Fallback: try parent workspace CLAUDE.md
        alt = repo_root.parent / ".claude" / "CLAUDE.md"
        if alt.exists():
            agents_file = alt

    skill_dir = repo_root / "SKILL"
    knowledge_dir = repo_root / "KNOWLEDGE"
    data_dir = repo_root / "personal-data"

    # Parse all sources
    logger.info("Parsing agents from %s", agents_file)
    agents = parse_agents_md(agents_file)
    logger.info("  -> %d agents", len(agents))

    logger.info("Parsing skills from %s", skill_dir)
    skills = parse_skills(skill_dir, repo_root)
    logger.info("  -> %d skills", len(skills))

    logger.info("Parsing knowledge from %s", knowledge_dir)
    knowledge = parse_knowledge(knowledge_dir, repo_root)
    logger.info("  -> %d knowledge docs", len(knowledge))

    logger.info("Parsing data sources from %s", data_dir)
    data_sources = parse_data_sources(data_dir, repo_root)
    logger.info("  -> %d data sources", len(data_sources))

    services = KNOWN_SERVICES.copy()
    logger.info("  -> %d external services (known)", len(services))

    # Resolve edges
    logger.info("Resolving edges...")
    edges = resolve_edges(agents, skills, knowledge, data_sources, services)
    logger.info("  -> %d edges", len(edges))

    # Statistics
    total_nodes = len(agents) + len(skills) + len(knowledge) + len(data_sources) + len(services)
    stats = {
        "agents": len(agents),
        "skills": len(skills),
        "knowledge_docs": len(knowledge),
        "data_sources": len(data_sources),
        "external_services": len(services),
        "total_nodes": total_nodes,
        "edges": len(edges),
        "edge_types": {},
        "execution_time_ms": 0,
        "db_path": str(db_path),
    }

    # Count edge types
    for e in edges:
        stats["edge_types"][e.relation_type] = stats["edge_types"].get(e.relation_type, 0) + 1

    if dry_run:
        logger.info("DRY RUN — no database changes")
        stats["dry_run"] = True
        stats["execution_time_ms"] = int((time.time() - start_time) * 1000)
        return stats

    # Build database
    logger.info("Building database at %s", db_path)
    conn = init_db(db_path)

    if force:
        logger.info("Force mode: clearing existing data")
        clear_agent_graph(conn)

    try:
        insert_nodes(conn, agents, skills, knowledge, data_sources, services)
        insert_edges(conn, edges)
    finally:
        conn.close()

    stats["execution_time_ms"] = int((time.time() - start_time) * 1000)
    logger.info("Build complete in %dms", stats["execution_time_ms"])
    return stats


def get_agent_graph_stats(db_path: Path) -> dict:
    """Get statistics from existing Agent Graph database."""
    if not db_path.exists():
        return {"error": "Database not found", "db_path": str(db_path)}

    conn = sqlite3.connect(str(db_path))
    stats = {}
    for table, label in [("agents", "agents"), ("skills", "skills"),
                          ("knowledge_docs", "knowledge_docs"),
                          ("data_sources", "data_sources"),
                          ("external_services", "external_services")]:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        stats[label] = row[0] if row else 0

    row = conn.execute("SELECT COUNT(*) FROM agent_relations").fetchone()
    stats["edges"] = row[0] if row else 0
    stats["total_nodes"] = sum(stats[k] for k in
                                ("agents", "skills", "knowledge_docs",
                                 "data_sources", "external_services"))

    # Edge type breakdown
    rows = conn.execute(
        "SELECT relation_type, COUNT(*) FROM agent_relations GROUP BY relation_type"
    ).fetchall()
    stats["edge_types"] = {r[0]: r[1] for r in rows}

    conn.close()
    stats["db_path"] = str(db_path)
    return stats


def list_agents_and_skills(db_path: Path) -> dict:
    """List all agents and their skills."""
    if not db_path.exists():
        return {"error": "Database not found"}

    conn = sqlite3.connect(str(db_path))
    agents = []
    for row in conn.execute("SELECT agent_id, name, emoji, role, society FROM agents ORDER BY agent_id"):
        agent = {"agent_id": row[0], "name": row[1], "emoji": row[2],
                 "role": row[3], "society": row[4], "skills": []}
        # Get linked skills
        skill_rows = conn.execute(
            "SELECT ar.target_id, s.name, s.category FROM agent_relations ar "
            "JOIN skills s ON ar.target_id = s.skill_id "
            "WHERE ar.source_id = ? AND ar.relation_type = 'USES_SKILL'",
            (row[0],)
        ).fetchall()
        agent["skills"] = [{"skill_id": sr[0], "name": sr[1], "category": sr[2]}
                           for sr in skill_rows]
        agents.append(agent)

    skills_without_agent = conn.execute(
        "SELECT s.skill_id, s.name, s.category FROM skills s "
        "WHERE s.skill_id NOT IN ("
        "  SELECT target_id FROM agent_relations WHERE relation_type = 'USES_SKILL'"
        ") ORDER BY s.category, s.skill_id"
    ).fetchall()

    conn.close()
    return {
        "agents": agents,
        "unbound_skills": [{"skill_id": r[0], "name": r[1], "category": r[2]}
                           for r in skills_without_agent],
    }


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(
        description="Agent Graph Builder — Build Agent Context Graph for GitNexus"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # build
    build_cmd = sub.add_parser("build", help="Build Agent Graph index")
    build_cmd.add_argument("repo", type=Path, help="Repository root path")
    build_cmd.add_argument("--db", type=Path, default=None,
                           help="Database path (default: REPO/.gitnexus/agent-graph.db)")
    build_cmd.add_argument("--dry-run", action="store_true", help="Parse only, no DB write")
    build_cmd.add_argument("--force", action="store_true", help="Clear existing data before build")
    build_cmd.add_argument("--json", action="store_true", help="Output stats as JSON")

    # status
    status_cmd = sub.add_parser("status", help="Show Agent Graph statistics")
    status_cmd.add_argument("repo", type=Path, help="Repository root path")
    status_cmd.add_argument("--db", type=Path, default=None)
    status_cmd.add_argument("--json", action="store_true")

    # list
    list_cmd = sub.add_parser("list", help="List agents and skills")
    list_cmd.add_argument("repo", type=Path, help="Repository root path")
    list_cmd.add_argument("--db", type=Path, default=None)
    list_cmd.add_argument("--json", action="store_true")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if os.environ.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    repo_root = args.repo.resolve()
    db_path = args.db or (repo_root / ".gitnexus" / "agent-graph.db")

    if args.command == "build":
        stats = build_agent_graph(repo_root, db_path,
                                   dry_run=args.dry_run, force=args.force)
        if args.json:
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        else:
            print(f"\n{'='*50}")
            print(f"Agent Graph Build {'(DRY RUN) ' if args.dry_run else ''}Complete")
            print(f"{'='*50}")
            print(f"  Agents:           {stats['agents']}")
            print(f"  Skills:           {stats['skills']}")
            print(f"  Knowledge Docs:   {stats['knowledge_docs']}")
            print(f"  Data Sources:     {stats['data_sources']}")
            print(f"  External Services:{stats['external_services']}")
            print(f"  Total Nodes:      {stats['total_nodes']}")
            print(f"  Edges:            {stats['edges']}")
            if stats.get("edge_types"):
                print(f"  Edge Types:")
                for et, count in sorted(stats["edge_types"].items()):
                    print(f"    {et}: {count}")
            print(f"  Time:             {stats['execution_time_ms']}ms")
            print(f"  DB:               {stats['db_path']}")

    elif args.command == "status":
        stats = get_agent_graph_stats(db_path)
        if args.json:
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        else:
            if "error" in stats:
                print(f"Error: {stats['error']}")
                sys.exit(1)
            print(f"\nAgent Graph Status")
            print(f"{'='*40}")
            print(f"  Agents:           {stats.get('agents', 0)}")
            print(f"  Skills:           {stats.get('skills', 0)}")
            print(f"  Knowledge Docs:   {stats.get('knowledge_docs', 0)}")
            print(f"  Data Sources:     {stats.get('data_sources', 0)}")
            print(f"  External Services:{stats.get('external_services', 0)}")
            print(f"  Total Nodes:      {stats.get('total_nodes', 0)}")
            print(f"  Edges:            {stats.get('edges', 0)}")
            if stats.get("edge_types"):
                print(f"  Edge Types:")
                for et, count in sorted(stats["edge_types"].items()):
                    print(f"    {et}: {count}")

    elif args.command == "list":
        data = list_agents_and_skills(db_path)
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            if "error" in data:
                print(f"Error: {data['error']}")
                sys.exit(1)
            print(f"\nAgents ({len(data['agents'])})")
            print(f"{'='*60}")
            for a in data["agents"]:
                skills_str = ", ".join(s["skill_id"] for s in a["skills"]) or "(none)"
                print(f"  {a.get('emoji','')} {a['name']} ({a['agent_id']}) — {a['role']}")
                print(f"    Skills: {skills_str}")
            if data.get("unbound_skills"):
                print(f"\nUnbound Skills ({len(data['unbound_skills'])})")
                print(f"{'-'*60}")
                for s in data["unbound_skills"]:
                    print(f"  [{s['category']}] {s['skill_id']} — {s['name']}")


if __name__ == "__main__":
    main()
