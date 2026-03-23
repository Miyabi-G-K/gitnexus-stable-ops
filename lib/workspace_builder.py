#!/usr/bin/env python3
"""
Workspace Builder — Phase 1 Workspace Graph
Reads .gitnexus/workspace.json and orchestrates cross-repo,
cross-symlink analysis for agent-aware workspaces.

Schema v1.1: generalized nodes/services model (tool-agnostic).
Backwards compatible with v1.0 machines/agents schema.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("workspace-builder")


# ---------------------------------------------------------------------------
# Data classes — v1.1 generalized schema
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceNodeAccess:
    """Tool-agnostic connection descriptor for a compute node."""
    type: str                       # "local" | "ssh" | "http" | "custom"
    host: Optional[str] = None      # SSH hostname / HTTP hostname
    port: Optional[int] = None      # Port (optional)
    user: Optional[str] = None      # Login user (optional)


@dataclass
class WorkspaceNodeNetwork:
    """Network information for a compute node."""
    ip: Optional[str] = None        # Private IP / VPN IP / public IP
    labels: dict = field(default_factory=dict)  # e.g. {"vpn": "tailscale"}


@dataclass
class WorkspaceNode:
    """A compute resource: PC, VM, container, cloud instance, etc."""
    id: str                         # Unique identifier (referenced by services)
    name: str                       # Display name
    role: str                       # "gateway" | "primary" | "worker" | any
    os: str                         # "linux" | "macos" | "windows"
    description: str = ""
    access: Optional[WorkspaceNodeAccess] = None
    network: Optional[WorkspaceNodeNetwork] = None
    workspace_root: Optional[str] = None
    services: list[str] = field(default_factory=list)  # service IDs on this node
    labels: dict = field(default_factory=dict)          # free metadata


@dataclass
class WorkspaceService:
    """A service running on a node: agent, server, database, worker, etc."""
    id: str
    name: str
    type: str                       # "agent" | "server" | "database" | "worker"
    node: Optional[str] = None      # node id
    description: str = ""
    knowledge_refs: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    skill_refs: list[str] = field(default_factory=list)
    labels: dict = field(default_factory=dict)


@dataclass
class WorkspaceSymlink:
    name: str
    resolved: str
    description: str = ""
    index: bool = True
    register_as: Optional[str] = None


@dataclass
class WorkspaceSubRepo:
    name: str
    path: str
    auto_index: bool = False


@dataclass
class WorkspaceManifest:
    version: str
    workspace_root: str
    description: str = ""
    symlinks: list[WorkspaceSymlink] = field(default_factory=list)
    sub_repos: list[WorkspaceSubRepo] = field(default_factory=list)
    nodes: list[WorkspaceNode] = field(default_factory=list)
    services: list[WorkspaceService] = field(default_factory=list)
    cluster: dict = field(default_factory=dict)
    # Legacy field aliases (kept for render helpers)
    knowledge_refs: dict = field(default_factory=dict)
    index_policy: dict = field(default_factory=dict)


@dataclass
class WorkspaceStatus:
    workspace_root: str
    workspace_path: str
    manifest_found: bool
    symlinks: list[dict] = field(default_factory=list)
    sub_repos: list[dict] = field(default_factory=list)
    nodes: list[dict] = field(default_factory=list)
    indexed_repos: list[str] = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0


# ---------------------------------------------------------------------------
# Schema migration helpers (v1.0 machines → v1.1 nodes/services)
# ---------------------------------------------------------------------------

def _migrate_machines_to_nodes(data: dict) -> dict:
    """
    Convert v1.0 'machines' schema to v1.1 'nodes'+'services' schema.
    This allows backwards compatibility with old workspace.json files.
    """
    if "machines" not in data:
        return data

    nodes: list[dict] = []
    services: list[dict] = []
    existing_service_ids: set[str] = {s["id"] for s in data.get("services", [])}

    for m in data["machines"]:
        node_id = m.get("name", "").replace(" ", "-").lower()

        # Build access object
        ssh_host = m.get("ssh_host")
        access = {"type": "ssh", "host": ssh_host} if ssh_host else {"type": "local"}

        # Build network object — move tailscale_ip into network.ip + labels
        network: dict = {}
        if m.get("tailscale_ip"):
            network["ip"] = m["tailscale_ip"]
            network["labels"] = {"vpn": "tailscale"}

        # Move tool-specific versions into labels
        labels: dict = {}
        if m.get("node_version"):
            labels["node_version"] = m["node_version"]
        if m.get("openclaw_version"):
            labels["openclaw_version"] = m["openclaw_version"]

        agent_ids = m.get("agents", [])

        node: dict = {
            "id": node_id,
            "name": m.get("description", m.get("name", node_id)),
            "role": m.get("role", "worker"),
            "os": m.get("os", "linux"),
            "description": m.get("description", ""),
            "access": access,
            "services": agent_ids,
        }
        if network:
            node["network"] = network
        if m.get("workspace_root"):
            node["workspace_root"] = m["workspace_root"]
        if labels:
            node["labels"] = labels

        nodes.append(node)

        # Create minimal service entries for agents not already defined
        for agent_id in agent_ids:
            if agent_id not in existing_service_ids:
                services.append({
                    "id": agent_id,
                    "name": agent_id,
                    "type": "agent",
                    "node": node_id,
                })
                existing_service_ids.add(agent_id)

    # Migrate cluster section
    cluster = dict(data.get("cluster", {}))
    if cluster:
        cluster_labels: dict = cluster.pop("labels", {})
        for key in ("tailnet", "gateway_url", "openclaw_version", "network"):
            if key in cluster:
                cluster_labels[key] = cluster.pop(key)
        if cluster_labels:
            cluster["labels"] = cluster_labels
        # Map total_agents → total_services
        if "total_agents" in cluster:
            cluster.setdefault("total_services", cluster.pop("total_agents"))

    result = {k: v for k, v in data.items() if k not in ("machines", "cluster")}
    result["nodes"] = nodes
    result["services"] = data.get("services", []) + services
    if cluster:
        result["cluster"] = cluster
    return result


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

def _parse_node(raw: dict) -> WorkspaceNode:
    access_raw = raw.get("access")
    access = WorkspaceNodeAccess(**access_raw) if access_raw else None

    network_raw = raw.get("network")
    network = WorkspaceNodeNetwork(**network_raw) if network_raw else None

    return WorkspaceNode(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        role=raw.get("role", "worker"),
        os=raw.get("os", "linux"),
        description=raw.get("description", ""),
        access=access,
        network=network,
        workspace_root=raw.get("workspace_root"),
        services=raw.get("services", []),
        labels=raw.get("labels", {}),
    )


def _parse_service(raw: dict) -> WorkspaceService:
    return WorkspaceService(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        type=raw.get("type", "agent"),
        node=raw.get("node"),
        description=raw.get("description", ""),
        knowledge_refs=raw.get("knowledge_refs", []),
        memory_refs=raw.get("memory_refs", []),
        skill_refs=raw.get("skill_refs", []),
        labels=raw.get("labels", {}),
    )


def load_manifest(repo_path: str | Path) -> Optional[WorkspaceManifest]:
    """Load .gitnexus/workspace.json from a repo path (v1.1 or v1.0)."""
    manifest_path = Path(repo_path) / ".gitnexus" / "workspace.json"
    if not manifest_path.exists():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Auto-migrate v1.0 machines schema to v1.1 nodes/services
        if "machines" in raw:
            raw = _migrate_machines_to_nodes(raw)

        symlinks = [WorkspaceSymlink(**s) for s in raw.get("symlinks", [])]
        sub_repos = [WorkspaceSubRepo(**r) for r in raw.get("sub_repos", [])]
        nodes = [_parse_node(n) for n in raw.get("nodes", [])]
        services = [_parse_service(s) for s in raw.get("services", [])]

        return WorkspaceManifest(
            version=raw.get("version", "1.0"),
            workspace_root=raw.get("workspace_root", ""),
            description=raw.get("description", ""),
            symlinks=symlinks,
            sub_repos=sub_repos,
            nodes=nodes,
            services=services,
            cluster=raw.get("cluster", {}),
            knowledge_refs=raw.get("knowledge_refs", {}),
            index_policy=raw.get("index_policy", {}),
        )
    except Exception as e:
        logger.error(f"Failed to load workspace manifest: {e}")
        return None


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

GITNEXUS_BIN = os.environ.get(
    "GITNEXUS_BIN",
    os.path.expanduser("~/.local/bin/gitnexus-stable"),
)
if not os.path.exists(GITNEXUS_BIN):
    GITNEXUS_BIN = "gitnexus"


def _has_embeddings(repo_path: str | Path) -> bool:
    meta = Path(repo_path) / ".gitnexus" / "meta.json"
    if not meta.exists():
        return False
    try:
        data = json.loads(meta.read_text())
        return int(data.get("stats", {}).get("embeddings", 0) or 0) > 0
    except Exception:
        return False


def _analyze_repo(repo_path: str | Path, force: bool = True) -> bool:
    """Run gitnexus analyze on a directory."""
    rp = Path(repo_path)
    if not rp.is_dir():
        logger.warning(f"Target not a directory (skipping): {rp}")
        return False

    args = [GITNEXUS_BIN, "analyze"]
    if force:
        args.append("--force")
    if _has_embeddings(rp):
        args.append("--embeddings")

    logger.info(f"  Analyzing: {rp}")
    try:
        result = subprocess.run(
            args,
            cwd=str(rp),
            capture_output=False,
            timeout=300,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"  Timeout analyzing {rp}")
        return False
    except Exception as e:
        logger.error(f"  Error analyzing {rp}: {e}")
        return False


def _get_registry() -> dict:
    """Load ~/.gitnexus/registry.json"""
    registry_path = Path.home() / ".gitnexus" / "registry.json"
    if not registry_path.exists():
        return {}
    try:
        return json.loads(registry_path.read_text())
    except Exception:
        return {}


def _repo_meta(repo_path: str | Path) -> dict:
    meta = Path(repo_path) / ".gitnexus" / "meta.json"
    if not meta.exists():
        return {}
    try:
        return json.loads(meta.read_text())
    except Exception:
        return {}


def _node_display_name(node: WorkspaceNode) -> str:
    """Get a concise display identifier for a node."""
    if node.access:
        if node.access.type == "ssh" and node.access.host:
            return node.access.host
        if node.access.type == "local":
            return "(local)"
        if node.access.type == "http" and node.access.host:
            return node.access.host
    return node.id


def _node_ip(node: WorkspaceNode) -> str:
    """Get IP string for display."""
    if node.network and node.network.ip:
        return node.network.ip
    return ""


# ---------------------------------------------------------------------------
# Workspace commands
# ---------------------------------------------------------------------------

def cmd_status(repo_path_str: str, as_json: bool = False) -> int:
    """Show workspace structure and index status."""
    repo_path = Path(repo_path_str).resolve()
    manifest = load_manifest(repo_path)

    registry = _get_registry()
    indexed = set(registry.keys()) if isinstance(registry, dict) else set()

    status = WorkspaceStatus(
        workspace_root=manifest.workspace_root if manifest else repo_path.name,
        workspace_path=str(repo_path),
        manifest_found=manifest is not None,
    )

    if manifest:
        for sl in manifest.symlinks:
            resolved = Path(sl.resolved).expanduser()
            is_accessible = resolved.is_dir()
            is_indexed = sl.register_as in indexed if sl.register_as else False
            meta = _repo_meta(resolved) if is_accessible and sl.index else {}
            status.symlinks.append({
                "name": sl.name,
                "resolved": str(resolved),
                "accessible": is_accessible,
                "index": sl.index,
                "indexed": is_indexed,
                "nodes": meta.get("stats", {}).get("nodes", 0),
                "edges": meta.get("stats", {}).get("edges", 0),
            })
            if is_indexed:
                status.total_nodes += meta.get("stats", {}).get("nodes", 0)
                status.total_edges += meta.get("stats", {}).get("edges", 0)

        for sr in manifest.sub_repos:
            sr_path = repo_path / sr.path
            is_accessible = sr_path.is_dir()
            is_git = (sr_path / ".git").is_dir()
            is_indexed = sr.name in indexed
            meta = _repo_meta(sr_path) if is_accessible else {}
            status.sub_repos.append({
                "name": sr.name,
                "path": sr.path,
                "accessible": is_accessible,
                "is_git_repo": is_git,
                "auto_index": sr.auto_index,
                "indexed": is_indexed,
                "nodes": meta.get("stats", {}).get("nodes", 0),
            })

        # Build service lookup
        service_map: dict[str, WorkspaceService] = {s.id: s for s in manifest.services}

        for n in manifest.nodes:
            svc_count = len(n.services)
            ip = _node_ip(n)
            access_str = _node_display_name(n)
            status.nodes.append({
                "id": n.id,
                "name": n.name,
                "role": n.role,
                "os": n.os,
                "description": n.description,
                "access": access_str,
                "ip": ip,
                "workspace_root": n.workspace_root,
                "service_count": svc_count,
                "services": n.services,
                "labels": n.labels,
            })

    # Add main workspace stats
    main_meta = _repo_meta(repo_path)
    status.total_nodes += main_meta.get("stats", {}).get("nodes", 0)
    status.total_edges += main_meta.get("stats", {}).get("edges", 0)

    if as_json:
        print(json.dumps(asdict(status), indent=2, ensure_ascii=False))
        return 0

    # Human-readable output
    print(f"\n{'='*60}")
    print(f"  Workspace: {status.workspace_root}")
    print(f"  Path:      {status.workspace_path}")
    print(f"  Manifest:  {'✓ Found' if status.manifest_found else '✗ Not found (.gitnexus/workspace.json)'}")
    if manifest and manifest.version:
        print(f"  Schema:    v{manifest.version}")
    print(f"{'='*60}")

    main_nodes_count = main_meta.get("stats", {}).get("nodes", 0)
    main_edges_count = main_meta.get("stats", {}).get("edges", 0)
    main_indexed = repo_path.name in indexed or (repo_path / ".gitnexus" / "meta.json").exists()
    print(f"\n  [Main Repo]")
    print(f"    {repo_path.name:30s}  {'✓' if main_indexed else '○'}  {main_nodes_count:6d} nodes  {main_edges_count:6d} edges")

    if status.symlinks:
        print(f"\n  [Symlinks]")
        for sl in status.symlinks:
            idx_mark = "✓" if sl["indexed"] else ("○" if sl["index"] else "—")
            acc_mark = "✓" if sl["accessible"] else "✗"
            nodes = sl["nodes"] if sl["nodes"] else "—"
            print(f"    {sl['name']:30s}  {idx_mark}  acc:{acc_mark}  {str(nodes):>6} nodes")
            print(f"    {'':30s}     → {sl['resolved']}")

    if status.sub_repos:
        print(f"\n  [Sub-repos]")
        for sr in status.sub_repos:
            idx_mark = "✓" if sr["indexed"] else ("○" if sr["auto_index"] else "—")
            git_mark = "git" if sr["is_git_repo"] else "dir"
            nodes = sr["nodes"] if sr["nodes"] else "—"
            print(f"    {sr['name']:30s}  {idx_mark}  [{git_mark}]  {str(nodes):>6} nodes")

    if status.nodes:
        total_svcs = sum(n["service_count"] for n in status.nodes)
        print(f"\n  [Nodes] ({len(status.nodes)} nodes, {total_svcs} services)")
        role_icons = {"gateway": "🌐", "worker": "⚙️", "primary": "💻"}
        os_icons = {"windows": "🪟", "macos": "🍎", "linux": "🐧"}
        for n in status.nodes:
            role_icon = role_icons.get(n["role"], "?")
            os_icon = os_icons.get(n["os"], "?")
            ip_part = f"  {n['ip']}" if n["ip"] else ""
            print(f"    {role_icon}{os_icon} {n['id']:20s}  [{n['role']:7s}]  {n['access']:16s}{ip_part}")
            print(f"       services({n['service_count']}): {', '.join(n['services'][:5])}{'...' if n['service_count'] > 5 else ''}")

    print(f"\n  Total indexed: {status.total_nodes:,} nodes  {status.total_edges:,} edges")
    print()
    print("  Legend: ✓=indexed  ○=index:true but not yet indexed  —=skip  ✗=unreachable")
    print()
    return 0


def cmd_analyze(repo_path_str: str, force: bool = True, dry_run: bool = False) -> int:
    """
    Workspace-aware analyze:
    1. Analyze the main repo
    2. For each symlink with index:true, analyze the target
    3. For each sub_repo with auto_index:true, analyze it
    """
    repo_path = Path(repo_path_str).resolve()
    manifest = load_manifest(repo_path)

    if not manifest:
        print(f"[workspace] No workspace.json found at {repo_path}/.gitnexus/workspace.json")
        print("[workspace] Running standard analyze on main repo only...")
        if not dry_run:
            return 0 if _analyze_repo(repo_path, force=force) else 1
        return 0

    print(f"\n[workspace] Analyzing workspace: {manifest.workspace_root}")
    print(f"[workspace] Root: {repo_path}")

    targets: list[tuple[str, Path]] = [("(main)", repo_path)]

    for sl in manifest.symlinks:
        if not sl.index:
            print(f"[workspace]   skip symlink (index:false): {sl.name}")
            continue
        resolved = Path(sl.resolved).expanduser()
        if not resolved.is_dir():
            print(f"[workspace]   skip symlink (not accessible): {sl.name} → {resolved}")
            continue
        targets.append((f"symlink:{sl.name}", resolved))

    for sr in manifest.sub_repos:
        if not sr.auto_index:
            continue
        sr_path = repo_path / sr.path
        if not sr_path.is_dir():
            print(f"[workspace]   skip sub-repo (not found): {sr.name}")
            continue
        targets.append((f"sub-repo:{sr.name}", sr_path))

    print(f"\n[workspace] Targets ({len(targets)}):")
    for label, path in targets:
        print(f"  {label}: {path}")

    if dry_run:
        print("\n[workspace] Dry run — no analysis performed.")
        return 0

    print()
    results: list[tuple[str, bool]] = []
    for label, path in targets:
        print(f"\n[workspace] ── {label} ──────────────────")
        ok = _analyze_repo(path, force=force)
        results.append((label, ok))
        print(f"[workspace]   {'✓ done' if ok else '✗ failed'}: {label}")

    print(f"\n[workspace] ══ Results ══")
    all_ok = True
    for label, ok in results:
        mark = "✓" if ok else "✗"
        print(f"  {mark}  {label}")
        if not ok:
            all_ok = False

    if all_ok:
        print("\n[workspace] All targets indexed successfully.")
    else:
        print("\n[workspace] Some targets failed — check logs above.")

    return 0 if all_ok else 1


def cmd_cluster_status(repo_path_str: str, as_json: bool = False) -> int:
    """Show cluster node topology and service distribution."""
    repo_path = Path(repo_path_str).resolve()
    manifest = load_manifest(repo_path)

    if not manifest or not manifest.nodes:
        print(f"[cluster] No nodes defined in {repo_path}/.gitnexus/workspace.json")
        print("[cluster] Add a 'nodes' section to enable cluster topology view.")
        return 1

    # Build service lookup
    service_map: dict[str, WorkspaceService] = {s.id: s for s in manifest.services}
    total_services = sum(len(n.services) for n in manifest.nodes)

    if as_json:
        data = {
            "workspace_root": manifest.workspace_root,
            "cluster": manifest.cluster,
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "role": n.role,
                    "os": n.os,
                    "description": n.description,
                    "access": asdict(n.access) if n.access else None,
                    "network": asdict(n.network) if n.network else None,
                    "workspace_root": n.workspace_root,
                    "service_count": len(n.services),
                    "services": n.services,
                    "labels": n.labels,
                }
                for n in manifest.nodes
            ],
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    cluster = manifest.cluster
    cluster_labels = cluster.get("labels", {})

    print(f"\n{'='*70}")
    print(f"  Cluster: {manifest.workspace_root}")
    topology = cluster.get("topology", "")
    transport = cluster.get("transport", cluster_labels.get("vpn", ""))
    if topology or transport:
        print(f"  Topology: {topology or '—'}  /  Transport: {transport or '—'}")
    # Show tool-specific info from labels (if present)
    if cluster_labels.get("gateway_url"):
        print(f"  Gateway: {cluster_labels['gateway_url']}")
    if cluster_labels.get("tailnet"):
        print(f"  Network: {cluster_labels['tailnet']}")
    print(f"  Nodes: {len(manifest.nodes)}  /  Services: {total_services}")
    print(f"{'='*70}")

    role_order = {"gateway": 0, "primary": 1, "worker": 2}
    sorted_nodes = sorted(manifest.nodes, key=lambda n: role_order.get(n.role, 9))

    role_icons = {"gateway": "🌐", "worker": "⚙️ ", "primary": "💻"}
    os_tags = {"windows": "Win", "macos": "Mac", "linux": "Lnx"}

    print()
    for i, n in enumerate(sorted_nodes):
        role_icon = role_icons.get(n.role, "? ")
        os_tag = os_tags.get(n.os, "?")
        is_last = i == len(sorted_nodes) - 1
        connector = "└──" if is_last else "├──"
        indent = "   " if is_last else "│  "

        # Access / connection info
        access_str = _node_display_name(n)
        if n.access and n.access.type == "ssh":
            access_str = f"ssh {access_str}"

        # IP info
        ip_str = f"  [{_node_ip(n)}]" if _node_ip(n) else "  [local]"

        # Version labels (any tool's version info)
        version_parts = []
        for k, v in n.labels.items():
            if "version" in k.lower():
                version_parts.append(f"{k}={v}")
        version_str = "  " + ", ".join(version_parts[:2]) if version_parts else ""

        print(f"  {connector} {role_icon} [{os_tag}] {n.id}  ({n.role})")
        if n.description:
            print(f"  {indent}     {n.description}")
        print(f"  {indent}     {access_str}{ip_str}{version_str}")

        # Service list (wrapped at 5 per line)
        svcs = n.services
        if svcs:
            chunk_size = 5
            for j in range(0, len(svcs), chunk_size):
                chunk = svcs[j:j + chunk_size]
                if j == 0:
                    print(f"  {indent}     services({len(svcs)}): {', '.join(chunk)}")
                else:
                    print(f"  {indent}              {', '.join(chunk)}")
        print()

    print(f"  Legend: 🌐=gateway  💻=primary(local)  ⚙️=worker")
    print()
    return 0


def cmd_query(repo_path_str: str, query: str, as_json: bool = False) -> int:
    """Cross-workspace query: fan out to all indexed workspace repos."""
    repo_path = Path(repo_path_str).resolve()
    manifest = load_manifest(repo_path)

    repos: list[tuple[str, Path]] = [(repo_path.name, repo_path)]

    if manifest:
        for sl in manifest.symlinks:
            if sl.index and sl.register_as:
                resolved = Path(sl.resolved).expanduser()
                if resolved.is_dir() and (resolved / ".gitnexus" / "meta.json").exists():
                    repos.append((sl.register_as, resolved))

        for sr in manifest.sub_repos:
            if sr.auto_index:
                sr_path = repo_path / sr.path
                if sr_path.is_dir() and (sr_path / ".gitnexus" / "meta.json").exists():
                    repos.append((sr.name, sr_path))

    if not query:
        print("[workspace-query] No query provided.")
        return 1

    all_results: list[dict] = []
    for repo_name, rpath in repos:
        try:
            result = subprocess.run(
                [GITNEXUS_BIN, "query", "--repo", repo_name, query],
                cwd=str(rpath),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                all_results.append({
                    "repo": repo_name,
                    "path": str(rpath),
                    "results": result.stdout.strip(),
                })
        except Exception as e:
            logger.warning(f"Query failed for {repo_name}: {e}")

    if as_json:
        print(json.dumps(all_results, indent=2, ensure_ascii=False))
        return 0

    if not all_results:
        print(f"[workspace-query] No results for: {query}")
        return 0

    for r in all_results:
        print(f"\n{'─'*60}")
        print(f"  Repo: {r['repo']}")
        print(f"{'─'*60}")
        print(r["results"])

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    p = argparse.ArgumentParser(description="Workspace Builder for gitnexus-stable-ops")
    p.add_argument("command", choices=["status", "analyze", "query", "cluster-status"])
    p.add_argument("repo_path", nargs="?", default=os.getcwd())
    p.add_argument("--query", "-q", default="", help="Query string (for 'query' command)")
    p.add_argument("--force", action="store_true", default=True)
    p.add_argument("--no-force", dest="force", action="store_false")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")

    args = p.parse_args()

    if args.command == "status":
        return cmd_status(args.repo_path, as_json=args.as_json)
    elif args.command == "analyze":
        return cmd_analyze(args.repo_path, force=args.force, dry_run=args.dry_run)
    elif args.command == "query":
        return cmd_query(args.repo_path, query=args.query, as_json=args.as_json)
    elif args.command == "cluster-status":
        return cmd_cluster_status(args.repo_path, as_json=args.as_json)
    return 1


if __name__ == "__main__":
    sys.exit(main())
