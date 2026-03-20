# GitNexus Agent Context Graph — 統合レビューレポート

> **文書番号**: GNX-ACG-REV-001
> **バージョン**: 1.0.0
> **日付**: 2026-03-20
> **対象文書**: PLAN-agent-context-graph.md, REQUIREMENTS-agent-context-graph.md
> **レビュー参加エージェント**: 8/42（OpenClaw MAS）

---

## 1. レビュー参加エージェント一覧

| # | エージェント | ノード | 観点 | 評価 |
|---|------------|--------|------|------|
| 1 | dev-architect | MainMini | アーキテクチャ設計 | ✅ 承認（条件付き） |
| 2 | guardian | MainMini | セキュリティ | ✅ 承認（懸念あり） |
| 3 | promptpro | MacMini2 | プロンプト最適化 | ✅ 肯定的評価 |
| 4 | dev-reviewer | MainMini | コードレビュー | ⚠️ 7件の懸念点 |
| 5 | dev-tester | MainMini | テスト戦略 | ⚠️ 7件の推奨事項 |
| 6 | kotowari-dev | MacBook Pro | 実装（SQLite/Node.js） | ✅ 詳細な実装指針 |
| 7 | sigma | MainMini | データ分析（BM25） | ✅ パラメータ分析完了 |
| 8 | cc-hayashi | MacBook Pro | Claude Code統合 | ✅ 統合手順提示 |

---

## 2. 総合評価

### 2.1 全体判定: **承認（条件付き実装開始可）**

8エージェント中、重大なブロッカーを報告したエージェントはゼロ。
全エージェントが設計の妥当性を認めつつ、実装時の注意点を指摘。

### 2.2 コンセンサスポイント（全員一致）

| # | ポイント | 関連エージェント |
|---|---------|----------------|
| C1 | AgentRelation/CodeRelation テーブル分離は必須 | dev-architect, dev-reviewer, kotowari-dev |
| C2 | BM25デフォルト(k1=1.2, b=0.75)は初期値として妥当 | sigma, dev-tester |
| C3 | 95%トークン削減は野心的だが情報欠落リスクに注意 | dev-reviewer, cc-hayashi |
| C4 | FTS5とグラフクエリの明確な分離が必要 | kotowari-dev, sigma |
| C5 | テストにはグランドトゥルースデータセットが不可欠 | dev-tester, sigma |
| C6 | セキュリティ（パスのみ格納、PRIVATE除外）は適切 | guardian, dev-reviewer |
| C7 | フォールバック（R5 Communityノード拡張）は有効 | dev-architect, kotowari-dev |

---

## 3. エージェント別レビュー要約

### 3.1 dev-architect（アーキテクチャ）

**総合評価**: "robust and strategic approach"（堅牢で戦略的なアプローチ）

**肯定的評価**:
- AgentRelation/CodeRelation分離を **強く推奨**
- LadybugDB カスタムノード注入は実行可能
- R5 Communityノード拡張は有効なフォールバック

**懸念点**:
- LadybugDB のカスタムノード注入のスムーズさ（Cypher CREATE でカスタムラベルがサポートされるか）

### 3.2 guardian（セキュリティ）

**総合評価**: "appropriate security design"（適切なセキュリティ設計）

**肯定的評価**:
- パスのみ格納（コンテンツ非格納）
- PRIVATE ディレクトリの除外
- API キー非格納
- テーブル分離設計

**懸念点**:
- 実装の厳密性（設計と実装の乖離リスク）
- グラフDB アクセス制御（将来的なマルチユーザー対応時）
- メタデータ漏洩の可能性

### 3.3 promptpro（プロンプト最適化）

**総合評価**: "非常に効果的なプロンプト最適化戦略"

**肯定的評価**:
- 全社ナレッジグラフシステム（2026-03-17構築済み）が基盤として活用可能
- agent-views.json（10エージェントビュー）との連携で文脈提供が強化
- prompt-request-bus v2 との統合可能性
- 自動再インデックスによる情報鮮度維持

**提案**:
- 既存のナレッジグラフシステムとの統合を優先検討

### 3.4 dev-reviewer（コードレビュー）

**7件の懸念点**:

| # | 懸念 | 重要度 | 対策提案 |
|---|------|--------|---------|
| R1 | データモデルとスキーマの整合性 | HIGH | マイグレーション戦略を事前定義 |
| R2 | コンテキスト探索のスケーラビリティ | HIGH | インデックス戦略とキャッシュ機構 |
| R3 | 情報欠落リスク（95%削減は野心的） | HIGH | 段階的削減とフィードバックループ |
| R4 | SKILLファイルパースの堅牢性 | MEDIUM | バリデーション+エラーハンドリング |
| R5 | gni CLI のユーザビリティ | MEDIUM | 既存コマンド体系との一貫性 |
| R6 | セキュリティとアクセス制御 | MEDIUM | 機密ノードのフィルタリング |
| R7 | テスト計画の具体性 | MEDIUM | カバレッジ目標を明確化 |

### 3.5 dev-tester（テスト戦略）

**7件の推奨事項**:

| # | 推奨事項 | 優先度 |
|---|---------|--------|
| T1 | 本番相当のテストデータセット構築 | P0 |
| T2 | 負荷テスト（JMeter/Locust検討） | P1 |
| T3 | 精度テスト用グランドトゥルース作成 | P0 |
| T4 | エッジケース・障害シナリオテスト | P1 |
| T5 | CI/CD パイプラインへの組み込み | P1 |
| T6 | Cypher EXPLAIN による実行計画評価 | P2 |
| T7 | セキュリティテスト（認可・認証） | P2 |

### 3.6 kotowari-dev（実装：SQLite/Node.js）

**FTS5共存の実装指針**:
- FTS5はノードのテキストコンテンツ検索に限定
- グラフ構造はLadybugDBネイティブリレーションで管理
- クエリ分離: FTS5(`MATCH`)とグラフクエリ（リレーショナル結合）を明確に分ける
- FTS5で絞り込み → グラフクエリに渡す段階的アプローチ推奨

**スキーマ設計の提案**:
- Agent: `agent_id`, `name`, `type`, `description`, `config_path`
- Skill: `skill_id`, `name`, `description`, `version`, `location`, `tags`
- KnowledgeDoc: `doc_id`, `title`, `content_summary`, `file_path`, `type`, `last_modified_date`
- AgentRelation: `relation_id`, `source_agent_id`, `target_node_id`, `target_node_type`, `relation_type`, `timestamp`

**Node.js実装の注意点**:
- `better-sqlite3` 推奨（同期API、FTS5対応）
- SQLiteの書き込みロック管理（バッチ処理推奨）
- `async/await` + Promise ベースの設計
- クエリビルダ検討（knex.js等）

### 3.7 sigma（BM25パラメータ分析）

**BM25デフォルト値の評価**:

| パラメータ | デフォルト | 評価 | 調整の必要性 |
|-----------|----------|------|------------|
| k1 | 1.2 | 初期値として妥当 | ノード長の多様性次第 |
| b | 0.75 | 初期値として妥当 | 簡潔なSkillが多い場合は b→1.0 検討 |

**ハイブリッドスコアリング関数の提案**:

```
Final_Score = (w_text × BM25_Score) + (w_graph × f(BFS_Depth)) + (w_type × Node_Type_Weight)
```

- `w_text`, `w_graph`, `w_type`: テキスト/グラフ/ノードタイプの重み
- `f(BFS_Depth)`: `1 / (BFS_Depth + 1)` — 近いノードを優先
- `Node_Type_Weight`: Agent/Skill/KnowledgeDoc の種別重み

**最適化基準**:
- Precision/Recall 計測
- MAP（Mean Average Precision）
- グランドトゥルースデータセット必須
- A/Bテストによる反復改善

### 3.8 cc-hayashi（Claude Code統合）

**コンテキスト抽出の最適化**:
- タスクタイプ別クエリ（バグ修正/新機能/リファクタリング）
- 関連性閾値の設定
- 依存関係探索深度の制御
- 動的コンテキスト拡張（初回不足時の再取得）

**構造化出力の設計**:
```markdown
# Task Description
{Issue #123 Title}

# Relevant Code (file: path/to/file.py)
```python
def some_function(...):
    # ...
```

# Related Issues
- Issue #456: Previous bug in related module
```

**Claude Code CLI 統合**:
```bash
TASK_PROMPT="Fix the bug.\n\nContext:\n$(gni agent-context --task-id <ID>)"
claude --permission-mode bypassPermissions --print "${TASK_PROMPT}"
```

**エラーハンドリング**:
- コンテキスト抽出失敗時のフォールバック（汎用コンテキスト）
- Claude Code側に「情報不足なら報告」するプロンプト設計
- 実行ログの詳細記録

---

## 4. リスクマトリクス（レビュー統合）

| # | リスク | 重要度 | 発生確率 | 指摘元 | 対策 |
|---|--------|--------|---------|--------|------|
| R1 | LadybugDBカスタムノード注入の互換性 | HIGH | MEDIUM | dev-architect | R5フォールバック準備済み |
| R2 | 95%トークン削減による情報欠落 | HIGH | HIGH | dev-reviewer, cc-hayashi | 段階的削減 + フィードバックループ |
| R3 | BFS+BM25の大規模グラフでの性能劣化 | MEDIUM | LOW | dev-reviewer, sigma | キャッシュ + 探索深度制限 |
| R4 | SKILLフロントマターのパース不備 | MEDIUM | MEDIUM | dev-reviewer, kotowari-dev | バリデーション + エラーハンドリング |
| R5 | SQLite書き込みロック競合 | MEDIUM | LOW | kotowari-dev | バッチ処理 + トランザクション管理 |
| R6 | メタデータからの機密情報漏洩 | LOW | LOW | guardian | パスのみ格納ポリシー厳守 |
| R7 | テストカバレッジ不足 | MEDIUM | MEDIUM | dev-tester | グランドトゥルース + CI/CD組込 |

---

## 5. 実装への推奨事項（レビュー統合）

### Phase 1 に反映すべき事項

1. **AgentRelation テーブルを CodeRelation と完全分離**（C1: 全員一致）
2. **FTS5 はテキスト検索に限定、グラフ走査は別クエリ**（kotowari-dev）
3. **SKILL フロントマターのバリデーション強化**（dev-reviewer R4）
4. **better-sqlite3 の採用検討**（kotowari-dev）

### Phase 2 に反映すべき事項

5. **ハイブリッドスコアリング関数の採用**（sigma）
   ```
   Final_Score = (w_text × BM25) + (w_graph × 1/(depth+1)) + (w_type × TypeWeight)
   ```
6. **段階的トークン削減（43K → 10K → 4K）**（dev-reviewer R3）
7. **グランドトゥルースデータセットの構築**（dev-tester T3, sigma）

### Phase 3 に反映すべき事項

8. **タスクタイプ別コンテキスト取得戦略**（cc-hayashi）
9. **動的コンテキスト拡張メカニズム**（cc-hayashi）

### Phase 4 に反映すべき事項

10. **構造化出力（Markdown セクション + メタデータ）**（cc-hayashi）
11. **Claude Code CLI --context オプション統合**（cc-hayashi）
12. **フォールバック機構（コンテキスト取得失敗時）**（cc-hayashi）

### 横断的に反映すべき事項

13. **CI/CD パイプラインへのテスト組み込み**（dev-tester T5）
14. **A/B テストによる BM25 パラメータ反復改善**（sigma）
15. **既存ナレッジグラフシステムとの統合検討**（promptpro）

---

## 6. 未取得レビュー

以下のエージェントからはレビューが未取得（初期化状態 or 応答なし）:

| エージェント | ノード | 理由 |
|------------|--------|------|
| scholar | MainMini | 初期化状態（SOUL.md未設定） |
| dev-documenter | MainMini | 未クエリ |
| gyosei | MainMini | 未クエリ |
| main (orchestrator) | Gateway | 統合レビュー未取得 |
| その他28エージェント | 各ノード | 専門外のため省略 |

---

## 7. 結論

### 実装開始の可否: **GO（条件付き）**

**条件**:
1. Phase 1 開始前に AgentRelation テーブル分離設計を確定
2. Phase 2 開始前にグランドトゥルースデータセットを10件以上作成
3. 段階的トークン削減（一気に95%削減ではなく、75% → 90% → 95%）
4. 各フェーズ完了時にレビューエージェントへの再確認

**スケジュールへの影響**: なし（当初7-10日の見積もりは妥当）

---

## 変更履歴

| 日付 | バージョン | 変更内容 |
|------|----------|---------|
| 2026-03-20 | 1.0.0 | 初版（8エージェントレビュー統合） |
