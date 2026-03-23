# Agent Context Graph

> **Language**: [English](./agent-context-graph_en.md) | [日本語](./agent-context-graph.md)

**gitnexus-stable-ops v1.3.0** で追加された機能。コードシンボルグラフ（GitNexusのコアグラフ）とは独立した、エージェント/スキル/ノード/サービスの知識グラフ。

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

## 5分クイックスタート

新しいワークスペースへの Agent Context Graph 導入手順です。

### Step 1: workspace.json を作成 (1分)

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

### Step 2: SKILL/ ディレクトリを作成 (1分)

```bash
mkdir -p ~/dev/MY_WORKSPACE/SKILL/infra
cat > ~/dev/MY_WORKSPACE/SKILL/infra/deploy.md << 'EOF'
# Deploy スキル

**Version**: 1.0.0
**トリガー**: deploy, デプロイ, リリース, publish

## 概要
本番環境へのデプロイを担当する。

## 使い方
1. テスト通過確認
2. `npm run build` でビルド
3. `git push origin main` でデプロイトリガー
EOF
```

### Step 3: グラフ構築 (1分)

```bash
cd ~/dev/MY_WORKSPACE
gni agent-index . --force

# 出力例:
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

### Step 4: 動作確認 (1分)

```bash
# 統計確認
gni agent-status
# → Agents: 1, Skills: 1, Total Nodes: 4

# クエリ実行
gni aq "deploy"
# → ## Agent Context [Standard] query:'deploy'
#   ### Skills
#   - **deploy** — 本番環境へのデプロイを担当する。
```

### Step 5: Claude Code に注入 (1分)

```bash
# CLAUDE.md へのセクション自動注入
gni context-gen . --target claude --update

# または手動でコンテキストを取得してシステムプロンプトに使用
gni aq "deploy" --level 1  # ~100 tokens のコンパクトな概要
```

---

## セットアップ（既存ワークスペース向け）

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

## workspace.json v1.1 スキーマ詳細

`.gitnexus/workspace.json` の完全スキーマを説明します。

### トップレベルフィールド

```json
{
  "version": "1.1",              // スキーマバージョン（必須）
  "workspace_root": "NAME",      // ワークスペース名（必須）
  "description": "説明",         // オプション

  "symlinks": [...],             // シンボリックリンク定義（オプション）
  "sub_repos": [...],            // サブリポジトリ（オプション）
  "nodes": [...],                // コンピュートノード（必須）
  "services": [...],             // ワークスペースサービス（必須）
  "knowledge_refs": {...},       // ナレッジディレクトリマッピング（必須）
  "cluster": {...},              // クラスター設定（オプション）
  "index_policy": {...}          // インデックスポリシー（オプション）
}
```

### nodes[] — コンピュートノード

```json
{
  "id": "gateway",              // 一意ID（必須）
  "name": "Windows Gateway",   // 表示名（必須）
  "role": "gateway|worker|primary",  // ノードロール（必須）
  "os": "windows|macos|linux", // OS（必須）
  "description": "説明",       // オプション
  "access": {
    "type": "local|ssh",       // アクセス方式（必須）
    "host": "win-ts",          // SSH: ホスト名（ssh時必須）
    "user": "username"         // SSH: ユーザー（オプション）
  },
  "network": {
    "ip": "100.86.157.40",     // Tailscale IP（オプション）
    "labels": {"vpn": "tailscale"}
  },
  "workspace_root": "/path/to/ws",  // ワークスペースパス（オプション）
  "services": ["main", "x-ops"],    // このノードのサービスID一覧
  "labels": {
    "node_version": "v25.7.0",      // 任意のラベル
    "openclaw_version": "2026.3.11"
  }
}
```

**role の意味**:

| role | 説明 | 典型的なノード |
|------|------|--------------|
| `primary` | メイン開発マシン（ローカル実行） | MacBook Pro |
| `gateway` | OpenClaw Gateway（エージェント統括） | Windows PC |
| `worker` | Worker Node（分散実行） | Mac mini |

### services[] — ワークスペースサービス

```json
{
  "id": "cc-hayashi",           // 一意ID（必須）
  "name": "Claude Code Hayashi",// 表示名（必須）
  "type": "agent|server|tool",  // サービスタイプ（必須）
  "node": "macbook",            // nodes[].id への参照（必須）
  "description": "説明",        // オプション
  "skill_refs": ["SKILL/"],     // 参照するSKILLパス（オプション）
  "memory_refs": ["MEMORY/"],   // 参照するMEMORYパス（オプション）
  "labels": {
    "model": "claude-sonnet-4-6",  // 任意のラベル
    "heartbeat_interval": "4h"
  }
}
```

### knowledge_refs — ナレッジディレクトリマッピング

```json
{
  "skills_dir": "SKILL",        // スキル定義のルートディレクトリ（必須）
  "memory_dir": "MEMORY",       // メモリ/学習記録ディレクトリ
  "knowledge_dir": "KNOWLEDGE", // ナレッジベースディレクトリ
  "scripts_dir": "scripts",     // スクリプトディレクトリ
  "config_dir": "config"        // 設定ファイルディレクトリ
}
```

### 実際の例（HAYASHI_SHUNSUKE ワークスペース）

```json
{
  "version": "1.1",
  "workspace_root": "HAYASHI_SHUNSUKE",
  "description": "林駿甫パーソナルワークスペース — エージェント社会 + 全プロジェクト",
  "nodes": [
    {
      "id": "gateway",
      "name": "Windows Gateway (AAI)",
      "role": "gateway",
      "os": "windows",
      "description": "OpenClaw Gateway — 39エージェント統括",
      "access": {"type": "ssh", "host": "win-ts"},
      "network": {"ip": "100.86.157.40"},
      "services": ["main", "x-ops"],
      "labels": {"openclaw_version": "2026.3.11"}
    },
    {
      "id": "macbook",
      "name": "MacBook Pro (primary)",
      "role": "primary",
      "os": "macos",
      "access": {"type": "local"},
      "workspace_root": "/Users/shunsukehayashi/dev/HAYASHI_SHUNSUKE",
      "services": ["cc-hayashi", "kotowari-dev", "guardian"]
    }
  ],
  "services": [
    {
      "id": "main",
      "type": "agent",
      "node": "gateway",
      "description": "OpenClawメインエージェント — 全体統括・タスク分配",
      "skill_refs": ["SKILL/infra/", "SKILL/personal/"],
      "labels": {"model": "gemini-2.5-flash"}
    },
    {
      "id": "cc-hayashi",
      "type": "agent",
      "node": "macbook",
      "description": "Claude Code/Codex連携エージェント (ACP)",
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
```

---

## Agent / Skill の定義方法

### SKILL/ ディレクトリ構造

```
SKILL/
├── README.md               # スキルカタログ概要
├── SKILL_CATALOG.md        # 全スキル一覧（自動生成）
├── _index_generated.md     # GitNexus生成インデックス
│
├── personal/               # パーソナル系スキル
│   ├── hayashi-cli.md
│   ├── task-tracker.md
│   └── health-monitor.md
│
├── infra/                  # インフラ系スキル
│   ├── gitnexus.md
│   ├── claude-code-ops.md
│   ├── codex-workers.md
│   └── agent-skill-bus.md
│
├── openclaw/               # OpenClaw系スキル
│   ├── openclaw-agent-sync.md
│   └── xai-account-ops/
│       └── skill.md
│
├── business/               # ビジネス系スキル
├── content/                # コンテンツ系スキル
└── communication/          # コミュニケーション系スキル
```

### スキル定義ファイルの書き方

Agent Context Graph はスキル `.md` ファイルからメタデータを抽出します。

```markdown
# スキル名

**Version**: 1.0.0
**Created**: 2026-03-17
**トリガー**: deploy, デプロイ, リリース, publish

## 概要

このスキルの概要を1-2文で書く。ここの内容が `gni aq` の Level 2 出力の
description として表示される。

## 使い方
...
```

**重要なフィールド**:

| フィールド | 役割 | 検索への影響 |
|-----------|------|------------|
| `# タイトル` | スキル名 (`name`) | BM25スコアに影響 |
| `**トリガー**: ...` | キーワード (`keywords`) | FTS5検索の主要対象 |
| `## 概要` 直後の文 | 説明文 (`description`) | Level 2 出力で表示 |
| ファイルパス | カテゴリ推定 | タイプウェイト計算 |

### エージェント定義の取得元

Agent Context Graph はエージェント情報を以下のファイルから自動抽出します：

- `AGENTS.md` — エージェント社会の定義
- `.claude/CLAUDE.md` — エージェント情報を含む場合
- `docs/*.md` — ロール定義を含む文書
- OpenClaw `workspace.json` → `services[]` — サービスとして定義されたエージェント

```
AGENTS.md に含まれる情報:
  エージェント名（日本語名 + ID）
  役割 (role)
  tmux ペイン（pane）
  担当タスク
        ↓
  agent_graph_builder.py で自動解析
        ↓
  agents テーブルに登録
```

---

## OpenClaw / Codex / Claude Code への統合

### Claude Code への統合

**システムプロンプトへの自動注入**:

```bash
# CLAUDE.md に Agent Context Graph セクションを追加/更新
gni context-gen . --target claude --update

# 生成されるセクション:
# <!-- gitnexus:agent-context:start -->
# ## Agent Context (GitNexus)
# ### Cluster Topology
# | Role | ID | OS | SSH | Description |
# ...
# ### Available Skills
# business (15): `asset-creation`, ...
# <!-- gitnexus:agent-context:end -->
```

**Level 1 コンテキストを Python から取得**:

```python
import subprocess

def get_agent_context(query: str, level: int = 1) -> str:
    """Claude のシステムプロンプトに注入するコンテキストを取得"""
    result = subprocess.check_output(
        ["gni", "aq", query, "--level", str(level), "--format", "progressive"],
        text=True
    )
    return result

# システムプロンプト例
query = "デプロイ"
ctx = get_agent_context(query, level=1)

system_prompt = f"""You are an AI assistant for Hayashi's workspace.

## Available Agent Context
{ctx}

If you need more detail, ask the user to run:
  gni aq "{query}" --level 3
"""
```

**実際のコマンド出力例**:

```bash
$ gni aq "announce" --level 1
## Agent Context [Overview] query:'announce'
skills: [announce, macbook-local-announce]
skill: 2 matched
~1534 tokens (savings: 99.2%)

$ gni aq "deploy" --level 2
## Agent Context [Standard] query:'deploy'

### Agents
- **ボタン** — Deploy / Release

~200 tokens | savings: 99.9%

$ gni aq "cc-hayashi" --level 3
# Agent Context: cc-hayashi

**Agents**: ながれるん, カエデ, サクラ, ツバキ, ボタン
**Skills**: agent-skill-bus, claude-code-ops, codex-workers, ...
**Tokens**: ~4898 (savings: 97.5%)
...
```

### Codex への統合

Codex は独立したサンドボックスで実行されるため、タスク投入時にコンテキストを埋め込みます。

```bash
# Codex にタスクを投入する前にコンテキストを取得
CONTEXT=$(gni aq "実装タスク" --level 2)

# Codex のシステムプロンプトに追加
tmux send-keys -t %305 "[TASK] 機能を実装してください

## Agent Context
${CONTEXT}

## 要件
- 要件1
- 要件2

完了後: [DONE] で %0 に報告" Enter
```

### OpenClaw への統合

OpenClaw エージェントのシステムプロンプトに `gni aq` の出力を含める方法:

```bash
# エージェントの HEARTBEAT.md に Agent Context を自動注入する Bash スクリプト例
#!/bin/bash
# scripts/update-heartbeat-with-context.sh

WORKSPACE="/Users/shunsukehayashi/dev/HAYASHI_SHUNSUKE"
HEARTBEAT="$WORKSPACE/HEARTBEAT.md"

# 最新のコンテキストを取得
CONTEXT=$(gni aq "直近のタスク" --level 2 --repo "$WORKSPACE")

# HEARTBEAT.md のコンテキストセクションを更新
# <!-- agent-context:start --> ... <!-- agent-context:end --> を差し替え
python3 -c "
import re, sys
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

**定期更新（cron）**:

```bash
# crontab -e
# 毎朝 6:00 にエージェントグラフを再構築して HEARTBEAT.md を更新
0 6 * * * cd ~/dev/HAYASHI_SHUNSUKE && gni ai . --force && \
  ~/dev/HAYASHI_SHUNSUKE/scripts/update-heartbeat-with-context.sh
```

---

## FAQ

**Q: `gni agent-status` で Memory Docs が 0 と表示される**

A: v1.6.0 未満のバグです。`--force` で完全再構築してください:
```bash
gni ai . --force
gni as
# → Memory Docs: 25
```

**Q: `gni aq "cc-hayashi"` でエージェントが見つからない（ハイフン入りクエリ）**

A: ハイフン (`-`) は FTS5 で演算子として扱われます。ハイフンなしクエリを使うか、
スキルIDの一部を検索してください:
```bash
gni aq "cc hayashi"   # ✅ スペース区切り
gni aq "claude code"  # ✅ キーワードで検索
gni aq "cc-hayashi"   # ⚠️ FTS5 でパースエラーになる場合がある
```

**Q: インクリメンタルビルドと `--force` の違いは？**

| モード | 動作 | 使いどころ |
|--------|------|----------|
| `gni ai .` | ノードは `INSERT OR REPLACE`、エッジはクリア後再構築 | 通常の更新 |
| `gni ai . --force` | DB を完全破棄して再作成 | スキーマ変更後・確実な再構築 |
| `gni ai . --dry-run` | DB を更新せずプレビュー出力 | 変更確認 |

**Q: `gni agent-status` で Skills の件数が期待より少ない**

A: 重複する `skill_id` スラッグを持つスキルは `INSERT OR REPLACE` で上書きされます。
`gni ai . --dry-run` で実際に検出されるスキル数を確認してください:
```bash
gni ai . --dry-run
# Skills: 83  ← dry-run での検出数
gni as
# Skills: 79  ← ユニーク skill_id 数（重複4件が上書き）
```

**Q: `_index_generated.md` がスキルとして認識される**

A: これは意図的な動作です。スキルインデックスファイル自体もグラフで検索可能になります（`unknown` カテゴリ）。
不要な場合は `gni ai .` 前に削除するか、`.gitnexusignore` で除外してください:
```bash
echo "SKILL/_index_generated.md" >> .gitnexusignore
```

**Q: FTS5 が使えない（SQLite バージョンの問題）**

A: SQLite 3.35+ と FTS5 が必要です。Node.js v24+ で `node:sqlite` モジュールを使用すると FTS5 が有効になります:
```bash
node --version   # v24+ 必須
python3 -c "import sqlite3; print(sqlite3.sqlite_version)"  # 3.35+ 確認
```

**Q: `gni aq` が日本語クエリでうまく検索できない**

A: `_preprocess_query()` でビグラム分割が行われます。2文字以上のひらがな/カタカナ/漢字クエリは自動的にビグラムに分割されます:
```
"openclaw エージェント"
  → "openclaw" + "エー" + "ージ" + "ジェ" + "ェン" + "ント"
```
1文字のクエリ（`ン` など）はマッチしない場合があります。2文字以上で検索してください。

**Q: エージェントグラフと GitNexus コードグラフの併用**

A: 2つのグラフは完全独立です。両方を同時に使用できます:
```bash
# コードグラフ: 関数の影響分析
gni impact validateUser --direction upstream

# エージェントグラフ: コンテキスト取得
gni aq "validate" --level 2

# 組み合わせ: コードを理解しながらエージェントコンテキストも把握
gni aq "deploy" --level 1 && gni context deploy --format short
```

---

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
