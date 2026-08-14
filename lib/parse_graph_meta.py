#!/usr/bin/env python3
"""
Parse GitNexus graph metadata from Cypher query results.
Extracts cross-cluster edges and calculates relationship weights.
"""
import sys
import json


def calculate_weight(edges):
    """Calculate relationship weight based on edge count."""
    if edges >= 10:
        return 0.95
    elif edges >= 5:
        return round(0.7 + (edges - 5) * 0.04, 2)
    elif edges >= 2:
        return round(0.4 + (edges - 2) * 0.1, 2)
    else:
        return 0.2


def main():
    if len(sys.argv) < 3:
        print("Usage: parse_graph_meta.py <repo_name> <timestamp>", file=sys.stderr)
        sys.exit(1)

    repo = sys.argv[1]
    ts = sys.argv[2]

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if "error" in data or "markdown" not in data:
        sys.exit(0)

    lines = data["markdown"].strip().split("\n")
    
    # Skip header rows (first 2 lines)
    for line in lines[2:]:
        cols = [c.strip() for c in line.split("|") if c.strip()]
        if len(cols) < 5:
            continue

        try:
            edges = int(cols[4])
        except ValueError:
            continue

        weight = calculate_weight(edges)

        print(json.dumps({
            "repo": repo,
            "fromCluster": cols[0],
            "fromLabel": cols[1],
            "toCluster": cols[2],
            "toLabel": cols[3],
            "crossEdges": edges,
            "weight": weight,
            "ts": ts
        }))


if __name__ == "__main__":
    main()
