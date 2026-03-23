#!/usr/bin/env python3
"""
Workspace Builder — Phase 1 Workspace Graph
Reads .gitnexus/workspace.json and orchestrates cross-repo,
cross-symlink analysis for agent-aware workspaces.

Resolves Issue #24: workspace-aware analysis for symlinks and sub-repos.
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
# Data classes
# ---------------------------------------------------------------------------

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
    agent_context: dict = field(default_factory=dict)
    index_policy: dict = field(default_factory=dict)


@dataclass
class WorkspaceStatus:
    workspace_root: str
    workspace_path: str
    manifest_found: bool
    symlinks: list[dict] = field(default_factory=list)
    sub_repos: list[dict] = field(default_factory=list)
    indexed_repos: list[str] = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

def load_manifest(repo_path: str | Path) -> Optional[WorkspaceManifest]:
    """Load .gitnexus/workspace.json from a repo path."""
    manifest_path = Path(repo_path) / ".gitnexus" / "workspace.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        symlinks = [WorkspaceSymlink(**s) for s in data.get("symlinks", [])]
        sub_repos = [WorkspaceSubRepo(**r) for r in data.get("sub_repos", [])]
        return WorkspaceManifest(
            version=data.get("version", "1.0"),
            workspace_root=data.get("workspace_root", ""),
            description=data.get("description", ""),
            symlinks=symlinks,
            sub_repos=sub_repos,
            agent_context=data.get("agent_context", {}),
            index_policy=data.get("index_policy", {}),
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
    # Fallback to PATH-based gitnexus
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

    # Add the main workspace itself
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
    print(f"{'='*60}")

    main_nodes = main_meta.get("stats", {}).get("nodes", 0)
    main_edges = main_meta.get("stats", {}).get("edges", 0)
    main_indexed = repo_path.name in indexed or (repo_path / ".gitnexus" / "meta.json").exists()
    print(f"\n  [Main Repo]")
    print(f"    {repo_path.name:30s}  {'✓' if main_indexed else '○'}  {main_nodes:6d} nodes  {main_edges:6d} edges")

    if status.symlinks:
        print(f"\n  [Symlinks]")
        for sl in status.symlinks:
            idx_mark = "✓" if sl["indexed"] else ("○" if sl["index"] else "—")
            acc_mark = "✓" if sl["accessible"] else "✗"
            nodes = sl["nodes"] if sl["nodes"] else "—"
            print(f"    {sl['name']:30s}  {idx_mark}  acc:{acc_mark}  {str(nodes):>6} nodes")
            print(f"    {'':30s}     → {sl['resolved']}")

    if status.sub_repos:
        print(f"\n  [Sub-repos in PROJECTS/]")
        for sr in status.sub_repos:
            idx_mark = "✓" if sr["indexed"] else ("○" if sr["auto_index"] else "—")
            git_mark = "git" if sr["is_git_repo"] else "dir"
            nodes = sr["nodes"] if sr["nodes"] else "—"
            print(f"    {sr['name']:30s}  {idx_mark}  [{git_mark}]  {str(nodes):>6} nodes")

    print(f"\n  Total indexed: {status.total_nodes:,} nodes  {status.total_edges:,} edges")
    print()
    print("  Legend: ✓=indexed  ○=index:true but not yet indexed  —=skip  ✗=unreachable")
    print()
    return 0


def cmd_analyze(repo_path_str: str, force: bool = True, dry_run: bool = False) -> int:
    """
    Workspace-aware analyze:
    1. Analyze the main repo
    2. For each symlink with index:true, analyze the target separately
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

    targets: list[tuple[str, Path]] = []

    # 1. Main repo
    targets.append(("(main)", repo_path))

    # 2. Symlinks with index:true
    for sl in manifest.symlinks:
        if not sl.index:
            print(f"[workspace]   skip symlink (index:false): {sl.name}")
            continue
        resolved = Path(sl.resolved).expanduser()
        if not resolved.is_dir():
            print(f"[workspace]   skip symlink (not accessible): {sl.name} → {resolved}")
            continue
        targets.append((f"symlink:{sl.name}", resolved))

    # 3. Sub-repos with auto_index:true
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


def cmd_query(repo_path_str: str, query: str, as_json: bool = False) -> int:
    """Cross-workspace query: fan out to all indexed workspace repos."""
    repo_path = Path(repo_path_str).resolve()
    manifest = load_manifest(repo_path)

    # Collect all repos to search
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
    p.add_argument("command", choices=["status", "analyze", "query"])
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
