#!/usr/bin/env python3
"""
MCP Server for Agent Context Graph — Phase 4

Exposes `agent_context` as an MCP tool via JSON-RPC over stdio.
Designed for Claude Code's mcpServers configuration.

Usage in Claude Code settings.json:
    {
      "mcpServers": {
        "gitnexus-agent": {
          "command": "python3",
          "args": ["/path/to/gitnexus-stable-ops/lib/mcp_server.py"],
          "env": { "GITNEXUS_AGENT_REPO": "/path/to/HAYASHI_SHUNSUKE" }
        }
      }
    }

Protocol: MCP (Model Context Protocol) over stdio
  - JSON-RPC 2.0 messages on stdin/stdout
  - Newline-delimited JSON
"""

import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Import context_resolver from the same lib/ directory
sys.path.insert(0, str(Path(__file__).parent))
from context_resolver import assemble_context, format_markdown, ContextResult

logger = logging.getLogger("mcp-agent-context")

# ----- MCP Protocol Constants -----

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "gitnexus-agent-context"
SERVER_VERSION = "1.0.0"

# ----- Tool Definition -----

TOOL_AGENT_CONTEXT = {
    "name": "gitnexus_agent_context",
    "description": (
        "Resolve a natural-language task query to relevant Agent Graph nodes. "
        "Returns matched agents, skills, files to read, and token estimates. "
        "Use this BEFORE reading context files to minimize token usage. "
        "Average savings: 93% of context window."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language task description (e.g., '定款を修正して', 'add health tracking')",
            },
            "agent": {
                "type": "string",
                "description": "Direct agent lookup by name (optional, overrides query)",
            },
            "skill": {
                "type": "string",
                "description": "Direct skill lookup by name (optional, overrides query)",
            },
            "depth": {
                "type": "integer",
                "description": "Graph traversal depth (default: 2, max: 5)",
                "default": 2,
            },
            "max_tokens": {
                "type": "integer",
                "description": "Token budget for returned context (default: 5000)",
                "default": 5000,
            },
            "task_type": {
                "type": "string",
                "enum": ["bugfix", "feature", "refactor"],
                "description": "Task type for scoring adjustment (optional)",
            },
            "format": {
                "type": "string",
                "enum": ["json", "markdown"],
                "description": "Output format (default: json)",
                "default": "json",
            },
        },
        "required": ["query"],
    },
}

TOOL_AGENT_STATUS = {
    "name": "gitnexus_agent_status",
    "description": (
        "Show Agent Graph statistics: node counts by type, edge counts, "
        "and index freshness. Use this to check if the agent graph is healthy."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
    },
}

TOOL_AGENT_LIST = {
    "name": "gitnexus_agent_list",
    "description": (
        "List all agents and skills in the Agent Graph. "
        "Returns agent names, roles, and their associated skills."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "node_type": {
                "type": "string",
                "enum": ["Agent", "Skill", "KnowledgeDoc", "DataSource", "ExternalService"],
                "description": "Filter by node type (optional, lists all if omitted)",
            },
        },
    },
}

ALL_TOOLS = [TOOL_AGENT_CONTEXT, TOOL_AGENT_STATUS, TOOL_AGENT_LIST]


# ----- Helper Functions -----

def _resolve_paths():
    """Resolve repo root and database path from environment."""
    repo_root = os.environ.get("GITNEXUS_AGENT_REPO", os.getcwd())
    repo_root = Path(repo_root).resolve()

    db_path = os.environ.get("GITNEXUS_AGENT_DB")
    if db_path:
        db_path = Path(db_path)
    else:
        db_path = repo_root / ".gitnexus" / "agent-graph.db"

    return repo_root, db_path


def _context_result_to_dict(result: ContextResult) -> dict:
    """Convert ContextResult dataclass to serializable dict."""
    return {
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


def _db_stats(conn: sqlite3.Connection) -> dict:
    """Get Agent Graph statistics."""
    stats = {"nodes": {}, "edges": {}, "total_nodes": 0, "total_edges": 0}

    # Node counts by type — use actual table names from agent_graph_builder.py
    table_type_map = {
        "agents": "Agent",
        "skills": "Skill",
        "knowledge_docs": "KnowledgeDoc",
        "data_sources": "DataSource",
        "external_services": "ExternalService",
    }

    for table, node_type in table_type_map.items():
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            count = row[0] if row else 0
            if count > 0:
                stats["nodes"][node_type] = count
                stats["total_nodes"] += count
        except sqlite3.OperationalError:
            pass

    if stats["total_nodes"] == 0:
        stats["error"] = "No agent graph tables found"
        return stats

    # Edge counts by type
    try:
        for row in conn.execute(
            "SELECT relation_type, COUNT(*) FROM agent_relations GROUP BY relation_type"
        ):
            stats["edges"][row[0]] = row[1]
            stats["total_edges"] += row[1]
    except sqlite3.OperationalError:
        pass

    # DB file size
    repo_root, db_path = _resolve_paths()
    if db_path.exists():
        stats["db_size_kb"] = round(db_path.stat().st_size / 1024, 1)

    return stats


def _list_nodes(conn: sqlite3.Connection, node_type: str = None) -> list:
    """List nodes, optionally filtered by type."""
    nodes = []

    # Map node_type filter to actual table queries
    table_queries = {
        "Agent": ("agents", "agent_id", "name", "''"),
        "Skill": ("skills", "skill_id", "name", "path"),
        "KnowledgeDoc": ("knowledge_docs", "doc_id", "title", "path"),
        "DataSource": ("data_sources", "ds_id", "name", "path"),
        "ExternalService": ("external_services", "svc_id", "name", "''"),
    }

    targets = {node_type: table_queries[node_type]} if node_type and node_type in table_queries else table_queries

    for ntype, (table, id_col, name_col, path_col) in targets.items():
        try:
            sql = f"SELECT {id_col}, {name_col}, {path_col} FROM {table} ORDER BY {name_col}"
            for row in conn.execute(sql).fetchall():
                nodes.append({
                    "node_id": row[0],
                    "node_type": ntype,
                    "name": row[1],
                    "path": row[2] if row[2] else None,
                })
        except sqlite3.OperationalError:
            pass

    return nodes


# ----- MCP Protocol Handlers -----

def handle_initialize(params: dict) -> dict:
    """Handle initialize request."""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    }


def handle_tools_list(params: dict) -> dict:
    """Handle tools/list request."""
    return {"tools": ALL_TOOLS}


def handle_tools_call(params: dict) -> dict:
    """Handle tools/call request."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    repo_root, db_path = _resolve_paths()

    if not db_path.exists():
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "error": f"Agent Graph not found at {db_path}. Run: gni agent-index {repo_root}",
                }, ensure_ascii=False),
            }],
            "isError": True,
        }

    conn = sqlite3.connect(str(db_path))
    try:
        if tool_name == "gitnexus_agent_context":
            return _handle_agent_context(conn, arguments, repo_root)
        elif tool_name == "gitnexus_agent_status":
            return _handle_agent_status(conn)
        elif tool_name == "gitnexus_agent_list":
            return _handle_agent_list(conn, arguments)
        else:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"error": f"Unknown tool: {tool_name}"}),
                }],
                "isError": True,
            }
    finally:
        conn.close()


def _handle_agent_context(conn, arguments, repo_root):
    """Execute agent_context tool."""
    query = arguments.get("query", "")
    agent_name = arguments.get("agent")
    skill_name = arguments.get("skill")
    depth = min(arguments.get("depth", 2), 5)  # Cap at 5
    max_tokens = arguments.get("max_tokens", 5000)
    task_type = arguments.get("task_type")
    output_format = arguments.get("format", "json")

    if not query and not agent_name and not skill_name:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "error": "At least one of 'query', 'agent', or 'skill' is required",
                }),
            }],
            "isError": True,
        }

    result = assemble_context(
        conn=conn,
        query=query,
        agent_name=agent_name,
        skill_name=skill_name,
        depth=depth,
        max_tokens=max_tokens,
        task_type=task_type,
        repo_root=repo_root,
    )

    if output_format == "markdown":
        text = format_markdown(result)
    else:
        text = json.dumps(_context_result_to_dict(result), indent=2, ensure_ascii=False)

    return {
        "content": [{
            "type": "text",
            "text": text,
        }],
    }


def _handle_agent_status(conn):
    """Execute agent_status tool."""
    stats = _db_stats(conn)
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(stats, indent=2, ensure_ascii=False),
        }],
    }


def _handle_agent_list(conn, arguments):
    """Execute agent_list tool."""
    node_type = arguments.get("node_type")
    nodes = _list_nodes(conn, node_type)
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(nodes, indent=2, ensure_ascii=False),
        }],
    }


# ----- Main Event Loop -----

def send_response(response_id, result):
    """Send JSON-RPC response to stdout."""
    response = {
        "jsonrpc": "2.0",
        "id": response_id,
        "result": result,
    }
    msg = json.dumps(response, ensure_ascii=False)
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def send_error(response_id, code, message):
    """Send JSON-RPC error to stdout."""
    response = {
        "jsonrpc": "2.0",
        "id": response_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    msg = json.dumps(response, ensure_ascii=False)
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def main():
    """MCP server main loop — reads JSON-RPC from stdin, writes to stdout."""
    log_level = logging.DEBUG if os.environ.get("DEBUG") else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,  # Logs go to stderr, protocol goes to stdout
    )

    logger.info("MCP Agent Context server starting")
    logger.info("Repo: %s", os.environ.get("GITNEXUS_AGENT_REPO", "(CWD)"))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            send_error(None, -32700, f"Parse error: {e}")
            continue

        request_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        logger.debug("Request: method=%s id=%s", method, request_id)

        try:
            if method == "initialize":
                result = handle_initialize(params)
                send_response(request_id, result)
            elif method == "notifications/initialized":
                # Client notification — no response needed
                pass
            elif method == "tools/list":
                result = handle_tools_list(params)
                send_response(request_id, result)
            elif method == "tools/call":
                result = handle_tools_call(params)
                send_response(request_id, result)
            elif method == "ping":
                send_response(request_id, {})
            else:
                send_error(request_id, -32601, f"Method not found: {method}")
        except Exception as e:
            logger.exception("Error handling %s", method)
            send_error(request_id, -32603, str(e))


if __name__ == "__main__":
    main()
