# MCP Integration Guide — Agent Context Graph

> Phase 4: Claude Code から `agent-context` をMCPツールとして利用する

## セットアップ

### 1. Claude Code settings.json に追加

```json
{
  "mcpServers": {
    "gitnexus-agent": {
      "command": "python3",
      "args": ["/path/to/gitnexus-stable-ops/lib/mcp_server.py"],
      "env": {
        "GITNEXUS_AGENT_REPO": "/path/to/HAYASHI_SHUNSUKE"
      }
    }
  }
}
```

### 2. Agent Graph をビルド（初回のみ）

```bash
gni agent-index /path/to/HAYASHI_SHUNSUKE
```

### 3. 動作確認

```bash
# MCP サーバーをテスト起動
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | \
  GITNEXUS_AGENT_REPO=/path/to/HAYASHI_SHUNSUKE \
  python3 lib/mcp_server.py
```

## 利用可能なツール

### `gitnexus_agent_context`

タスク記述から関連するコンテキストを探索し、読むべきファイルを返す。

```json
{
  "query": "定款を修正して",
  "depth": 2,
  "max_tokens": 5000,
  "task_type": "feature",
  "format": "json"
}
```

**レスポンス例:**
```json
{
  "query": "定款を修正して",
  "matched_agents": [],
  "matched_skills": [],
  "context_chain": [
    {
      "type": "KnowledgeDoc",
      "name": "Ambitious AI株式会社 定款 参考資料",
      "score": 0.442,
      "depth": 0,
      "path": "KNOWLEDGE/ambitious-ai-定款-参考資料.md",
      "token_estimate": 3033
    }
  ],
  "files_to_read": ["KNOWLEDGE/ambitious-ai-定款-参考資料.md"],
  "estimated_tokens": 3033,
  "savings_vs_full": "98.3%"
}
```

### `gitnexus_agent_status`

Agent Graph の統計情報を返す。

```json
{
  "nodes": {"Agent": 5, "Skill": 74, "KnowledgeDoc": 78},
  "total_nodes": 216,
  "total_edges": 30,
  "db_size_kb": 212.0
}
```

### `gitnexus_agent_list`

ノード一覧を返す。`node_type` でフィルタ可能。

```json
{
  "node_type": "Skill"
}
```

## Context Loading Protocol

CLAUDE.md に以下を追加することで、Claude Code がタスク開始時に自動的にグラフ探索を使用する。

```markdown
## Context Loading Protocol (P1)

タスク開始時、全コンテキストを読み込む代わりに:
1. `gitnexus_agent_context({query: "タスク記述"})` でグラフ探索
2. 返却された `files_to_read` のみを Read
3. 不足があれば `--depth 3` で再探索
```

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `GITNEXUS_AGENT_REPO` | 対象リポジトリパス | CWD |
| `GITNEXUS_AGENT_DB` | DBファイルパス | `REPO/.gitnexus/agent-graph.db` |
| `DEBUG` | デバッグログ有効化 | (未設定) |
| `GITNEXUS_AGENT_REINDEX` | Git hook 自動reindex | `1` |

## 自動再ビルド（Phase 5）

Git hooks が SKILL/, KNOWLEDGE/, AGENTS.md の変更を検知し、自動で Agent Graph を再ビルドする。

```bash
# hooks をインストール
make install-hooks REPO=/path/to/HAYASHI_SHUNSUKE

# 手動で再ビルド
gni agent-reindex /path/to/HAYASHI_SHUNSUKE

# 強制再ビルド
gni agent-reindex /path/to/HAYASHI_SHUNSUKE --force

# 自動再ビルドを無効化
export GITNEXUS_AGENT_REINDEX=0
```
