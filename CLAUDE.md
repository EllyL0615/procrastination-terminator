# CLAUDE.md（项目级）

学习督促 Discord Bot。完整需求见 `docs/SPEC.md`——**它是唯一事实来源，动手前先读**。全局默认见 `.claude/CLAUDE.md`；本文件只写项目特有事实与覆盖项。

## 命令

- 跑起来：`uv run python -m procrastination_terminator`（先 `cp .env.example .env` 填密钥）。
- 常规：`uv sync` / `uv run pytest` / `uv run ruff check` / `uv run ruff format` / `uv run mypy .`（标准命令不赘述）。

## 结构与边界

- `src/` 布局，包名 `procrastination_terminator`，mypy `--strict`、Python 3.12+。
- **纯函数是测试重点**：`backoff.py`（退避曲线）、`daytime.py`（逻辑日）、`monitor.py`（监工决策表）——不碰 IO，每条边界都该有单测钉死。改这三个必须同步改/加测试。
- IO 分层：`storage/`（后端抽象：`file` 走 `store.py` 的 CSV，`notion` 走 Notion，由 `STORAGE_BACKEND` 选，`build_backend` 建）/ `plan_parser.py`(解析+同步) / `llm.py`(LLM) / `bot.py`(discord)。`store.py` 只是 `file` 后端的实现,别再从 `bot.py` 直接调它——走 `self.store`。

## 关键不变式（破坏即 bug，改前先想清楚）

- 监工**无记忆**：只读当前快照 + 当前时间下结论；去重只认 `latest_progress_time` 列，绝不靠内存。
- **外部存储是唯一事实来源**（本地文件或 Notion，按 `STORAGE_BACKEND`）：监工每 tick 重读快照、只写这一轮要动的行，不动其他行（防盖掉手动编辑）。file 后端重读整表改行；notion 后端按 `code` PATCH 单页,天然只碰这一行。
- `!sync` = 按 **`code`** 集合对比（增缺的/删多的/匹配的整行不动），只动今天及以后；**不重判 `type`**。唯一例外：`notes` 列由 `plan.txt` 全权拥有，匹配行也会刷（见 SPEC §3.1）。
- 解析分层：任务骨架（日期/时间/名/`subject`/`code`）由 `plan_parser.parse_plan_text` **确定性**解析（不漏行、code 稳）；LLM（`llm.annotate_plan`）只在固定清单上标注 `type`/`notes`，无权增删改任务。
- 时间一律 **tz-aware**（`Europe/London`，自动处理夏令时）；跨午夜按「逻辑日」（日初 4:00 为界）。
- `context.txt` 只经 LLM 层，只改变「理解含义 + 措辞」（在 `llm.py._chat` 统一拼进 system prompt）；**不进监工决策**（何时催/催谁/状态推进仍只看快照+时间+配置）。别把它当行为/时间配置面板。

## 别碰 / 先问

- 不要 `rm -rf .git` 或动 git 历史（`init.md` 那条是给全新起手的，本仓库已有历史 + PR）。
- 改 SPEC 的机制语义前先确认——它是一来一回敲定的，多处交叉引用。
- `init.md` 是一次性脚手架，起完手可删；别据它改已定布局。

## 隐私与密钥

- 密钥走环境变量：`DISCORD_TOKEN` / `DISCORD_USER_ID` / `DISCORD_CHANNEL_ID` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`；notion 模式另加 `NOTION_API_KEY` / `NOTION_DB_ID` / `NOTION_PLAN_PAGE_ID` / `NOTION_CONTEXT_PAGE_ID`（`STORAGE_BACKEND=notion` 时 `from_env` 会强制要求）。
- 模板见 `.env.example`（只有键名）；真实值放 `.env`（已 gitignore）。
- 运行期数据 `plan.txt` / `progress.csv` / `history.csv` / `context.txt`（默认在 `data/`）含个人计划，**不提交**（已 gitignore）。`context.txt` 是我手写、Bot 只读的常驻自然语言说明（术语/口径/偏好/背景，见 SPEC §2、§4.5）。notion 模式下这四者改存 Notion（仍属个人私有；集成密钥走环境变量、不提交）。
