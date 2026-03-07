---
name: secondbrain-cli
description: "Route natural-language SecondBrain intents to the local CLI deterministically. Use for daily planning, daily notes, sessions, wrapup, resources, projects, ideas, thinking, research, personal life, article workflows, diet logs, and environment diagnostics. Trigger when the user asks to create/open/update/query vault content or explicitly mentions commands such as today, start-session, capture, promote, daily-wrapup, ask, trace, connect, emerge, challenge, research, doctor, or related Chinese phrases."
---

# SecondBrain CLI Skill

## Runtime Anchors

- Repository path: `.`
- CLI path: `cli/secondbrain.py`
- Default vault: `vault-template`
- Fast route table: `skills/secondbrain-cli/FAST_ROUTE_TABLE.json`
- Command schema cache: `skills/secondbrain-cli/COMMAND_SCHEMA_CACHE.json`
- Primary command source: `cli/secondbrain.py`

## Execution Policy

- Treat `secondbrain-cli` as the default execution layer for this workspace.
- Run the CLI first when the user intent maps cleanly to one command.
- Prefer canonical commands over compatibility commands.
- Build commands with an explicit `--vault vault-template` unless the user overrides it.
- Verify success from exit code plus returned path or structured output.

Routing priority:
1. Explicit command text such as `/today`, `/capture`, `start-session`, `$secondbrain-cli`
2. Clear natural-language intent that maps to one command
3. Multi-intent request split into an ordered command sequence
4. Ask one short clarification question only if routing is still ambiguous

## Git Boundary

- Treat `.` as the toolkit repo.
- Treat `vault-template` as the default vault in this repository unless the user provides another `--vault` path.
- For `--push` or `close`, sync the git repository that contains the effective `--vault` path.
- Never assume a user-specific remote URL.

## Fast Path

1. Read `FAST_ROUTE_TABLE.json` first.
2. Match `high_priority_phrases` before `intent_keywords`.
3. Build the command from the route `template`.
4. Use `COMMAND_SCHEMA_CACHE.json` as the first parameter reference.
5. Avoid `--help` and source scanning on the first pass.
6. Execute directly.
7. If execution fails, fallback in order: `COMMAND_SCHEMA_CACHE.json`, `--help`, source snippet in `cli/secondbrain.py`.
8. Read the detailed semantic sections in this file only when the fast path is insufficient.

## Command Catalog

| Command | Purpose | Typical output |
|---|---|---|
| `today` | Create or open today's DailyNote and refresh indexes/dashboard links. | Daily note path |
| `plan-today` | Compatibility command to create or open today's DailyPlan and refresh DailyNote links. | DailyPlan path |
| `start-session` | Create a new session note and link it into today's DailyNote. | Session note path |
| `daily-open` | Open or create a DailyNote by natural date expression. | Daily note path |
| `session-log` | Write a summarized session note into `02_Daily/YYYY/YYYY-MMMM/Sessions`. | Session note path |
| `capture-url` / `capture` | Capture a URL into `04_Resources/Inbox` and optionally fetch summary content. | Inbox resource path |
| `promote-resource` / `promote` | Move a reviewed resource from Inbox to Library and normalize the template. | Source path plus Library path |
| `close` | Compatibility day-close command. Prefer `daily-wrapup --date today --archive --push`. | Daily path plus optional archive/sync logs |
| `daily-wrapup` | Refresh DailyNote sections, optionally archive, optionally push the vault repo. | Daily path plus optional archive/sync log |
| `graduate` | Distill recent notes and resources into thinking drafts. | Created or skipped counts |
| `archive-daily` | Archive older Daily and Session notes into `99_Archive/Daily/...`. | Archived counts |
| `project-new` | Create a new project folder and core notes under `03_Projects/Active`. | Project folder path |
| `project-start` | Move a project from `03_Projects/Backlog` to `03_Projects/Active`. | Active project folder path |
| `project-query` | Search only within `03_Projects`. | Scoped project query output |
| `project-close` | Close and archive a project and generate a report artifact. | Report path plus archive path |
| `thinking-capture` | Capture an observation or insight into `05_Thinking`. | Thinking note path |
| `life-memo` | Write a memo into `06_PersonalLife/Backlog`. | Personal memo path |
| `life-status` | Summarize notes under `06_PersonalLife/Active`. | Active life snapshot |
| `life-plan-set` | Create or update a life plan under `06_PersonalLife/<Active|Backlog|Closed>`. | Life plan path |
| `article-draft` | Create an article draft under `07_Articles/Drafts`. | Draft article path |
| `article-move` | Move an article to Scheduled or Published and update publish fields. | Source path plus target path |
| `idea-list` | List recorded ideas under `03_Projects/Ideas`. | Idea list output |
| `idea-capture` | Create a new idea note under `03_Projects/Ideas`. | Idea note path |
| `ask` | Query vault knowledge and return a synthesized answer with references. | Structured answer |
| `brainstorm` | Aggregate Ideas, Resources, and Thinking into direction suggestions. | Brainstorm synthesis |
| `trace` | Trace the evolution timeline of a topic. | Topic timeline |
| `connect` | Find bridge points between two domains. | Cross-domain bridge report |
| `emerge` | Extract latent themes from recent notes. | Theme report |
| `challenge` | Challenge a belief with counter-evidence from notes. | Counter-evidence report |
| `research` | Research a topic or URL and write to inbox, library, or thinking. | Research note path plus write mode |
| `diet-log` | Compatibility diet logger. Prefer `diet-capture`. | Diet note path plus summary |
| `diet-capture` | Log a meal, calculate kcal, and evaluate against targets. | Diet note path plus verdict |
| `doctor` | Diagnose runtime, vault, and Obsidian integration readiness. | Diagnostics report |

## Semantic Routing Map

### `today`

Intent examples:
- 今天做什么
- 我看看今天该干什么
- 打开今日工作台
- 帮我开今天的日报

Run:
`python cli/secondbrain.py --vault vault-template today`

### `plan-today`

Compatibility only:
- Do not route natural-language intent to this command.
- Use only when the user explicitly types `plan-today`.

Run:
`python cli/secondbrain.py --vault vault-template plan-today`

### `start-session`

Intent examples:
- 开始一个会话
- 记录这次讨论
- 新建 session
- 把当前对话开一个工作会话

Run:
`python cli/secondbrain.py --vault vault-template start-session`

### `daily-open`

Intent examples:
- 看看我昨天干了什么
- 打开 2026-03-03 的日报
- 看看某天的 DailyNote

Run:
`python cli/secondbrain.py --vault vault-template daily-open "yesterday"`

### `session-log`

Intent examples:
- 总结我们本轮对话并写入 session
- 把这轮沟通记录成会话笔记
- 生成会话总结到 Sessions

Run:
`python cli/secondbrain.py --vault vault-template session-log --title "<topic>" --summary "<summary>" --date today`

### `capture-url`

Intent examples:
- 收录这个链接
- 把这个网址记到资源库待审核
- 帮我抓取并总结这个页面
- 存一下这条视频/图片链接

Parameter extraction:
- `url`: detect the first valid `http/https` URL
- `resource-type` inference:
- `视频|访谈|youtube|b站|video` -> `video`
- `图片|海报|截图|image` -> `image`
- `prompt|提示词` -> `prompt`
- otherwise -> `article`
- Add `--fetch` by default unless the user says `只收录不抓取`

Run template:
`python cli/secondbrain.py --vault vault-template capture-url --fetch --resource-type <prompt|article|video|image> <url>`

Alias:
`python cli/secondbrain.py --vault vault-template capture --fetch --resource-type <prompt|article|video|image> <url>`

### `promote-resource`

Intent examples:
- 这个资源审核通过，入库
- 把这个 Inbox 资源转到 Library
- 资源通过评审，迁移到正式库
- promote 这个链接

Run:
`python cli/secondbrain.py --vault vault-template promote-resource "<ref-or-url>"`

Alias:
`python cli/secondbrain.py --vault vault-template promote "<ref-or-url>"`

### `close`

Compatibility only:
- Do not route natural-language intent to this command.
- Use only when the user explicitly types `close`.

Run:
`python cli/secondbrain.py --vault vault-template close`

### `daily-wrapup`

Intent examples:
- 总结今日对话
- 结束今天对话，总结今日对话
- 把今天的 Sessions/Resources/Thinking/Articles/PersonalLife 回填到 DailyNote
- 今日收尾并推送
- 今日收尾并归档旧记录

Push scope:
- `--push` sync only the git repository at `--vault`
- In this workspace, `vault-template` is the push target

Run:
`python cli/secondbrain.py --vault vault-template daily-wrapup --date today`

With push:
`python cli/secondbrain.py --vault vault-template daily-wrapup --date today --push`

With archive plus push:
`python cli/secondbrain.py --vault vault-template daily-wrapup --date today --archive --push`

### `graduate`

Intent examples:
- 把最近的内容提炼成 thinking
- 沉淀近一周洞察
- 生成思考草稿

Run:
`python cli/secondbrain.py --vault vault-template graduate --days <N>`

### `archive-daily`

Intent examples:
- 归档旧日报
- 清理 30 天前的 daily/session
- 跑一次日记归档

Run:
`python cli/secondbrain.py --vault vault-template archive-daily --older-than <N>`

### `project-new`

Intent examples:
- 新建项目 XXX
- 立一个项目：XXX
- 创建 Active 项目 XXX

Run:
`python cli/secondbrain.py --vault vault-template project-new "<name>"`

### `project-start`

Intent examples:
- 启动 XXX 计划
- 把 XXX 从 Backlog 提到 Active
- 开始推进 XXX 项目

Run:
`python cli/secondbrain.py --vault vault-template project-start "<name>"`

### `project-query`

Intent examples:
- 查询 XXX 计划
- 看看 XXX 项目当前细节
- 在 `03_Projects` 里查找 XXX

Run:
`python cli/secondbrain.py --vault vault-template project-query "<name>" --top-k 10`

### `project-close`

Intent examples:
- 关闭项目 XXX
- 项目 XXX 收尾归档
- 把 XXX 标记完成并归档

Run:
`python cli/secondbrain.py --vault vault-template project-close "<name>"`

### `thinking-capture`

Intent examples:
- 记录这个观察
- 记录这个洞见
- 把这段思考写入 Thinking

Run:
`python cli/secondbrain.py --vault vault-template thinking-capture "<title>" --content "<insight>" --tags "observation,insight"`

### `life-memo`

Intent examples:
- 将 XXX 写入个人备忘录
- 把这条提醒记到生活 Backlog

Run:
`python cli/secondbrain.py --vault vault-template life-memo "<title>" --content "<memo>"`

### `life-status`

Intent examples:
- 我当前的生活计划
- 看看我现在的个人生活安排

Run:
`python cli/secondbrain.py --vault vault-template life-status --top-k 20`

### `life-plan-set`

Intent examples:
- 设定 XXX 生活计划
- 新增一个运动/饮食/阅读计划

Run:
`python cli/secondbrain.py --vault vault-template life-plan-set "<title>" --content "<plan>" --area <Diet|Exercise|Reading|General> --status active`

### `article-draft`

Intent examples:
- 将这篇文章写入草稿
- 写一篇文章草稿：XXX

Run:
`python cli/secondbrain.py --vault vault-template article-draft "<title>" --content "<draft-content>"`

### `article-move`

Intent examples:
- 把这篇文章排期
- 把这篇文章设为已发布
- 将 Drafts 的文章移动到 Scheduled 或 Published

Run (scheduled):
`python cli/secondbrain.py --vault vault-template article-move "<ref>" --to scheduled --date <YYYY-MM-DD>`

Run (published):
`python cli/secondbrain.py --vault vault-template article-move "<ref>" --to published --url "<publish-url>"`

### `idea-list`

Intent examples:
- 我有什么已经记录的灵感
- 列一下 Ideas 里的想法
- 看看我存过哪些灵感

Run:
`python cli/secondbrain.py --vault vault-template idea-list --top-k 30`

### `idea-capture`

Intent examples:
- 我有一个想法
- 记录一个灵感：XXX
- 进行灵感记录

Run:
`python cli/secondbrain.py --vault vault-template idea-capture "<title>" --content "<details>" --tags "idea,brainstorm"`

### `ask`

Intent examples:
- 在我的知识库里查一下 XXX
- 我之前记过 XXX 吗
- 总结一下 vault 里关于 XXX 的内容

Run:
`python cli/secondbrain.py --vault vault-template ask "<question>" --engine hybrid --top-k 6`

### `brainstorm`

Intent examples:
- 试着开始头脑风暴
- 围绕 XXX 做一个脑暴
- 结合灵感、资源、思考给我方案方向

Run:
`python cli/secondbrain.py --vault vault-template brainstorm "<topic>" --top-k 12`

### `trace`

Intent examples:
- 追踪 XXX 的演化脉络
- 这个想法是怎么一步步形成的
- 帮我看主题 XXX 的时间线

Run:
`python cli/secondbrain.py --vault vault-template trace "<topic>" --top-k 8`

### `connect`

Intent examples:
- 帮我连接 A 和 B 两个领域
- 找找 A 与 B 的桥接点
- 做一个跨领域联想：A / B

Run:
`python cli/secondbrain.py --vault vault-template connect "<domain_a>" "<domain_b>" --top-k 6`

### `emerge`

Intent examples:
- 最近有哪些隐含主题
- 帮我做主题涌现分析
- 从最近 30 天记录里找模式

Run:
`python cli/secondbrain.py --vault vault-template emerge --days <N> --top-k 6`

### `challenge`

Intent examples:
- 挑战一下这个观点：XXX
- 帮我找这个信念的反例
- 用历史笔记反证这个判断

Run:
`python cli/secondbrain.py --vault vault-template challenge "<belief>" --top-k 6`

### `research`

Intent examples:
- 帮我研究 XXX
- 做一个关于 XXX 的资料调研
- 针对这个 URL 做研究并写入资源

Parameter extraction:
- If input is a URL, keep it as the topic string
- Route inference:
- `入库|正式库|library` -> `--route library`
- `思考|洞察|thinking` -> `--route thinking`
- default -> `--route inbox`

URL routing rule:
- `research "<url>" --route inbox` auto-delegate to `capture --fetch`
- Use `--url-mode research` to force the research pipeline on a URL

Run:
`python cli/secondbrain.py --vault vault-template research "<topic-or-url>" --route <inbox|library|thinking> --top-k 6`

### `diet-log`

Compatibility only:
- Do not route natural-language intent to this command.
- Use only when the user explicitly types `diet-log`.

Required fields:
- `meal`
- `foods`
- `carbs`
- `protein`
- `fat`

Run template:
`python cli/secondbrain.py --vault vault-template diet-log --day-type <training|rest> --meal <meal> --carbs <g> --protein <g> --fat <g> --foods "<text>"`

### `diet-capture`

Intent examples:
- 作今日餐食记录
- 记录今天吃了什么并判断是否达标

Run template:
`python cli/secondbrain.py --vault vault-template diet-capture --day-type <training|rest> --meal <meal> --foods "<foods>" --carbs <g> --protein <g> --fat <g>`

### `doctor`

Intent examples:
- 帮我检查 secondbrain 环境
- 看看 Obsidian CLI 能不能用
- 跑一下诊断

Run:
`python cli/secondbrain.py --vault vault-template doctor`

## Resource Template Binding

- `capture-url` writes Inbox resources with `vault-template/00_System/Templates/Resource-Inbox.md`
- `promote-resource` writes reviewed resources with `vault-template/00_System/Templates/Resource-Library.md`
- Use resource filename convention `YYYY-MM-DD - <topic>.md`
- Require source fields `source_url` and `from_who`
- Restrict frontmatter `type` to `prompt | article | video | image`
- For `type=video --fetch`, try transcript first with `yt-dlp`, then Agent-Reach, then `r.jina.ai`
- For `type=image`, download to `08_Attachments/`, write `attachment_path`, and try OCR with `tesseract` when `--fetch` is present
- For `type=prompt --fetch`, prioritize prompt candidates from markdown and code blocks into `## Quotes / Evidence`

## Global Alias Keywords

Trigger this skill for:
- `secondbrain`, `general agent`, `daily`, `today`, `session`, `start-session`
- `capture url`, `capture`, `promote`, `收录链接`, `审核入库`
- `daily-open`, `open daily`, `yesterday summary`, `session-log`
- `project new`, `project start`, `project close`, `project-query`
- `ask`, `trace`, `connect`, `emerge`, `challenge`, `research`, `brainstorm`
- `idea capture`, `idea list`, `灵感记录`, `我有一个想法`, `启动计划`, `查询计划`
- `thinking capture`, `insight capture`, `观察记录`, `洞见记录`
- `life memo`, `life status`, `life plan`, `个人备忘录`, `生活计划`
- `article draft`, `article move`, `发布文章`, `文章排期`
- `diet capture`, `diet log`, `今日餐食记录`, `饮食达标`, `餐食记录`
- `今天做什么`, `我看看今天该干什么`, `今天该干什么`

## High-Priority Chinese Phrases

Always route these phrases to CLI execution first:
- 查看今日计划 -> `today`
- 看看我昨天干了什么 / 打开某日日报 -> `daily-open`
- 今天收工 / 结束今天并归档旧记录 -> `daily-wrapup --date today --archive --push`
- 结束今天对话 / 结束今天工作 / 结束今天对话，总结今日对话 -> `daily-wrapup --date today --archive --push`
- 启动 XXX 计划 -> `project-start`
- 查询 XXX 计划 / 查询 XXX 项目 -> `project-query`
- 我有什么已经记录的灵感 -> `idea-list`
- 试着开始头脑风暴 -> `brainstorm`
- 进行灵感记录 / 我有一个想法 -> `idea-capture`
- 总结我们本轮对话 -> `session-log`
- 总结今日对话 -> `daily-wrapup --date today`
- 总结今日对话并推送 -> `daily-wrapup --date today --archive --push`
- 收录这篇文章、视频、图片、prompt 加 URL -> `capture --fetch --resource-type <...> <url>`
- 我认为这篇文章信息是可用的 -> `promote "<ref-or-url>"`
- 记录这个观察 / 洞见 -> `thinking-capture`
- 将 XXX 写入个人备忘录 -> `life-memo`
- 我当前的生活计划 -> `life-status`
- 作今日餐食记录 -> `diet-capture`
- 设定 XXX 生活计划 -> `life-plan-set`
- 将这篇文章写入草稿 -> `article-draft`
- 将文章移到已发布 / 已排期 -> `article-move --to published|scheduled`

## Compatibility Commands

Treat these commands as backward-compatible only:
- `plan-today` -> prefer `today`
- `close` -> prefer `daily-wrapup --date today --archive --push`
- `diet-log` -> prefer `diet-capture`

Routing rule:
- Use compatibility commands only when the user explicitly types the command token.

## Summary Writeback Rule

When giving a key-point summary, also write a UTF-8 Chinese markdown note into the vault.

- Default location: `04_Resources/Library/Summaries/`
- Suggested filename: `<date> - <source-slug> - 中文总结.md`
- Minimum sections:
- `## 内容概述`
- `## 关键见解`
- `## 可执行动作`

