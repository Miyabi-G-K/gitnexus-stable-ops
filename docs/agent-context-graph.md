# Agent Context Graph

**gitnexus-stable-ops v1.6.0** で追加された機能。コードシンボルグラフ（GitNexusのコアグラフ）とは独立した、エージェント/スキル/ノード/サービスの知識グラフ。

## 概要

```
                  ┌──────────────────────┐
  Code Graph      │ ~/.gitnexus/         │  ← GitNexus コアグラフ
  (32K+ symbols)  │  KuzuDB / LadybugDB  │    gni query/context/impact
                  └──────────────────────┘

                  ┌──────────────────────┐
  Agent Graph     │ .gitnexus/           │  ← エージェントコンテキストグラフ
  (270+ nodes)    │  agent-graph.db      │    gni ai/as/aq/cg
                  └──────────────────────┘
```

**2つのグラフは独立して動作**します。コードグラフを使いながらエージェントグラフも使えます。

## セットアップ

```bash
# 1. エージェントグラフを構築（初回のみ）
gni agent-index ~/dev/MY_WORKSPACE --force

# 2. 統計確認
gni agent-status

# 3. クエリ実行
gni aq "deploy"

# 4. CLAUDE.md/AGENTS.md 生成
gni context-gen . --target agents
gni context-gen . --target claude --update
```

## コマンドリファレンス

### `gni agent-index` (alias: `ai`)

Agent Context Graph を構築/更新します。

```bash
gni ai [repo-path] [--force] [--dry-run] [--json]
```

| オプション | 説明 |
|-----------|------|
| `--force` | 完全再構築（既存DBを破棄して再作成） |
| `--dry-run` | 変更プレビューのみ（DBは更新しない） |
| `--json` | 構築結果をJSON形式で出力 |

**インデックス対象**:

| カテゴリ | ソース | DBテーブル |
|---------|--------|-----------|
| Agents | `AGENTS.md` / `docs/*.md` / `.claude/` | `agents` |
| Skills | `SKILL/**/*.md` / `.claude/skills/` | `skills` |
| Knowledge Docs | `KNOWLEDGE/**/*.md` / `docs/**/*.md` | `knowledge_docs` |
| Memory Docs | `MEMORY/**/*.md` / `.claude/projects/*/memory/` | `memory_docs` |
| Compute Nodes | `.gitnexus/workspace.json` → `nodes[]` | `compute_nodes` |
| Workspace Services | `.gitnexus/workspace.json` → `services[]` | `workspace_services` |

### `gni agent-status` (alias: `as`)

グラフの統計情報を表示します。

```bash
gni as [repo-path]
```

出力例:
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

エージェントコンテキストを検索します。**Progressive Disclosure** で返すトークン量を制御。

```bash
gni aq "<query>" [--level 1|2|3] [--format progressive|json|markdown] [--repo path]
```

#### Progressive Disclosure レベル

| Level | トークン量 | 内容 | 用途 |
|-------|-----------|------|------|
| 1 | ~100 tokens | IDと件数のみ | システムプロンプト冒頭の全体把握 |
| 2 | ~400 tokens | 名前・役割・属性 (default) | 標準的なプロンプト注入 |
| 3 | ~2000 tokens | 完全情報・全エッジ | オンデマンドの深堀り |

```bash
# Level 1 — "何があるか" を把握（プロンプト冒頭）
gni aq "announce" --level 1
# → skills: [announce, macbook-local-announce]
#   skill: 2 matched (~100 tokens)

# Level 2 — デフォルト（標準注入）
gni aq "deploy"
# → ## Agent Context [Standard] query:'deploy'
#   ### Skills
#   - **agent-skill-bus** — ...
#   (~400 tokens)

# Level 3 — 完全情報（オンデマンド）
gni aq "cc-hayashi" --level 3
# → Full detail with all edges (~2000 tokens)
```

#### LLM への注入例

```python
# Python
import subprocess

level1 = subprocess.check_output(
    ["gni", "aq", query, "--level", "1", "--format", "progressive"]
).decode()

system_prompt = f"""
You are an AI assistant for Hayashi's development workspace.

{level1}  # ← ここに挿入 (~100 tokens)

If you need more detail about a specific agent or skill,
ask the user to run: gni aq "<keyword>" --level 3
"""
```

### `gni context-gen` (alias: `cg`)

エージェントグラフから CLAUDE.md/AGENTS.md/スキルインデックスを自動生成します。

```bash
gni context-gen [repo-path] [options]
```

| オプション | 説明 |
|-----------|------|
| `--target claude\|agents\|skill\|all` | 生成対象（default: all） |
| `--update` | 既存ファイルのセクションを更新 |
| `--dry-run` | ファイルを書かず stdout に出力 |
| `--json` | JSON サマリー出力 |
| `--out-dir <path>` | 出力先ディレクトリ |

#### ワークフロー

```bash
# 初回セットアップ
gni ai . --force          # 1. グラフ構築
gni cg . --dry-run        # 2. プレビュー確認
gni cg . --target agents  # 3. AGENTS.md 生成（Codex向け）
gni cg . --target claude --update  # 4. CLAUDE.md にセクション注入

# 定期更新
gni ai . --force && gni cg . --target claude --update
```

#### 生成されるファイル

**CLAUDE.md** — `<!-- gitnexus:agent-context:start/end -->` で囲まれたセクション:

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

**AGENTS.md** — Codex や他の AI エージェント向けの完全マニフェスト:

```markdown
# AGENTS.md
## Summary
- Agents: 5, Skills: 79, ...

## Cluster Topology
...

## Agents
### Development Society (5)
#### 🍁 カエデ (`kade`)
- Role: CodeGen / Developer
...

## Skills
### Business (15)
| Skill | Description |
...
```

**SKILL/_index_generated.md** — スキルクイックリファレンス

## workspace.json との関係

Agent Context Graph は `.gitnexus/workspace.json` から**ノード/サービス情報**を読み込みます。

```json
{
  "schema_version": "1.1",
  "nodes": [
    {
      "id": "gateway",
      "role": "gateway",
      "os": "windows",
      "description": "OpenClaw Gateway — 39エージェント統括",
      "access": {"type": "ssh", "host": "win-ts"},
      "network": {"ip": "100.86.157.40", "vpn": "tailscale"},
      "services": ["main", "x-ops"]
    }
  ],
  "services": [
    {
      "id": "main",
      "type": "agent",
      "node": "gateway",
      "model": "gemini-2.5-flash"
    }
  ]
}
```

詳細は [workspace-schema.md](./workspace-schema.md) を参照してください。

## コードグラフとの使い分け

| 用途 | コマンド | グラフ |
|------|---------|--------|
| 関数の影響分析 | `gni impact <symbol>` | コードグラフ |
| APIの使い方を調べる | `gni context <symbol>` | コードグラフ |
| エージェントのノードを調べる | `gni aq "agent-name" --level 2` | エージェントグラフ |
| スキルの使い方を調べる | `gni aq "skill-name" --level 3` | エージェントグラフ |
| LLMプロンプトに注入 | `gni aq "<keyword>" --level 1` | エージェントグラフ |
| CLAUDE.md 更新 | `gni cg . --update` | エージェントグラフ |

## トラブルシューティング

### Agent Graph DB が見つからない

```
ERROR: Agent Graph DB not found: ...
Run `gni agent-index <repo> --force` first.
```

解決策: `gni ai . --force` でグラフを構築してください。

### Memory Docs: 0 と表示される

インクリメンタルビルドでは既存 DB を使用するため、新しいメモリファイルが検出されない場合があります。
`gni ai . --force` で完全再構築してください。

### `_index_generated` がスキルとして認識される

`SKILL/_index_generated.md` が生成されると、次回の `gni ai --force` でスキルとしてインデックスされます（`unknown` カテゴリ）。これは意図的な動作で、スキルインデックス自体もエージェントグラフで検索可能になります。
