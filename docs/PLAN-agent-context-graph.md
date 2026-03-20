# GitNexus Agent Context Graph — 拡張プラン

> **ゴール**: コンテキストウィンドウの効率的使用のため、グラフベースのコンテキスト探索を実現する
> **作成日**: 2026-03-20
> **ステータス**: DRAFT — レビュー待ち

---

## 1. 課題: なぜこの拡張が必要か

### 現状の問題

```
セッション開始
  ↓
CLAUDE.md 全読み込み（~15,000 tokens）
  ↓
.claude/rules/*.md 全読み込み（~20,000 tokens）
  ↓
AGENTS.md 読み込み（~8,000 tokens）
  ↓
残りコンテキスト = 全体の30-40%しか作業に使えない
```

**13エージェント × 71スキル × 95ナレッジ = 179ノード** の情報が存在するが、
1回のタスクで必要なのは通常 **3-8ノード** のみ。

### 理想の動作

```
タスク: "定款を修正して"
  ↓
グラフ探索: 法務Agent → teikan-drafter Skill → K_PROJECTS (miyabi-llc)
  ↓
必要なコンテキストのみ読み込み（~2,000 tokens）
  ↓
残り95%のコンテキストを作業に使える
```

---

## 2. 設計概要

### アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: Agent Context Graph (新規)                     │
│  ┌──────┐  ┌──────┐  ┌──────────┐  ┌─────────┐         │
│  │Agent │→ │Skill │→ │Knowledge │→ │External │         │
│  │ノード│  │ノード│  │ノード    │  │Service  │         │
│  └──────┘  └──────┘  └──────────┘  └─────────┘         │
│        ↕ 同一グラフDB内で共存                            │
│  ┌──────┐  ┌──────────┐  ┌─────────┐                   │
│  │Code  │→ │Community │→ │Process  │                   │
│  │Symbol│  │(cluster) │  │(flow)   │                   │
│  └──────┘  └──────────┘  └─────────┘                   │
│  Layer 0: 既存 GitNexus Code Graph                      │
└─────────────────────────────────────────────────────────┘
              ↓ Cypher Query
┌─────────────────────────────────────────────────────────┐
│  gni agent-context "定款を修正して"                       │
│  → Agent: 法務 → Skills: [teikan-drafter, tracker]      │
│  → Knowledge: [K_PROJECTS/miyabi-llc-setup.md]          │
│  → Files: [miyabi-llc-setup/PROJECT_SPEC.md]            │
│  → Tokens: ~2,000 (vs 全読み込み ~43,000)               │
└─────────────────────────────────────────────────────────┘
```

### 新規ノード型

| ノード型 | ソース | プロパティ |
|---------|--------|-----------|
| `Agent` | AGENTS.md, KNOWLEDGE/agents/ | name, emoji, role, pane_id, society |
| `Skill` | SKILL/*.md | name, category, path, dependencies |
| `KnowledgeDoc` | KNOWLEDGE/**/*.md | name, path, category, priority |
| `DataSource` | personal-data/**/*.json | name, path, schema, is_ssot |
| `ExternalService` | (定義ファイル) | name, api_url, auth_type |

### 新規エッジ型

| エッジ型 | From → To | 意味 |
|---------|-----------|------|
| `USES_SKILL` | Agent → Skill | エージェントがスキルを使用 |
| `DEPENDS_ON` | Skill → KnowledgeDoc | スキルがナレッジを参照 |
| `READS_DATA` | Skill → DataSource | スキルがデータを読む |
| `WRITES_DATA` | Skill → DataSource | スキルがデータを書く |
| `CALLS_SERVICE` | Skill → ExternalService | 外部API呼び出し |
| `COMPOSES` | Skill → Skill | スキル間依存 |
| `IMPLEMENTS_CODE` | Skill → Function/File | スキルの実体コード |
| `ROUTES_TO` | Agent → Agent | タスクルーティング |

---

## 3. 実装フェーズ

### Phase 1: Agent Graph Indexer（コア）

**成果物**: `bin/gitnexus-agent-index.sh` + `lib/agent_graph_builder.py`

**動作**:
1. AGENTS.md / SKILL/*.md / KNOWLEDGE/ をパース
2. ノード・エッジのJSONLを生成
3. GitNexus の Cypher INSERT でグラフDBに注入

```bash
# 使い方
bin/gitnexus-agent-index.sh /path/to/HAYASHI_SHUNSUKE

# 内部処理
# 1. scan: AGENTS.md → Agent nodes
# 2. scan: SKILL/**/*.md → Skill nodes + frontmatter parse
# 3. scan: KNOWLEDGE/**/*.md → KnowledgeDoc nodes
# 4. scan: personal-data/**/*.json → DataSource nodes
# 5. resolve: 依存関係 → edge JSONL
# 6. inject: Cypher CREATE/MERGE → .gitnexus/lbug
```

**パーサー仕様** (`lib/agent_graph_builder.py`):

```python
# SKILL/*.md のフロントマター例:
# ---
# name: teikan-drafter
# category: business
# agents: [法務, 確定申告]
# depends_on: [K_PROJECTS]
# external: []
# ---

# → Node: {type: "Skill", name: "teikan-drafter", category: "business", path: "SKILL/business/teikan-drafter.md"}
# → Edge: {type: "USES_SKILL", from: "法務", to: "teikan-drafter"}
# → Edge: {type: "DEPENDS_ON", from: "teikan-drafter", to: "K_PROJECTS"}
```

**推定工数**: 2-3日
**ファイル**: `bin/gitnexus-agent-index.sh`, `lib/agent_graph_builder.py`

---

### Phase 2: Context Resolver（クエリ層）

**成果物**: `bin/gitnexus-agent-context.sh`, `gni agent-context` コマンド

**コア機能**: タスク記述 → 関連ノード探索 → 最小コンテキスト返却

```bash
# 入力: 自然言語タスク or エージェント名 or スキル名
gni agent-context "定款を修正して"
gni agent-context --agent "法務"
gni agent-context --skill "teikan-drafter"
gni agent-context --depth 2  # 探索深度（デフォルト: 2）
```

**出力（JSON）**:

```json
{
  "query": "定款を修正して",
  "matched_agents": ["法務"],
  "context_chain": [
    {"type": "Agent", "name": "法務", "role": "Legal Agent"},
    {"type": "Skill", "name": "teikan-drafter", "path": "SKILL/business/teikan-drafter.md"},
    {"type": "Skill", "name": "touki-guide", "path": "SKILL/business/touki-guide.md"},
    {"type": "Skill", "name": "miyabi-tracker", "path": "SKILL/business/miyabi-tracker.md"},
    {"type": "KnowledgeDoc", "name": "miyabi-llc-setup", "path": "PROJECTS/miyabi-llc-setup.md"}
  ],
  "files_to_read": [
    "SKILL/business/teikan-drafter.md",
    "SKILL/business/touki-guide.md",
    "PROJECTS/miyabi-llc-setup.md"
  ],
  "estimated_tokens": 2100,
  "savings_vs_full": "95.1%"
}
```

**探索アルゴリズム**:

```
1. キーワードマッチ: タスク記述 → Agent.role / Skill.name でヒット
2. グラフ走査: ヒットしたノードから depth=N で隣接ノードを展開
3. スコアリング: 距離（近い=高）× 優先度（P0=高）× 関連度
4. カットオフ: top-K ノードを返却（デフォルト K=10）
5. ファイルパス化: ノードの path プロパティからファイル一覧を生成
```

**Cypher クエリ例**:

```cypher
-- タスク "定款を修正して" → キーワード "定款" にマッチするスキルを起点に探索
MATCH (s:Skill)
WHERE s.name CONTAINS '定款' OR s.name CONTAINS 'teikan'
WITH s
MATCH (a:Agent)-[:USES_SKILL]->(s)
OPTIONAL MATCH (s)-[:DEPENDS_ON]->(k:KnowledgeDoc)
OPTIONAL MATCH (s)-[:READS_DATA]->(d:DataSource)
RETURN a.name AS agent, s.name AS skill, s.path AS skill_path,
       collect(DISTINCT k.path) AS knowledge_paths,
       collect(DISTINCT d.path) AS data_paths
```

**推定工数**: 2-3日
**ファイル**: `bin/gitnexus-agent-context.sh`, `lib/context_resolver.py`

---

### Phase 3: Code-Agent Bridge（コードとエージェントの接続）

**成果物**: Skill → 実体コードファイルの `IMPLEMENTS_CODE` エッジ

```
SKILL/infra/gitnexus-*.md
  ↓ IMPLEMENTS_CODE
.claude/skills/gitnexus/*.md
  ↓ IMPLEMENTS_CODE
scripts/gitnexus-*.sh (実行コード)
  ↓ CALLS (既存GitNexus)
Function: _gitnexus()
```

これにより:
- 「gitnexusのreindex処理を改善したい」→ Skill(gitnexus-cli) → Code(scripts/gitnexus-auto-reindex.sh) → Function(_gitnexus)
- コードグラフとエージェントグラフがシームレスに接続

**実装**:
- `lib/agent_graph_builder.py` にスキル→コード解析を追加
- SKILL/*.md 内の `scripts:` / `files:` フロントマターからコードファイルを特定
- 既存GitNexusのコードシンボルとMERGE

**推定工数**: 1-2日

---

### Phase 4: MCP Integration（Claude Code統合）

**成果物**: `gni agent-context` をMCPツールとして公開

**Claude Codeからの利用イメージ**:

```
User: "定款を修正して"
  ↓
Claude Code (自動):
  1. gitnexus_agent_context({query: "定款を修正して"})
  2. → 返却: {files_to_read: ["SKILL/business/teikan-drafter.md", ...]}
  3. Read(各ファイル)  ← 必要なファイルだけ読む
  4. 作業実行
```

**CLAUDE.mdへの統合**:

```markdown
## Context Loading Protocol (P1)

タスク開始時、全コンテキストを読み込む代わりに:
1. `gitnexus_agent_context({query: "タスク記述"})` でグラフ探索
2. 返却された `files_to_read` のみを Read
3. 不足があれば `--depth 3` で再探索
```

**推定工数**: 1日

---

### Phase 5: Auto-Reindex & Sync（運用自動化）

**成果物**: Agent Graph の自動更新

```bash
# 既存 gitnexus-auto-reindex.sh を拡張
# コード変更 + SKILL/AGENTS/KNOWLEDGE変更 を検知して再インデックス

bin/gitnexus-agent-reindex.sh  # Agent Graph のみ再構築
bin/gitnexus-full-reindex.sh   # Code Graph + Agent Graph 両方
```

**トリガー**:
- `SKILL/*.md` 変更 → Agent Graph 再インデックス
- `AGENTS.md` 変更 → Agent Graph 再インデックス
- `KNOWLEDGE/` 変更 → KnowledgeDoc ノード更新
- git hook (post-commit) で自動判定

**推定工数**: 1日

---

## 4. ファイル構成（最終形）

```
gitnexus-stable-ops/
├── bin/
│   ├── gni                          # 既存 + agent-context コマンド追加
│   ├── gitnexus-agent-index.sh      # 🆕 Agent Graph インデクサ
│   ├── gitnexus-agent-context.sh    # 🆕 コンテキスト探索
│   ├── gitnexus-agent-reindex.sh    # 🆕 Agent Graph 自動更新
│   ├── gitnexus-auto-reindex.sh     # 既存
│   ├── gitnexus-doctor.sh           # 既存 + Agent Graph ヘルスチェック追加
│   ├── gitnexus-install-hooks.sh    # 既存 + SKILL/AGENTS 変更検知追加
│   ├── gitnexus-reindex-all.sh      # 既存
│   ├── gitnexus-reindex.sh          # 既存
│   ├── gitnexus-safe-impact.sh      # 既存
│   ├── gitnexus-smoke-test.sh       # 既存 + Agent Graph テスト追加
│   └── graph-meta-update.sh         # 既存
├── lib/
│   ├── common.sh                    # 既存
│   ├── parse_graph_meta.py          # 既存
│   ├── agent_graph_builder.py       # 🆕 Agent/Skill/Knowledge パーサ
│   └── context_resolver.py          # 🆕 グラフ探索 + スコアリング
├── schema/
│   └── agent-graph-schema.cypher    # 🆕 ノード・エッジ型定義
├── docs/
│   ├── architecture.md              # 更新: Agent Graph Layer 追記
│   ├── runbook.md                   # 更新: Agent Graph 運用手順追記
│   └── PLAN-agent-context-graph.md  # 🆕 このドキュメント
├── tests/
│   ├── test_common.sh               # 既存
│   ├── test_hooks.sh                # 既存
│   ├── test_agent_graph.sh          # 🆕 Agent Graph テスト
│   └── test_context_resolver.sh     # 🆕 Context Resolver テスト
└── examples/
    ├── env.example                  # 既存
    └── skill-template.md            # 🆕 SKILL フロントマター例
```

---

## 5. SKILL フロントマター規約

Agent Graph Indexer がパースするため、SKILL/*.md に以下のフロントマターを追加:

```yaml
---
name: teikan-drafter
category: business
version: 1.0.0
agents:
  - 法務
  - 確定申告
depends_on:
  - K_PROJECTS
reads:
  - miyabi-llc-setup/PROJECT_SPEC.md
writes: []
external_services: []
scripts:
  - scripts/miyabi-teikan.sh
keywords:
  - 定款
  - 社員総会
  - 事業目的
priority: P1
---
```

`keywords` フィールドが Context Resolver のマッチングに使われる。

---

## 6. 効果予測

### トークン削減シミュレーション

| シナリオ | 従来 | Agent Context Graph | 削減率 |
|---------|------|--------------------|----|
| 定款修正 | ~43,000 tokens | ~2,100 tokens | **95%** |
| GitNexus reindex | ~43,000 tokens | ~3,500 tokens | **92%** |
| タスク追加 | ~43,000 tokens | ~1,800 tokens | **96%** |
| PR作成 | ~43,000 tokens | ~4,200 tokens | **90%** |
| 健康データ分析 | ~43,000 tokens | ~2,800 tokens | **93%** |

### コンテキスト効率

```
Before: 作業可能トークン = 全体 - 43,000 (固定オーバーヘッド)
After:  作業可能トークン = 全体 - 2,000~4,000 (タスク依存)

→ 利用可能コンテキストが 2-3倍に拡大
→ より複雑なタスクを1セッションで完了可能
→ サブエージェント起動の必要性が減少
```

---

## 7. 実装スケジュール

| Phase | 内容 | 工数 | 依存 |
|-------|------|------|------|
| **Phase 1** | Agent Graph Indexer | 2-3日 | なし |
| **Phase 2** | Context Resolver | 2-3日 | Phase 1 |
| **Phase 3** | Code-Agent Bridge | 1-2日 | Phase 1 |
| **Phase 4** | MCP Integration | 1日 | Phase 2 |
| **Phase 5** | Auto-Reindex & Sync | 1日 | Phase 1 |

**合計**: 7-10日
**クリティカルパス**: Phase 1 → Phase 2 → Phase 4 (5-7日)

Phase 3 と Phase 5 は Phase 1 完了後に並行実行可能。

---

## 8. 技術的制約と対策

### 制約1: GitNexus の Cypher INSERT がサポートされていない可能性

**対策**: `gitnexus analyze` のカスタム入力として JSONL を供給する方法を調査。
不可能な場合は、Agent Graph を別 DB（SQLite FTS5）に保持し、`gni` で統合クエリを実行。

### 制約2: SKILL フロントマターが未整備

**対策**: Phase 0 として既存 58 SKILL ファイルにフロントマターを一括追加するスクリプトを作成。
`scripts/add-skill-frontmatter.sh` — AGENTS.md の routing_table から依存関係を推定して自動生成。

### 制約3: キーワードマッチの精度

**対策**: Phase 2 では BM25（テキストマッチ）を先行実装。
将来的に GitNexus の embedding 機能を有効化してセマンティック検索に移行。

### 制約4: GitNexus 本体の parser は変更しない（StableOps の Non-Goal）

**対策**: Agent Graph は StableOps 側のスクリプトで構築・注入する。
GitNexus 本体の変更は不要（Cypher 経由での読み書きのみ）。

---

## 9. 成功基準

| 指標 | 目標 |
|------|------|
| コンテキスト削減率 | > 80% (平均) |
| Context Resolver 応答時間 | < 3秒 |
| キーワードマッチ適合率 | > 70% (上位3件に正解含む) |
| Agent Graph ノード数 | 179+ (13 Agent + 71 Skill + 95 Knowledge) |
| Agent Graph エッジ数 | 127+ (既知の依存関係) |
| SKILL フロントマター整備率 | 100% (58/58) |

---

## 10. 将来展望

### v2: Semantic Context Retrieval

GitNexus embedding を有効化し、タスク記述のベクトル類似度でコンテキストを取得。
キーワードに依存しない柔軟な探索が可能に。

### v3: Dynamic Context Window Management

セッション中にコンテキストが不足した場合、自動的にグラフを再探索して追加コンテキストを読み込む。
「必要な時に必要な分だけ」の完全動的ロード。

### v4: Multi-Repo Agent Graph

複数リポジトリ（HAYASHI_SHUNSUKE, KOTOWARI, Gen-Studio等）のAgent Graphを統合。
クロスリポジトリの依存関係も可視化・探索可能に。

### v5: OpenClaw Integration

OpenClaw の 40 エージェント定義を Agent Graph に取り込み。
分散実行ノード（MainMini, MacMini2, Mini3, MacBook Pro）のトポロジーも表現。
