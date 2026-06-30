# CLAUDE.md（项目级）

学习督促 Discord Bot。完整需求见 `docs/SPEC.md`——**它是唯一事实来源，动手前先读**。全局默认见 `.claude/CLAUDE.md`；本文件只写项目特有事实与覆盖项。

## 命令

- 跑起来：`uv run python -m procrastination_terminator`（先 `cp .env.example .env` 填密钥）。
- 常规：`uv sync` / `uv run pytest` / `uv run ruff check` / `uv run ruff format` / `uv run mypy .`（标准命令不赘述）。

## 结构与边界

- `src/` 布局，包名 `procrastination_terminator`，mypy `--strict`、Python 3.12+。
- **纯函数是测试重点**：`backoff.py`（退避曲线）、`daytime.py`（逻辑日）、`monitor.py`（监工决策表）——不碰 IO，每条边界都该有单测钉死。改这三个必须同步改/加测试。
- IO 分层：`store.py`(CSV) / `plan_parser.py`(解析+同步) / `llm.py`(LLM) / `bot.py`(discord)。

## 关键不变式（破坏即 bug，改前先想清楚）

- 监工**无记忆**：只读当前快照 + 当前时间下结论；去重只认 `latest_progress_time` 列，绝不靠内存。
- **文件是唯一事实来源**：监工写回时先重读、只改这一轮要动的行，**不整文件覆盖**（防盖掉手动编辑）。
- `!sync` = 按 **`code`** 集合对比（增缺的/删多的/匹配的整行不动），只动今天及以后；**不重判 `type`**。
- 时间一律 **tz-aware**（`Europe/London`，自动处理夏令时）；跨午夜按「逻辑日」（日初 4:00 为界）。

## 别碰 / 先问

- 不要 `rm -rf .git` 或动 git 历史（`init.md` 那条是给全新起手的，本仓库已有历史 + PR）。
- 改 SPEC 的机制语义前先确认——它是一来一回敲定的，多处交叉引用。
- `init.md` 是一次性脚手架，起完手可删；别据它改已定布局。

## 隐私与密钥

- 密钥走环境变量：`DISCORD_TOKEN` / `DISCORD_USER_ID` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`。
- 模板见 `.env.example`（只有键名）；真实值放 `.env`（已 gitignore）。
- 运行期数据 `plan.txt` / `progress.csv` / `history.csv`（默认在 `data/`）含个人计划，**不提交**（已 gitignore）。
