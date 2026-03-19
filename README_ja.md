# gitnexus-stable-ops

[English](./README.md) | [中文](./README_zh.md) | **日本語**

![Stars](https://img.shields.io/github/stars/ShunsukeHayashi/gitnexus-stable-ops?style=for-the-badge&color=yellow)
![License](https://img.shields.io/github/license/ShunsukeHayashi/gitnexus-stable-ops?style=for-the-badge)
![Last Commit](https://img.shields.io/github/last-commit/ShunsukeHayashi/gitnexus-stable-ops?style=for-the-badge)

**[GitNexus](https://github.com/abhigyanpatwari/GitNexus) を本番環境で安定運用するための運用ツールキット。固定バージョンの CLI/MCP ワークフローに対応。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Stars](https://img.shields.io/github/stars/ShunsukeHayashi/gitnexus-stable-ops?style=social)](https://github.com/ShunsukeHayashi/gitnexus-stable-ops)
[![GitHub Issues](https://img.shields.io/github/issues/ShunsukeHayashi/gitnexus-stable-ops)](https://github.com/ShunsukeHayashi/gitnexus-stable-ops/issues)
[![Last Commit](https://img.shields.io/github/last-commit/ShunsukeHayashi/gitnexus-stable-ops)](https://github.com/ShunsukeHayashi/gitnexus-stable-ops/commits/main)

[合同会社みやび (LLC Miyabi)](https://miyabi-ai.jp) が開発 — GitNexus でインデックスされた 25 以上のリポジトリを本番環境で管理しています。

---

## 課題

GitNexus は強力ですが、多数のリポジトリを本番環境で運用するといくつかの課題が生じます:

- **バージョンのずれ** — CLI と MCP が異なる GitNexus バージョン（KuzuDB vs LadybugDB）を参照し、データ破損を引き起こす
- **embedding の消失** — `analyze --force` を `--embeddings` なしで実行すると、既存の embedding がサイレントに削除される
- **dirty な worktree による破損** — コミットされていない変更を含んだ状態でインデックスを再構築すると、コードグラフが汚染される
- **impact の不安定性** — `impact` コマンドが断続的に失敗し、分析ワークフローがブロックされる

このツールキットはこれらすべてを解決します。

## 機能一覧

| スクリプト | 用途 |
|-----------|------|
| `bin/gni` | 読みやすい出力と impact フォールバック表示を備えた改良版 CLI ラッパー |
| `bin/gitnexus-doctor.sh` | バージョンのずれ、インデックスの健全性、MCP 設定を診断 |
| `bin/gitnexus-smoke-test.sh` | エンドツーエンドのヘルスチェック（analyze/status/list/context/cypher/impact） |
| `bin/gitnexus-safe-impact.sh` | 自動的な context ベースのフォールバック付き影響分析 |
| `bin/gitnexus-auto-reindex.sh` | スマートな単一リポジトリ再インデックス（stale 検出、embedding 保護） |
| `bin/gitnexus-reindex.sh` | 最近変更されたリポジトリのバッチ再インデックス（cron 対応） |
| `bin/gitnexus-reindex-all.sh` | 安全なデフォルト設定で全登録リポジトリを再インデックス |
| `bin/graph-meta-update.sh` | グラフ可視化用のクロスコミュニティエッジ JSONL を生成 |

## 前提条件

- `bash`, `git`, `jq`, `python3`
- `gitnexus` CLI がインストール済み（デフォルト: `~/.local/bin/gitnexus-stable`）

## インストール

### ワンライナー（推奨）

```bash
git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops.git
cd gitnexus-stable-ops
make install
```

これにより以下が実行されます:
- `bin/gni` を `~/.local/bin/gni` にシンボリックリンク
- すべてのスクリプトに実行権限を付与
- `~/.local/bin` が PATH に含まれていることを確認

### 手動インストール

```bash
git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops.git
cd gitnexus-stable-ops
ln -s $(PWD)/bin/gni ~/.local/bin/gni
chmod +x bin/*
```

## クイックスタート

```bash
# テストを実行
make test

# リポジトリを診断
bin/gitnexus-doctor.sh ~/dev/my-repo my-repo MyClassName

# スモークテストを実行
bin/gitnexus-smoke-test.sh ~/dev/my-repo my-repo MyClassName

# スマート再インデックス（インデックスが最新の場合はスキップ）
REPO_PATH=~/dev/my-repo bin/gitnexus-auto-reindex.sh

# 直近 24 時間以内に変更されたリポジトリをバッチ再インデックス
REPOS_DIR=~/dev bin/gitnexus-reindex.sh
```

## 安全なデフォルト設定

- **embedding 保護** — 既存の embedding があるリポジトリには自動的に `--embeddings` フラグが付与される
- **dirty な worktree のスキップ** — コミットされていない変更がある場合は再インデックスをスキップ（上書き: `ALLOW_DIRTY_REINDEX=1`）
- **impact フォールバック** — `impact` が失敗した場合、`gitnexus-safe-impact.sh` が context ベースの JSON を返す
- **バージョン固定** — すべてのスクリプトが `$GITNEXUS_BIN`（デフォルト: `~/.local/bin/gitnexus-stable`）を使用

## 環境変数

| 変数 | デフォルト値 | 用途 |
|------|------------|------|
| `GITNEXUS_BIN` | `~/.local/bin/gitnexus-stable` | 固定された GitNexus CLI のパス |
| `REGISTRY_PATH` | `~/.gitnexus/registry.json` | インデックス済みリポジトリの registry |
| `ALLOW_DIRTY_REINDEX` | `0` | dirty な worktree の再インデックスを許可 |
| `FORCE_REINDEX` | `1` | スモークテストで強制再インデックス |
| `REPOS_DIR` | `~/dev` | バッチ再インデックスのルートディレクトリ |
| `LOOKBACK_HOURS` | `24` | 変更をチェックする遡及時間 |
| `OUTPUT_DIR` | `./out` | グラフメタデータの出力ディレクトリ |

## cron との併用

```bash
# 毎日午前 3 時に再インデックス
0 3 * * * cd /path/to/gitnexus-stable-ops && REPOS_DIR=~/dev bin/gitnexus-reindex.sh

# 毎週月曜午前 4 時にフル再インデックス
0 4 * * 1 cd /path/to/gitnexus-stable-ops && bin/gitnexus-reindex-all.sh
```

## 互換性

| プラットフォーム | 状態 |
|----------------|------|
| macOS (Apple Silicon) | テスト済み（メイン開発プラットフォーム） |
| Linux (Ubuntu, Debian, Fedora) | テスト済み、サポート対象 |
| Windows | 非対応（WSL または Git Bash を使用してください） |

必要条件:
- Bash 4.0+
- Git 2.0+
- jq 1.6+
- Python 3.6+

## ドキュメント

- [Runbook](docs/runbook.md) — ステップバイステップの運用手順
- [Architecture](docs/architecture.md) — 設計原則とデータフロー

## コントリビューション

コントリビューションを歓迎します！ガイドラインについては [CONTRIBUTING.md](CONTRIBUTING.md) をご覧ください。

- [バグ報告](.github/ISSUE_TEMPLATE/bug_report.md)
- [機能リクエスト](.github/ISSUE_TEMPLATE/feature_request.md)
- Pull Request の送信

すべてのコントリビューションには以下が必要です:
- 新機能にはテストを含めること
- [Conventional Commits](https://www.conventionalcommits.org/) 形式に従うこと
- `make test` を通過すること

## 本番環境での実績

合同会社みやびの本番環境で運用中:
- **25 リポジトリ**をインデックス・監視
- ナレッジグラフに **32,000 以上のシンボル** / **73,000 以上のエッジ**
- cron による**毎日の自動再インデックス**
- このツールキット導入以降 **embedding の消失ゼロ**

## ライセンス

MIT — [LICENSE](LICENSE) をご覧ください。

---

## 開発者について

**林 駿甫 (Shunsuke Hayashi)** — 40 の AI Agent を運用する個人開発者。

- [miyabi-ai.jp](https://www.miyabi-ai.jp)
- X/Twitter: [@The_AGI_WAY](https://x.com/The_AGI_WAY)
- GitHub: [@ShunsukeHayashi](https://github.com/ShunsukeHayashi)

役に立ったら Star をお願いします！
