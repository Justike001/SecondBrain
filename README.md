# SecondBrain

SecondBrain 是一个面向 Agent 的 Obsidian 知识操作系统模板与 CLI 工具集。

这个仓库已经与作者的私人知识库解耦。对其他用户、Agent 或自动化流程来说，默认应把仓库内的 `vault-template` 视为可直接使用的 vault。

- 默认 vault: `./vault-template`
- CLI 入口: `python cli/secondbrain.py`
- 推荐执行目录: 当前仓库根目录

## 快速开始

在仓库根目录直接运行：

```bash
python cli/secondbrain.py --vault vault-template today
python cli/secondbrain.py --vault vault-template start-session
python cli/secondbrain.py --vault vault-template doctor
```

如果后续你希望把自己的真实笔记与本仓库隔离，可以复制 `vault-template` 到别的目录，再将 `--vault` 改为那个路径。

如果你想保留自己的本地默认配置而不提交到 Git，可复制 `config/local.example.json` 为 `config/local.json`，再填写你自己的 `vault_path` 和 `owner`。

## 命令行清单（当前实际命令）

说明:
- `capture` 是 `capture-url` 别名。
- `promote` 是 `promote-resource` 别名。
- 兼容命令 `plan-today` / `close` / `diet-log` 仅建议在显式输入命令 token 时使用。

### 1) Daily / Session / Wrapup

| 命令 | 作用 | 常见语义触发 |
|---|---|---|
| `today` | 创建/刷新今日 DailyNote，并回填索引区块。 | 查看今日计划、今天做什么、我看看今天该干什么 |
| `plan-today` (兼容) | 创建/打开今日 DailyPlan，并确保 DailyNote 已联动。 | 显式输入 `plan-today` 时使用 |
| `start-session` | 为今天新建一个 Session，并写入 DailyNote 的 Sessions 索引。 | 开始一个会话、新建 session |
| `daily-open <date>` | 按自然日期打开（可选创建）DailyNote。 | 看看我昨天干了什么、打开某日日报 |
| `session-log --title --summary` | 把当前对话摘要写入 `02_Daily/.../Sessions`。 | 总结我们本轮对话 |
| `daily-wrapup --date today [--archive] [--push]` | 回填当日 DailyNote 的 Sessions/Resources/Thinking/Articles/PersonalLife/Notes；可归档+推送。 | 总结今日对话、今天收工、结束今天并归档旧记录、结束今天对话 |
| `close` (兼容) | 旧版收尾命令。建议改用 `daily-wrapup --date today --archive --push`。 | 显式输入 `close` 时使用 |
| `archive-daily --older-than N` | 归档旧 Daily/Sessions 到 `99_Archive`。 | 归档旧日报、清理 N 天前记录 |
| `graduate --days N` | 从最近 N 天记录提炼 Thinking 草稿。 | 沉淀近一周洞察、提炼思考 |

### 2) Resource Capture / Promote / Research

| 命令 | 作用 | 常见语义触发 |
|---|---|---|
| `capture-url <url>` / `capture <url>` | URL 收录到 `04_Resources/Inbox`，可抓取摘要。支持 `--resource-type prompt/article/video/image`。 | 收录这篇文章/视频/图片/prompt + URL |
| `promote-resource <ref-or-url>` / `promote` | 把 Inbox 已审核资源迁移到 Library。 | 我认为这篇文章信息可用、审核通过入库 |
| `research <topic-or-url>` | 主题研究写入 inbox/library/thinking。URL + `--route inbox` 默认自动委派到 `capture --fetch`。 | 帮我研究 xxx、调研这个主题 |

### 3) Projects / Ideas

| 命令 | 作用 | 常见语义触发 |
|---|---|---|
| `project-new "<name>"` | 在 `03_Projects/Active` 新建项目骨架（默认创建 `Project.md`、`AGENTS.md`、`Log.md`）。 | 新建 xxx 计划 |
| `project-start "<name>"` | Backlog -> Active。 | 启动 xxx 计划 |
| `project-query "<name>" --top-k N` | 仅在 `03_Projects` 范围检索项目细节。 | 查询 xxx 计划 |
| `project-close "<name>"` | 项目收尾并归档。 | 完结 xxx 计划 |
| `idea-capture "<title>"` | 记录灵感到 `03_Projects/Ideas`。 | 我有一个想法、进行灵感记录 |
| `idea-list` | 列出已记录灵感。 | 我有什么已经记录的灵感 |

### 4) Thinking / PersonalLife / Articles

| 命令 | 作用 | 常见语义触发 |
|---|---|---|
| `thinking-capture "<title>" --content ...` | 记录观察/洞见到 `05_Thinking`。 | 记录这个观察、记录这个洞见 |
| `life-memo "<title>" --content ...` | 写入 `06_PersonalLife/Backlog`。 | 将 xxx 写入个人备忘录 |
| `life-status` | 汇总 `06_PersonalLife/Active` 当前计划。 | 我当前的生活计划 |
| `life-plan-set "<title>" --content ...` | 在 `06_PersonalLife/{Active|Backlog|Closed}` 新建或更新生活计划。 | 设定 xxx 生活计划 |
| `diet-capture --meal ... --foods ... --carbs --protein --fat` | 记录餐食、自动计算 kcal，并对比目标给出“合格/需调整”。 | 作今日餐食记录、记录今天吃了什么 |
| `diet-log` (兼容) | 旧版餐食记录命令。建议改用 `diet-capture`。 | 显式输入 `diet-log` 时使用 |
| `article-draft "<title>" --content ...` | 生成文章草稿到 `07_Articles/Drafts`。 | 将这篇文章写入草稿 |
| `article-move "<ref>" --to scheduled/published` | 文章在 Drafts/Scheduled/Published 间迁移，并更新发布字段。 | 文章排期、文章已发布 |

### 5) Vault Query / Reasoning

| 命令 | 作用 | 常见语义触发 |
|---|---|---|
| `ask "<question>"` | 全 vault 检索并综合回答。 | 我曾经做过 xxx，我想看细节 |
| `brainstorm "<topic>"` | 聚合 Ideas + Resources + Thinking 做方向建议。 | 试着开始头脑风暴 |
| `trace "<topic>"` | 主题演化追踪（时间线 + 链接关系）。 | 追踪 xxx 的演化 |
| `connect "<a>" "<b>"` | 跨领域桥接分析。 | 连接 A 和 B |
| `emerge --days N` | 最近 N 天的隐含主题涌现分析。 | 最近有哪些隐含主题 |
| `challenge "<belief>"` | 对当前信念做反证与挑战。 | 挑战这个观点 |
| `doctor` | 环境与配置诊断。 | 跑一下诊断 |

## 当前语义触发规则（摘要）

来自 `skills/secondbrain-cli/SKILL.md` 的当前路由规则:

1. 优先路由到 canonical 命令。
2. 兼容命令 `plan-today` / `close` / `diet-log` 不作为自然语义主路由目标。
3. 高优先语义映射示例:
- 查看今日计划 -> `today`
- 看看我昨天干了什么 -> `daily-open`
- 今天收工 / 结束今天并归档旧记录 -> `daily-wrapup --date today --archive --push`
- 结束今天对话 / 结束今天工作 / 总结今日对话 -> `daily-wrapup --date today --archive --push`
- 收录这篇文章/视频/图片/prompt + URL -> `capture --fetch --resource-type <...> <url>`
- 我认为这篇文章信息是可用的 -> `promote <ref-or-url>`
- 记录这个观察/洞见 -> `thinking-capture`
- 将 xxx 写入个人备忘录 -> `life-memo`
- 我当前的生活计划 -> `life-status`
- 作今日餐食记录 -> `diet-capture`
- 设定 xxx 生活计划 -> `life-plan-set`
- 将这篇文章写入草稿 -> `article-draft`
- 将文章移到已发布/已排期 -> `article-move --to published|scheduled`

## 默认 Vault 说明

本仓库内置了一个可直接使用的标准 vault 骨架：

- 路径: `./vault-template`
- 用途: 给用户、Agent、自动化流程提供默认工作区
- 内容: 已包含目录结构、模板、Base 文件和系统文档骨架

推荐默认命令：

```bash
python cli/secondbrain.py --vault vault-template today
```

如果你后续要迁移到自己的独立 vault，可以直接复制 `vault-template`，然后继续沿用同一套命令。

### `--push` 边界（重要）

- `daily-wrapup ... --push` 只会推送 `--vault` 所在的 git 仓库。
- 当 `--vault` 指向仓库内的 `vault-template` 时，如果它没有独立 git 仓库，那么推送目标会落到当前仓库。
- 如果你希望笔记和 CLI 完全独立管理，先把 `vault-template` 复制到单独目录或单独仓库，再使用 `--push`。

## Vault 当前完整目录层级与作用

> 以下为 `vault-template/` 的标准目录结构示例，并标注每个子目录作用。

### 顶层目录

| 路径 | 作用 |
|---|---|
| `vault-template/00_System/` | 系统层：规范、模板、Agent 协议与全局仪表盘。 |
| `vault-template/02_Daily/` | 日志与会话执行层（按年/月分桶）。 |
| `vault-template/03_Projects/` | 项目生命周期层（Ideas/Active/Backlog/Closed）。 |
| `vault-template/04_Resources/` | 资源层（Inbox 待审、Library 正式）。 |
| `vault-template/05_Thinking/` | 思考层（洞见、方法论、evergreen）。 |
| `vault-template/06_PersonalLife/` | 个人生活层（Active/Backlog/Closed）。 |
| `vault-template/07_Articles/` | 内容发布层（Drafts/Scheduled/Published）。 |
| `vault-template/08_Attachments/` | 附件统一存储。 |
| `vault-template/99_Archive/` | 归档层（历史 daily/project/resource/article）。 |

### 00_System 详细层级

| 路径 | 作用 |
|---|---|
| `00_System/Agents/` | Agent 协作规则、协议文档存放。 |
| `00_System/Templates/` | 所有标准模板（DailyNote、DailyPlan、Session、Project、Thinking、Article、Resource 等）。 |
| `00_System/Dashboard.md` | 全局总览入口页面。 |
| `00_System/Memory.md` | 记忆/上下文记录总入口。 |
| `00_System/Projects.base` | 项目结构化视图（Base）。 |
| `00_System/Resources.base` | 资源结构化视图（Base）。 |
| `00_System/Articles.base` | 文章结构化视图（Base）。 |

### 02_Daily 详细层级

| 路径 | 作用 |
|---|---|
| `02_Daily/2026/` | 年度分桶示例。 |
| `02_Daily/2026/2026-February/` | 月度容器示例。 |
| `02_Daily/2026/2026-February/DailyNotes/` | 当月每日主日志。 |
| `02_Daily/2026/2026-February/Sessions/` | 当月会话记录。 |
| `02_Daily/2026/2026-February/Weekly/` | 当月周总结。 |
| `02_Daily/2026/2026-February/Monthly/` | 当月月总结。 |
| `02_Daily/2026/2026-March/` | 月度容器示例。 |
| `02_Daily/2026/2026-March/DailyNotes/` | 当月每日主日志。 |
| `02_Daily/2026/2026-March/Sessions/` | 当月会话记录。 |
| `02_Daily/2026/2026-March/Weekly/` | 当月周总结。 |
| `02_Daily/2026/2026-March/Monthly/` | 当月月总结。 |
| `02_Daily/2026/2026-March/DailyPlan/` | 当日计划页（由 `today/plan-today` 生成）。 |

### 03_Projects 详细层级

| 路径 | 作用 |
|---|---|
| `03_Projects/Ideas/` | 灵感池，未承诺排期。 |
| `03_Projects/Active/` | 正在推进的项目。 |
| `03_Projects/Backlog/` | 已定义但未启动项目。 |
| `03_Projects/Closed/` | 已完成项目（收尾归档前后容器）。 |
| `03_Projects/Active/Project - Example Active Project/` | 示例进行中项目。 |
| `03_Projects/Backlog/Example Research Project/` | Backlog 示例项目。 |
| `03_Projects/Backlog/Example Learning Project/` | Backlog 示例项目。 |

### 04_Resources 详细层级

| 路径 | 作用 |
|---|---|
| `04_Resources/Inbox/` | 待审核资源收件箱。 |
| `04_Resources/Library/` | 已审核可复用资源库。 |

### 05_Thinking 详细层级

| 路径 | 作用 |
|---|---|
| `05_Thinking/` | 洞见、方法论、可长期复用思考。 |

### 06_PersonalLife 详细层级

| 路径 | 作用 |
|---|---|
| `06_PersonalLife/Active/` | 当前执行中的个人生活计划。 |
| `06_PersonalLife/Backlog/` | 个人生活待办计划池。 |
| `06_PersonalLife/Closed/` | 已完成个人计划归档。 |
| `06_PersonalLife/Active/Diet/` | 饮食计划与餐食记录。 |
| `06_PersonalLife/Active/Exercise/` | 训练计划。 |
| `06_PersonalLife/Active/Reading/` | 阅读计划。 |

### 07_Articles 详细层级

| 路径 | 作用 |
|---|---|
| `07_Articles/Drafts/` | 草稿区。 |
| `07_Articles/Scheduled/` | 已排期待发布。 |
| `07_Articles/Published/` | 已发布归档。 |

### 08_Attachments 详细层级

| 路径 | 作用 |
|---|---|
| `08_Attachments/` | 图片、PDF、截图等附件存放。 |

### 99_Archive 详细层级

| 路径 | 作用 |
|---|---|
| `99_Archive/Daily/` | Daily 历史归档入口。 |
| `99_Archive/Daily/2025/` | 历史归档分桶示例。 |
| `99_Archive/Daily/2025/2025-January/` | 月度归档分桶示例。 |
| `99_Archive/Daily/2025/2025-January/DailyNotes/` | 历史 DailyNotes 归档。 |
| `99_Archive/Daily/2025/2025-January/Sessions/` | 历史 Sessions 归档。 |
| `99_Archive/Daily/2025/2025-January/Weekly/` | 历史 Weekly 归档。 |
| `99_Archive/Daily/2025/2025-January/Monthly/` | 历史 Monthly 归档。 |
| `99_Archive/_Legacy/` | 旧结构迁移暂存区。 |
| `99_Archive/_Legacy/Articles/` | 旧文章归档残留。 |
| `99_Archive/_Legacy/Projects/` | 旧项目归档残留。 |
| `99_Archive/_Legacy/Resources/` | 旧资源归档残留。 |
| `99_Archive/_Legacy/Resources/2026/02/` | 旧资源按年月分桶示例。 |

## 运行

```bash
python cli/secondbrain.py -h
python cli/secondbrain.py --vault vault-template doctor
```
