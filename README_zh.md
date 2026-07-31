# gitnexus-stable-ops

[English](./README.md) | **中文** | [日本語](./README_ja.md)

**用于在生产环境中稳定运行 [GitNexus](https://github.com/abhigyanpatwari/GitNexus) 的运维工具集，支持固定版本的 CLI/MCP 工作流。**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Stars](https://img.shields.io/github/stars/ShunsukeHayashi/gitnexus-stable-ops?style=social)](https://github.com/ShunsukeHayashi/gitnexus-stable-ops)

由 [合同会社みやび (Miyabi G.K.)](https://miyabi-ai.jp) 构建 — 在生产环境中管理 25+ 个使用 GitNexus 索引的仓库。

> **⚠️ 许可证说明**: 此仓库使用 **MIT 许可证**，仅适用于包装脚本、工具和文档。**[GitNexus](https://github.com/abhigyanpatwari/GitNexus) 本身使用 [PolyForm NonCommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/) 许可证。** 此工具集调用 GitNexus CLI，但不包含或重新分发任何 GitNexus 源代码。商业使用前请查看 [GitNexus 许可证](https://github.com/abhigyanpatwari/GitNexus/blob/main/LICENSE)。

---

## 概述

GitNexus 非常强大，但在多仓库的生产环境中运行它会带来以下运维挑战：

- **版本漂移** — CLI 和 MCP 引用不同的 GitNexus 版本（KuzuDB vs LadybugDB），导致数据损坏
- **Embedding 丢失** — `analyze --force` 不加 `--embeddings` 会静默删除现有 embedding
- **脏工作树损坏** — 对未提交的工作进行重索引会污染代码图
- **Impact 不稳定** — `impact` 命令间歇性失败，阻塞分析工作流

本工具集解决了以上所有问题。

## 功能特性

| 脚本 | 用途 |
|------|------|
| `bin/gni` | 改进的 CLI 封装，提供可读输出和 impact 回退视图 |
| `bin/gitnexus-doctor.sh` | 诊断版本漂移、索引健康状况和 MCP 配置 |
| `bin/gitnexus-smoke-test.sh` | 端到端健康检查（analyze/status/list/context/cypher/impact） |
| `bin/gitnexus-safe-impact.sh` | 带有自动上下文回退的影响分析 |
| `bin/gitnexus-auto-reindex.sh` | 智能单仓库重索引（过期检测、embedding 保护） |
| `bin/gitnexus-reindex.sh` | 批量重索引最近变更的仓库（适合 cron） |
| `bin/gitnexus-reindex-all.sh` | 使用安全默认值重索引所有已注册仓库 |
| `bin/graph-meta-update.sh` | 为图可视化生成跨社区边缘 JSONL |

## 前提条件

- `bash`、`git`、`jq`、`python3`
- 已安装 `gitnexus` CLI（默认路径: `~/.local/bin/gitnexus-stable`）

## 安装

### 一键安装（推荐）

```bash
git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops.git
cd gitnexus-stable-ops
make install
```

这将会：
- 将 `bin/gni` 软链接到 `~/.local/bin/gni`
- 使所有脚本可执行
- 确保 `~/.local/bin` 在你的 PATH 中

### 手动安装

```bash
git clone https://github.com/ShunsukeHayashi/gitnexus-stable-ops.git
cd gitnexus-stable-ops
ln -s $(PWD)/bin/gni ~/.local/bin/gni
chmod +x bin/*
```

## 快速开始

```bash
# 运行测试
make test

# 诊断仓库
bin/gitnexus-doctor.sh ~/dev/my-repo my-repo MyClassName

# 运行冒烟测试
bin/gitnexus-smoke-test.sh ~/dev/my-repo my-repo MyClassName

# 智能重索引（索引为最新时跳过）
REPO_PATH=~/dev/my-repo bin/gitnexus-auto-reindex.sh

# 批量重索引最近 24 小时内变更的仓库
REPOS_DIR=~/dev bin/gitnexus-reindex.sh
```

## 安全默认值

- **Embedding 保护** — 有现有 embedding 的仓库自动添加 `--embeddings` 标志
- **脏工作树跳过** — 有未提交更改时跳过重索引（覆盖: `ALLOW_DIRTY_REINDEX=1`）
- **Impact 回退** — 当 `impact` 失败时，`gitnexus-safe-impact.sh` 返回基于上下文的 JSON
- **版本固定** — 所有脚本使用 `$GITNEXUS_BIN`（默认: `~/.local/bin/gitnexus-stable`）

## 环境变量

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `GITNEXUS_BIN` | `~/.local/bin/gitnexus-stable` | 固定的 GitNexus CLI 路径 |
| `REGISTRY_PATH` | `~/.gitnexus/registry.json` | 已索引的仓库注册表 |
| `ALLOW_DIRTY_REINDEX` | `0` | 允许重索引脏工作树 |
| `FORCE_REINDEX` | `1` | 在冒烟测试中强制重索引 |
| `REPOS_DIR` | `~/dev` | 批量重索引的根目录 |
| `LOOKBACK_HOURS` | `24` | 检查变更的时间范围 |
| `OUTPUT_DIR` | `./out` | 图元数据输出目录 |

## 与 Cron 配合使用

```bash
# 每天凌晨 3 点重索引
0 3 * * * cd /path/to/gitnexus-stable-ops && REPOS_DIR=~/dev bin/gitnexus-reindex.sh

# 每周一凌晨 4 点完整重索引
0 4 * * 1 cd /path/to/gitnexus-stable-ops && bin/gitnexus-reindex-all.sh
```

## 兼容性

| 平台 | 状态 |
|------|------|
| macOS (Apple Silicon) | 已测试（主要开发平台） |
| Linux (Ubuntu, Debian, Fedora) | 已测试并支持 |
| Windows | 不支持（请使用 WSL 或 Git Bash） |

系统要求：
- Bash 4.0+
- Git 2.0+
- jq 1.6+
- Python 3.6+

## 文档

- [运维手册](docs/runbook.md) — 分步操作流程
- [架构设计](docs/architecture.md) — 设计原则和数据流

## 生产环境统计

在合同会社みやび的生产环境中运行：
- **25 个仓库** 已索引并监控
- **32,000+ 符号** / **73,000+ 边** 的知识图谱
- **每日自动重索引** 通过 cron
- 自部署此工具集以来 **零 embedding 丢失**

## 贡献指南

欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

- [报告 Bug](.github/ISSUE_TEMPLATE/bug_report.md)
- [功能请求](.github/ISSUE_TEMPLATE/feature_request.md)
- 提交 Pull Request

所有贡献必须：
- 为新功能包含测试
- 遵循 [Conventional Commits](https://www.conventionalcommits.org/) 格式
- 通过 `make test`

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

---

## 关于开发者

**林 駿甫 (Shunsuke Hayashi)** — 一位运营 40 个 AI Agent 的个人开发者。

- [miyabi-ai.jp](https://www.miyabi-ai.jp)
- X/Twitter: [@The_AGI_WAY](https://x.com/The_AGI_WAY)
- GitHub: [@ShunsukeHayashi](https://github.com/ShunsukeHayashi)

如果觉得有用，请给这个项目点个 Star！
