# Workspace Manifest Schema — `.gitnexus/workspace.json`

## 概念

ワークスペースマニフェストは「このディレクトリが包括する構造」を宣言する設定ファイルです。
以下の5つを一般的な語彙で記述します：

| セクション | 意味 |
|-----------|------|
| `symlinks` | シンボリックリンク先（別リポジトリ・外部フォルダ）|
| `sub_repos` | サブリポジトリ（PROJECTS/ 配下の git repos）|
| `nodes` | 計算リソース（PC・VM・コンテナ・クラウドインスタンス）|
| `services` | ノード上で動くサービス（エージェント・サーバー・ワーカー）|
| `knowledge_refs` | ナレッジ・スキル・メモリのディレクトリ定義 |

---

## スキーマ

```jsonc
{
  // --- メタ情報 ---
  "version": "1.1",
  "workspace_root": "MY_WORKSPACE",          // 識別子（任意の文字列）
  "description": "説明文",

  // --- ローカルファイル構造 ---
  "symlinks": [
    {
      "name": "external-repo",               // このワークスペース内での表示名
      "resolved": "/absolute/path/to/repo",  // 実際のパス
      "description": "説明",
      "index": true,                         // GNIインデックス対象か
      "register_as": "repo-name"             // GNIレジストリ登録名（null可）
    }
  ],

  "sub_repos": [
    {
      "name": "my-sub-project",
      "path": "PROJECTS/my-sub-project",     // workspace_root からの相対パス
      "auto_index": true                     // gni workspace-analyze で自動インデックスか
    }
  ],

  // --- 計算ノード（マシン/VM/コンテナ） ---
  "nodes": [
    {
      "id": "gateway",                       // 一意のID（services から参照）
      "name": "My Gateway Server",           // 表示名
      "role": "gateway",                     // gateway | primary | worker | <任意文字列>
      "os": "linux",                         // linux | macos | windows

      "access": {                            // アクセス方法（ツール非依存）
        "type": "ssh",                       // local | ssh | http | custom
        "host": "myserver",                  // SSH host alias / hostname
        "port": 22,                          // optional
        "user": "ubuntu"                     // optional
      },

      "network": {                           // ネットワーク情報（optional）
        "ip": "192.168.1.10",                // プライベートIP・VPN IP等
        "labels": {                          // 自由キーバリュー
          "vpn": "wireguard",
          "datacenter": "home-lab"
        }
      },

      "workspace_root": "/home/ubuntu/work", // このノード上のワークスペースパス
      "services": ["svc-orchestrator"],      // このノードで動くサービスIDリスト

      "labels": {                            // 自由メタデータ（ツール固有情報はここに）
        "node_version": "v22.0.0",
        "my_tool_version": "1.2.3"
      }
    }
  ],

  // --- サービス（エージェント・サーバー・ワーカー等） ---
  "services": [
    {
      "id": "svc-orchestrator",
      "name": "Main Orchestrator",
      "type": "agent",                       // agent | server | database | worker | <任意>
      "node": "gateway",                     // 実行ノードID
      "description": "メインのオーケストレーターエージェント",

      "knowledge_refs": [                    // 参照するナレッジパス
        "KNOWLEDGE/",
        "KNOWLEDGE/context/system.md"
      ],
      "memory_refs": [                       // 参照するメモリパス
        "MEMORY/"
      ],
      "skill_refs": [                        // 参照するスキルパス
        "SKILL/infra/",
        "SKILL/personal/"
      ],

      "labels": {                            // 自由メタデータ
        "model": "claude-sonnet-4-6",
        "heartbeat_interval": "6h"
      }
    }
  ],

  // --- ナレッジ・スキル・メモリのディレクトリマッピング ---
  "knowledge_refs": {
    "skills_dir": "SKILL",
    "memory_dir": "MEMORY",
    "knowledge_dir": "KNOWLEDGE",
    "scripts_dir": "scripts",
    "config_dir": "config"
  },

  // --- クラスター全体情報（複数ノード使用時のみ、optional） ---
  "cluster": {
    "name": "My Cluster",
    "topology": "hub-spoke",               // hub-spoke | mesh | star | single
    "transport": "ssh",                    // ssh | vpn | local | http
    "total_services": 10,
    "labels": {                            // ツール固有情報はここに
      "vpn_type": "tailscale",
      "tailnet": "my-tailnet.ts.net",
      "gateway_url": "wss://my-gateway:443"
    }
  },

  // --- インデックスポリシー ---
  "index_policy": {
    "follow_symlinks_in_manifest": true,
    "skip_symlinks_not_in_manifest": true,
    "cross_workspace_edges": true
  }
}
```

---

## 最小構成（シングルマシン）

```jsonc
{
  "version": "1.1",
  "workspace_root": "MY_PROJECT",
  "symlinks": [],
  "sub_repos": [],
  "nodes": [],
  "services": []
}
```

## 用途別テンプレート

### パターンA: 外部リポジトリを包括するモノレポ

```jsonc
{
  "version": "1.1",
  "workspace_root": "monorepo",
  "symlinks": [
    { "name": "shared-lib", "resolved": "/path/to/shared-lib", "index": true, "register_as": "shared-lib" }
  ],
  "sub_repos": [
    { "name": "service-a", "path": "services/service-a", "auto_index": true }
  ],
  "nodes": [],
  "services": []
}
```

### パターンB: ローカルエージェント開発環境

```jsonc
{
  "version": "1.1",
  "workspace_root": "my-ai-workspace",
  "symlinks": [],
  "sub_repos": [],
  "nodes": [
    {
      "id": "local",
      "name": "MacBook Pro",
      "role": "primary",
      "os": "macos",
      "access": { "type": "local" },
      "workspace_root": "/Users/me/workspace",
      "services": ["agent-1", "agent-2"]
    }
  ],
  "services": [
    {
      "id": "agent-1",
      "name": "My AI Agent",
      "type": "agent",
      "node": "local",
      "skill_refs": ["SKILL/"],
      "memory_refs": ["MEMORY/"]
    }
  ]
}
```

### パターンC: SSH接続マルチマシンクラスター

```jsonc
{
  "version": "1.1",
  "workspace_root": "my-cluster-workspace",
  "nodes": [
    {
      "id": "head",
      "role": "gateway",
      "access": { "type": "ssh", "host": "head-node" },
      "services": ["orchestrator"]
    },
    {
      "id": "worker-1",
      "role": "worker",
      "access": { "type": "ssh", "host": "worker-1" },
      "services": ["worker-svc-1"]
    }
  ],
  "cluster": {
    "topology": "hub-spoke",
    "transport": "ssh"
  }
}
```
