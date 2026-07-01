# Procrastination Terminator

A single-user Discord bot that keeps you moving through a daily study plan. You
write down what you intend to do and when; the bot watches the clock and messages
you in a Discord channel to start each task on time, checks in on your progress,
confirms when you finish, and prompts you each night to plan the next day.

It is built for one person — you — and only listens to you, in one channel.

---

## What it does

- **Nags you to start.** When a task's time arrives and you haven't begun, the bot
  messages you with one concrete first step. If you keep putting it off, it keeps
  reminding you, with the interval growing so it never floods the channel.
- **Checks your progress.** Halfway through a task and again at its end, it asks how
  things are going and records a short summary of your reply.
- **Confirms completion.** When you say you're done (or the bot judges you are), the
  task is marked complete.
- **Wraps up the day.** At a set time each night it summarizes what you finished and
  what you didn't, then reminds you to write tomorrow's plan.

You reply to the bot in plain language, or use short commands like `!started` and
`!progress` (see [Commands](#commands)).

---

## How it works

- You keep a **plan** (what you'll do, and when). The bot reads it once at the start
  of each day, and again whenever you ask it to.
- A **supervisor** runs once a minute. It reads your current task list, looks at each
  task's status and the current time, and decides what to do this minute. It has no
  memory between runs — it always acts on the current state — so restarts and manual
  edits take effect immediately.
- An **LLM** (any OpenAI-compatible model) handles the judgement calls: reading your
  plan, deciding whether your reply means you really started, summarizing progress,
  and phrasing the messages.

By default everything is stored in local files. You can instead store it in Notion,
so you can view and edit your plan and progress from anywhere — see
[Using Notion](#using-notion-optional).

---

## What you'll need

Before setting up, make sure you have:

1. A **Discord account** and a server (guild) you control, with a text channel for
   the bot.
2. An **API key for an OpenAI-compatible LLM** — for example [DeepSeek](https://platform.deepseek.com).
3. A **computer or server that stays on**. The bot only nags you while it is running,
   so for daily use it should live on an always-on machine (see [Deployment](#deployment)).

You do **not** need to know how to program, but you will use the terminal for a few
setup commands. Follow them exactly and you'll be fine.

---

## Setup

### 1. Create the Discord bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   and click **New Application**. Give it a name.
2. Open the **Bot** tab. Under **Privileged Gateway Intents**, turn on
   **Message Content Intent** — the bot needs this to read your messages.
3. Click **Reset Token**, then **Copy**. This is your bot token
   (`DISCORD_TOKEN` later). Keep it secret; anyone with it can control your bot.
4. Open **OAuth2 → URL Generator**. Check the **bot** scope, then check these
   permissions: **Send Messages**, **Read Message History**, and **Manage Messages**
   (the last one lets the bot delete its own messages for `!clear`). Copy the
   generated URL, open it in your browser, and add the bot to your server.

### 2. Find the channel and your user IDs

1. In Discord, open **Settings → Advanced** and turn on **Developer Mode**.
2. Right-click the channel you want the bot to use and choose **Copy Channel ID**
   (`DISCORD_CHANNEL_ID`).
3. Right-click your own name and choose **Copy User ID** (`DISCORD_USER_ID`). The bot
   only responds to this user.

### 3. Get an LLM API key

Sign up with an OpenAI-compatible provider (such as DeepSeek), create an API key, and
note the key, the endpoint URL, and the model name.

### 4. Install and configure

This project uses [uv](https://docs.astral.sh/uv/) to manage Python.

```bash
# Install uv (see the uv docs for other platforms)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Get the project and install its dependencies
git clone <this-repository-url>
cd procrastination-terminator
uv sync

# Create your configuration file
cp .env.example .env
```

Open `.env` in a text editor and fill in the values you collected above. At minimum:

```
DISCORD_TOKEN=your-bot-token
DISCORD_USER_ID=your-user-id
DISCORD_CHANNEL_ID=your-channel-id
LLM_API_KEY=your-llm-key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

The full list of settings is in [Configuration](#configuration). Your `.env` file
holds secrets — never share it or commit it to version control.

### 5. Run it

```bash
uv run python -m procrastination_terminator
```

The bot logs in and starts watching the clock. Write a plan (next section), and it
will begin nagging you at the right times.

---

## Writing your plan

By default your plan lives in `data/plan.txt`. You write it in plain text; only the
start of each line matters.

- A line that **starts with a date** (`MM.DD`) opens a day. Anything after the date on
  that line (a weekday, a note to yourself) is ignored.
- A line that **starts with a time** (`HH:MM`) is a task under the current day. The
  rest of the line is the task's description.
- An **indented line** under a task (with no leading time) becomes a note for that
  task — the bot uses it to know what the task actually involves.
- Any other line is ignored.

Include meals, sleep, and breaks too. They aren't nagged, but the bot uses them to
know when the previous task is meant to end.

Example:

```
07.01 Wednesday
14:00 SDE Chapter 8
15:30 Quantum revision
    focus on the entanglement problems
18:00 Dinner
19:00 Programming assignment
23:00 Sleep
```

### The daily window

A day runs on a **logical day**, not the calendar day: it starts at the **day start**
(default 04:00) and ends at the next day's start. So one day's plan must fall within
`[day start, next day start)` — earliest its 04:00, latest just before 04:00 the next
morning.

Early-morning tasks (00:00–03:59) belong to the **end** of that logical day, so write
them under **that day's** date header, not the next calendar day's. For example, if on
07.01 you stay up until a `02:00` sleep, write `02:00` under the `07.01` header.

---

## Talking to the bot

Most of the time you simply reply to the bot in plain language, in its channel:

- Tell it you've started ("starting now", "on it") and it moves the task forward.
- Answer its progress check-ins with what you actually did ("finished the first two
  problems"); it records a short summary.
- Tell it you're done and it marks the task complete.

If a reply is vague ("ok", "in a sec"), the bot treats it as not-yet-started and keeps
nagging — so be specific when you've genuinely begun. When several tasks are active at
once and it can't tell which you mean, it will ask instead of guessing.

For anything you want to be exact about, use a command.

---

## Commands

Type these in the bot's channel. `<task>` is a **fuzzy reference** — you don't need the
exact task code, just something recognizable, like `Programming` or "the afternoon one".

| Command | What it does |
|---|---|
| `!sync` | Re-read your plan and update the task list to match it. |
| `!progress` | Show a table of today's tasks: status (as an emoji), start time, and name. |
| `!progress detailed` | The same table with an extra column for each task's latest progress note. |
| `!whattodo [task]` | Break a task into 3–5 small, do-it-now steps. With no task, it uses the one active right now. |
| `!started <task>` | Mark a task as started; stops the start reminders. |
| `!completed <task>` | Mark a task as completed. |
| `!modify <instruction>` | Edit tasks in plain language, e.g. `!modify move the run to 19:00`. |
| `!reloadcontext` | Reload your context notes (only needed in Notion mode; see below). |
| `!clear [N \| 30m \| all]` | Delete the bot's own messages: the latest, the latest `N`, those from the last `30m`/`2h`/`1d`, or `all`. |

`!sync` matches tasks by their code (derived from date, time, and name). Changing a
task's time or name in the plan creates a new task and drops the old one, which resets
that task's runtime state — fine before you've started it, worth noting once you have.

---

## Configuration

All settings live in `.env`. Only the first group is required.

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Your bot's token. |
| `DISCORD_USER_ID` | Yes | Your Discord user ID; the bot only listens to you. |
| `DISCORD_CHANNEL_ID` | Yes | The channel the bot posts in and reads. |
| `LLM_API_KEY` | Yes | API key for an OpenAI-compatible model. |
| `LLM_BASE_URL` | Yes | The LLM endpoint, e.g. `https://api.deepseek.com`. |
| `LLM_MODEL` | Yes | The model name, e.g. `deepseek-v4-flash`. |
| `BOT_NAME` | No | What the bot calls itself (default: `Bot`). |
| `TIMEZONE` | No | IANA timezone name, e.g. `Europe/London` (default). Handles daylight saving automatically. |
| `DAY_START` | No | Daily sync time and logical-day boundary, `HH:MM` (default: `04:00`). |
| `DAY_END` | No | Daily summary + plan nag time, `HH:MM` (default: `23:00`). Must not pass `DAY_START`. |
| `POLL_SECONDS` | No | Supervisor poll interval in seconds (default: `60`). |
| `PERSONALITY_GRANULARITY` | No | How often the message personality is re-chosen: `per_task` (default), `per_message`, or `per_day`. |
| `MESSAGE_LANG` | No | Language of the bot's messages: `zh` or `en` (default: `en`). |
| `DIALOGUE_HISTORY` | No | How many recent messages to use as conversational context (default: `12`). |
| `PLAN_PATH`, `PROGRESS_PATH`, `HISTORY_PATH`, `CONTEXT_PATH` | No | File-backend data file locations (defaults under `data/`). |
| `STORAGE_BACKEND` | No | `file` (default) or `notion`. |
| `NOTION_API_KEY`, `NOTION_DB_ID`, `NOTION_PLAN_PAGE_ID`, `NOTION_CONTEXT_PAGE_ID` | If `notion` | See [Using Notion](#using-notion-optional). |

You can also keep a `data/context.txt` file with standing notes for the bot — your
glossary, tone preferences, and background. The bot reads it (never writes it) and
folds it into how it understands your words and phrases its messages. It does **not**
change *when* or *whether* you're nagged.

---

## Using Notion (optional)

Instead of local files, you can store your plan, progress, and context in Notion, so
you can view and edit them from any device.

1. **Create a Notion connection.** Go to
   [notion.so/my-integrations](https://www.notion.so/my-integrations), create a new
   **internal** connection with a **token**, and copy the token — this is your
   `NOTION_API_KEY`. Keep it secret.
2. **Create a parent page** in your workspace (for example, "Procrastination
   Terminator") and give the connection access to it (the page's `···` menu →
   **Connections**).
3. **Provision the database and pages.** Run:

   ```bash
   uv run python -m procrastination_terminator init-notion <parent-page-url-or-id>
   ```

   Your token must already be in `.env` as `NOTION_API_KEY`. This creates a `tasks`
   database and empty `plan` and `context` pages under your parent page, and prints
   three IDs.
4. **Finish your `.env`.** Add the printed IDs and switch the backend:

   ```
   STORAGE_BACKEND=notion
   NOTION_DB_ID=...
   NOTION_PLAN_PAGE_ID=...
   NOTION_CONTEXT_PAGE_ID=...
   ```
5. **Write your plan** on the `plan` page (same format as above), then start the bot
   and send `!sync`. Your tasks appear in the `tasks` database.

Notion controls how rows and columns are displayed, so to see your tasks in time
order, sort the database view by the `code` column (ascending). After you edit the
`context` page, send `!reloadcontext` to have the change take effect immediately;
otherwise it refreshes at the start of the next day.

---

## Deployment

The bot only nags you while it is running, so for daily use it should run on an
always-on machine. In `file` mode, your task state lives in `data/`, which must sit on
storage that survives restarts — many free hosts wipe their filesystem on restart,
which would lose your progress. Use a persistent volume (such as a Railway Volume or
Render Disk) or a VPS. In `notion` mode, your state lives in Notion, so this is not a
concern.

### Running 24/7 with systemd

On any Linux VPS, the tidiest way to keep the bot running — restarting it if it
crashes and starting it on boot — is a systemd service. After you've cloned the
project, run `uv sync`, and filled in `.env` (see [Setup](#setup)), create the service
file (adjust `User` and the two paths to match your machine; `which uv` prints the uv
path):

```ini
# /etc/systemd/system/procrastination-terminator.service
[Unit]
Description=Procrastination Terminator Discord bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/procrastination-terminator
ExecStart=/home/ubuntu/.local/bin/uv run python -m procrastination_terminator
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now procrastination-terminator
sudo systemctl status procrastination-terminator   # should be active (running)
journalctl -u procrastination-terminator -f         # follow the logs
```

Because the service is **enabled**, it starts automatically on boot — after an
accidental shutdown or reboot the bot comes back on its own; `systemctl status` confirms
it. Day-to-day management:

```bash
# Update to the latest code and apply it
cd ~/procrastination-terminator && git pull && uv sync
sudo systemctl restart procrastination-terminator

# Apply a changed .env (restart is enough — no need to pull)
sudo systemctl restart procrastination-terminator

# Stop the bot for now (it will still auto-start on the next reboot)
sudo systemctl stop procrastination-terminator

# Stop it and turn off auto-start (fully off until you re-enable)
sudo systemctl disable --now procrastination-terminator
```

`git pull` never touches your `.env` or `data/` (both gitignored), so updating is safe.

For a full walkthrough on Oracle Cloud's free ARM (Ampere A1) instance — creating the
VM, connecting, and getting your plan onto it — see
[`docs/deploy-oracle.md`](docs/deploy-oracle.md).

---

## Development

```bash
uv run pytest        # run the tests
uv run ruff check    # lint
uv run ruff format   # format
uv run mypy .        # type-check (strict)
```

The full product specification is in [`docs/SPEC.md`](docs/SPEC.md).
