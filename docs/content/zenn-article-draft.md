---
title: "GitNexusを25リポで本番運用して分かった4つの落とし穴と解決策"
emoji: "🔧"
type: "tech"
topics: ["GitNexus", "CLI", "開発ツール", "コードインテリジェンス", "自動化"]
published: false
---

## GitNexus とは

[GitNexus](https://github.com/abhigyanpatwari/GitNexus)（作者: abhigyanpatwari 氏）は、コードベースをナレッジグラフとして解析するツールです。関数・クラス・モジュールといったシンボルの関係を graph DB（LadybugDB）に格納し、自然言語での検索や影響分析を可能にします。

```bash
# インデックス作成
npx gitnexus analyze

# 自然言語検索
npx gitnexus query "auth flow"

# 影響分析
npx gitnexus impact --target validateUser
```

さらに MCP Server として Claude Code 等の AI エージェントから直接呼び出せる点が強力です。コードを読まなくても「この関数を変えると何が壊れるか」が数秒で分かります。

単一リポジトリで試す分には非常に快適です。しかし、複数リポジトリを本番環境で継続運用し始めると、静かに、しかし確実に問題が起きてきます。

---

## なぜ本番運用で問題が起きるのか

GitNexus の基本設計は「1リポジトリをローカルで解析する」ことに最適化されています。`analyze` して `query` する——この単純なユースケースなら何も問題ありません。

問題は **スケール** と **継続運用** です。

- リポジトリが増えるほど、インデックスの鮮度管理が難しくなる
- CLI と MCP Server を別々にインストールしていると、バージョンが乖離する
- CI/CD や cron で自動再インデックスを走らせると、副作用が出る
- `gitnexus impact` が断続的に失敗すると、ワークフロー全体がブロックされる

私自身、25リポジトリ・32K以上のシンボル・73K以上のエッジという規模で本番運用し、これらの問題に一つずつ直面しました。その経験から生まれたのが **[gitnexus-stable-ops](https://github.com/ShunsukeHayashi/gitnexus-stable-ops)** です。

---

## 4つの落とし穴

### 落とし穴 1: Version drift（バージョンのずれ）

**何が起きるか**

GitNexus の CLI と MCP Server を別々の方法でインストールしていると、気づかないうちに異なるバージョンを参照します。古い CLI は KuzuDB 形式のインデックスを生成し、新しい MCP Server は LadybugDB 形式を期待する——この組み合わせでグラフが破損します。

エラーメッセージも分かりづらく、「index not found」や「unexpected schema」といった出力になるため、バージョンずれが原因だと気づくまでに時間がかかります。

```bash
# 問題: グローバルの gitnexus（新）と、MCPが参照する gitnexus（旧）が違う
$ gitnexus --version
v0.9.2  # LadybugDB時代

$ cat ~/.codex/config.toml | grep gitnexus
command = "/usr/local/bin/gitnexus"  # 別のバージョン
```

**解決策**

`gitnexus-stable-ops` では、全スクリプトが `$GITNEXUS_BIN`（デフォルト: `~/.local/bin/gitnexus-stable`）という単一のバイナリを参照します。CLI も MCP も同じバイナリを向けることで、バージョンずれを構造的に排除します。

```bash:bin/gitnexus-doctor.sh（抜粋）
GITNEXUS_BIN="${GITNEXUS_BIN:-$HOME/.local/bin/gitnexus-stable}"

stable_version="$("$GITNEXUS_BIN" --version)"
global_version="$(command -v gitnexus >/dev/null 2>&1 && gitnexus --version 2>/dev/null || echo 'unavailable')"

echo "stable_version: $stable_version"
echo "global_version: $global_version"
```

`gitnexus-doctor.sh` を実行すると、stable バイナリとグローバルの `gitnexus` のバージョンを並べて表示します。ずれていれば即座に検知できます。

:::message alert
**`.gitnexus/kuzu` が残っている場合は stale な旧インデックス**です。`gitnexus-doctor.sh` はこのファイルを検知して警告します。削除してから再インデックスしてください。
:::

---

### 落とし穴 2: Embedding loss（embedding の消失）

**何が起きるか**

`npx gitnexus analyze --force` を実行すると、インデックスは新しくなります。しかし `--embeddings` フラグを付け忘れると、**既存の embedding が静かに消えます**。

embedding の生成には時間とコストがかかります（OpenAI API を使う場合）。それが `--force` 一発で消えるのは見落とされやすい罠です。`gitnexus status` を見ても `embeddings: 0` になるだけで、エラーは出ません。

```bash
# NG: embedding が消える
npx gitnexus analyze --force

# OK: embedding を保護しながら再インデックス
npx gitnexus analyze --force --embeddings
```

**解決策**

`gitnexus-auto-reindex.sh` は再インデックス前に `meta.json` を確認し、embedding が存在すれば自動的に `--embeddings` フラグを付与します。

```bash:bin/gitnexus-auto-reindex.sh（抜粋）
# meta.json から embedding 数を確認
embedding_count=$(jq '.stats.embeddings // 0' "$META_FILE" 2>/dev/null || echo 0)

if (( embedding_count > 0 )); then
  ANALYZE_FLAGS="--force --embeddings"
  log INFO "Embeddings detected ($embedding_count), preserving with --embeddings"
else
  ANALYZE_FLAGS="--force"
fi
```

:::message
**`meta.json` の `stats.embeddings` フィールドで embedding 数を確認できます。** `0` なら embedding はありません。`gitnexus-doctor.sh` もこの値を表示します。
:::

---

### 落とし穴 3: Dirty worktree corruption（未コミット変更によるグラフ汚染）

**何が起きるか**

未コミットの変更がある状態（dirty worktree）でインデックスを再構築すると、作業中の中途半端なコードがグラフに取り込まれます。

- 削除予定の関数がグラフに残る
- リファクタリング中の関数が「存在する」として影響分析に含まれる
- コミット後に再インデックスしても、汚染されたエッジが残ることがある

特に複数の開発者が並行して作業している環境や、cron で自動再インデックスを走らせている環境で問題になります。

**解決策**

全スクリプトでデフォルトとして dirty worktree を検知したらスキップします。

```bash:lib/common.sh（抜粋）
is_dirty_worktree() {
  local repo_path="$1"
  if git -C "$repo_path" diff --quiet && git -C "$repo_path" diff --cached --quiet; then
    return 1  # clean
  fi
  return 0  # dirty
}
```

```bash:bin/gitnexus-auto-reindex.sh（抜粋）
if is_dirty_worktree "$REPO_PATH" && [[ "${ALLOW_DIRTY_REINDEX:-0}" != "1" ]]; then
  log WARN "Dirty worktree detected, skipping reindex. Set ALLOW_DIRTY_REINDEX=1 to override."
  exit 0
fi
```

どうしても dirty な状態でインデックスしたい場合は、明示的に環境変数を設定します。

```bash
# 明示的な上書き（非推奨）
ALLOW_DIRTY_REINDEX=1 bin/gitnexus-auto-reindex.sh
```

:::message alert
**cron で自動再インデックスを走らせる場合、`ALLOW_DIRTY_REINDEX` のデフォルトは `0` のまま維持してください。** 開発中リポジトリを誤ってインデックスするリスクがあります。
:::

---

### 落とし穴 4: Impact instability（影響分析の不安定な失敗）

**何が起きるか**

`gitnexus impact --repo REPO_NAME SYMBOL_NAME` は断続的に失敗します。グラフの状態やシンボルの複雑さによって、成功したり `exit 1` になったりします。これをそのまま CI や自動化スクリプトに組み込むと、処理全体がブロックされます。

```bash
# ときどき失敗する
$ gitnexus impact --repo my-repo validateUser
Error: Failed to resolve impact graph
```

**解決策**

`gitnexus-safe-impact.sh` は `impact` が失敗した場合に自動的に `context` コマンドベースのフォールバックを実行します。`impact` の出力が不正な JSON でも、`context` の incoming/outgoing refs から近似的な影響サマリーを生成します。

```bash:bin/gitnexus-safe-impact.sh（抜粋）
set +e
impact_output="$("$GITNEXUS_BIN" impact --repo "$REPO_NAME" "$SYMBOL_NAME" 2>&1)"
impact_status=$?
set -e

if [[ $impact_status -eq 0 ]] && echo "$impact_output" | jq -e 'type == "object" and (.error? == null)' >/dev/null 2>&1; then
  echo "$impact_output"
  exit 0
fi

echo "WARN: impact failed, falling back to context-based summary" >&2

# context コマンドのフォールバック
context_output="$("$GITNEXUS_BIN" context --repo "$REPO_NAME" "$SYMBOL_NAME" 2>&1)"
echo "$context_output" | jq --arg direction "$DIRECTION" '...'
```

```bash
# 使い方: impact が失敗しても終了コード 0 で JSON を返す
bin/gitnexus-safe-impact.sh my-repo validateUser upstream
```

:::message
**`gitnexus-safe-impact.sh` の出力は常に JSON です。** Claude Code などの MCP 経由呼び出しと組み合わせる場合、`impact` 失敗を透過的に処理できます。
:::

---

## gitnexus-stable-ops のスクリプト構成

```
gitnexus-stable-ops/
├── bin/
│   ├── gni                       # 読みやすい出力の CLI ラッパー
│   ├── gitnexus-doctor.sh        # バージョンずれ・インデックス健全性診断
│   ├── gitnexus-smoke-test.sh    # E2E ヘルスチェック
│   ├── gitnexus-safe-impact.sh   # フォールバック付き影響分析
│   ├── gitnexus-auto-reindex.sh  # スマート単一リポジトリ再インデックス
│   ├── gitnexus-reindex.sh       # バッチ再インデックス（cron向け）
│   ├── gitnexus-reindex-all.sh   # 全リポジトリ再インデックス
│   └── gitnexus-install-hooks.sh # Git hooks インストーラー
├── lib/
│   ├── common.sh                 # 共通関数（is_dirty_worktree 等）
│   └── parse_graph_meta.py       # グラフメタデータパーサー
├── hooks/
│   ├── post-commit               # コミット時自動再インデックス
│   └── post-merge                # マージ時自動再インデックス
└── docs/
    └── runbook.md                # 運用手順書
```

### インストール

```bash:インストール手順
git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops.git
cd gitnexus-stable-ops
make install
```

これで `gni` が `~/.local/bin/gni` にシンボリックリンクされ、全スクリプトに実行権限が付与されます。

---

## cron で完全自動化する

25リポジトリを毎日自動再インデックスする cron 設定です。

```bash:crontab
# 毎日午前3時: 直近24時間で変更されたリポジトリを再インデックス
0 3 * * * cd /path/to/gitnexus-stable-ops && REPOS_DIR=~/dev LOOKBACK_HOURS=24 bin/gitnexus-reindex.sh >> /var/log/gitnexus-reindex.log 2>&1

# 毎週月曜午前4時: 全リポジトリの完全再インデックス
0 4 * * 1 cd /path/to/gitnexus-stable-ops && bin/gitnexus-reindex-all.sh >> /var/log/gitnexus-reindex-all.log 2>&1
```

`gitnexus-reindex.sh` は `LOOKBACK_HOURS` 以内に git コミットがあったリポジトリだけを対象にするので、変更のないリポジトリを無駄にインデックスしません。

### 環境変数一覧

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `GITNEXUS_BIN` | `~/.local/bin/gitnexus-stable` | 使用する GitNexus CLI のパス |
| `REGISTRY_PATH` | `~/.gitnexus/registry.json` | インデックス済みリポジトリの一覧 |
| `ALLOW_DIRTY_REINDEX` | `0` | dirty worktree の再インデックスを許可 |
| `REPOS_DIR` | `~/dev` | バッチ再インデックスのルートディレクトリ |
| `LOOKBACK_HOURS` | `24` | 変更をチェックする遡及時間（時間） |

---

## v1.2.0: Git hooks でコミット時に自動再インデックス

v1.2.0 から Git hooks に対応しました。コミットやマージのタイミングで自動的にインデックスを更新できます。

```bash:Git hooks のインストール
# 対象リポジトリに hooks をインストール
make install-hooks REPO=~/dev/my-repo

# または直接
bin/gitnexus-install-hooks.sh ~/dev/my-repo
```

インストールされる hooks:

- `post-commit`: コミット後に `gitnexus-auto-reindex.sh` を非同期実行
- `post-merge`: マージ後に同様の処理を実行

既存の hooks がある場合は `.bak` としてバックアップされるので、既存の設定を壊しません。

```bash:hooks/post-commit（生成されるhookの例）
#!/usr/bin/env bash
# GitNexus auto-reindex hook (managed by gitnexus-stable-ops)
GITNEXUS_STABLE_OPS="${GITNEXUS_STABLE_OPS:-$HOME/gitnexus-stable-ops}"
REPO_PATH="$(git rev-parse --show-toplevel)"

# バックグラウンドで実行（コミット操作をブロックしない）
REPO_PATH="$REPO_PATH" "$GITNEXUS_STABLE_OPS/bin/gitnexus-auto-reindex.sh" &
```

:::message
**hooks はコミット操作をブロックしません。** バックグラウンドで非同期実行されるため、`git commit` の速度に影響しません。
:::

---

## Production Stats

本番環境での実績数値です。

| 指標 | 値 |
|------|----|
| インデックス済みリポジトリ | **25** |
| ナレッジグラフのシンボル数 | **32,000+** |
| グラフのエッジ数 | **73,000+** |
| cron 自動再インデックス | 毎日実行 |
| このツールキット導入以降の embedding 消失件数 | **0** |

`gitnexus-doctor.sh` を定期実行することで、バージョンずれやインデックス破損を早期検知できています。

---

## まとめ

GitNexus 単体は非常に強力なツールです。しかし本番環境・複数リポジトリでの継続運用には、以下の4点に注意が必要です。

1. **CLI と MCP を同一バイナリに向ける**（version drift 防止）
2. **再インデックス時は常に embedding の有無を確認してから `--embeddings` を付ける**
3. **dirty worktree はデフォルトでスキップする**
4. **`impact` コマンドの失敗に備えたフォールバックを用意する**

[gitnexus-stable-ops](https://github.com/ShunsukeHayashi/gitnexus-stable-ops) はこれらを Shell スクリプトとして実装し、cron や Git hooks と組み合わせて完全自動化します。インストールは `make install` の一行です。

GitNexus 本家の素晴らしい設計の上に、本番運用の安定性を加えるレイヤーとして使ってみてください。

**リポジトリ**: https://github.com/ShunsukeHayashi/gitnexus-stable-ops

GitNexus 本家: https://github.com/abhigyanpatwari/GitNexus
