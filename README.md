# Procrastination Terminator

A single-user Discord bot that keeps you moving through a daily study plan. You
write down what you intend to do and when; the bot watches the clock, messages
you to start each task on time, checks in on your progress, and wraps up your
day. It is built for one person — you — and only listens to you, in one channel.

- [Introduction](#introduction)
  - [What it does](#what-it-does)
  - [How it works](#how-it-works)
- [Setup](#setup)
  - [1. Preparation](#1-preparation)
  - [2. Install](#2-install)
  - [3. Configure](#3-configure)
  - [4. First run](#4-first-run)
- [Usage](#usage)
  - [Configuration (`.env`)](#configuration-env)
  - [Writing your plan (`data/plan.txt`)](#writing-your-plan-dataplantxt)
  - [Standing context (`data/context.txt`, optional)](#standing-context-datacontexttxt-optional)
  - [Talking to the bot](#talking-to-the-bot)
  - [Using Notion (optional)](#using-notion-optional)
- [Deployment](#deployment)
  - [Start on login (Windows)](#start-on-login-windows)
  - [Running 24/7 with systemd](#running-247-with-systemd)
- [Development](#development)

---

## Introduction

### What it does

- **Nags you to start.** When a task's time arrives and you haven't begun, the
  bot messages you with one concrete first step, and keeps reminding you at
  growing intervals until you do.
- **Checks your progress.** Halfway through a task and again at its end, it
  asks how things are going and records a short summary of your reply.
- **Confirms completion.** When you say you're done, the task is marked
  complete.
- **Wraps up the day.** Each night it summarizes what you finished and reminds
  you to write tomorrow's plan.

A typical exchange:

> **Bot:** It's 09:00 — time for *Finish the monthly report*. Open the draft
> and reread the last paragraph you wrote to get moving. Tell me once you've
> started.
>
> **You:** starting now
>
> **Bot:** Logged. I'll check in later.
>
> **Bot** *(at the halfway point)*: How is the report coming along?
>
> **You:** summary section done, just the intro left
>
> **Bot:** Noted. Wrap up the intro by 12:30 — lunch is next.

### How it works

- Your plan file is synced into a task table when the bot starts, at day start
  (04:00), and whenever you send `!sync`.
- A supervisor wakes once a minute, compares each task's status with the
  clock, and decides what to say. It keeps no memory between runs, so restarts
  and hand-edits to the task table take effect immediately.
- An LLM (any OpenAI-compatible model) handles the judgement calls: deciding
  whether your reply means you really started, summarizing progress, and
  phrasing every message.

---

## Setup

You don't need to know how to program: step 1 is clicking through a few
websites to collect keys, and the rest is a few terminal commands to copy.

### 1. Preparation

This step collects the six values the bot needs. Copy these lines into a
scratch note now, and fill in each one as you go (the last two are already
filled in for DeepSeek — adjust if you use another provider). Keep the note
private, and delete it once your `.env` is done in step 3:

```
DISCORD_TOKEN=
DISCORD_USER_ID=
DISCORD_CHANNEL_ID=
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

#### 1.1 Create the Discord bot

You'll need a **Discord account** and a server you control, with a text
channel for the bot. No server? Create one just for yourself: the **+**
button at the bottom of Discord's server list. Then:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   and click **New Application**. Give it a name.
2. Open the **Bot** tab. Under **Privileged Gateway Intents**, turn on
   **Message Content Intent** — the bot needs this to read your messages.
3. Click **Reset Token**, then **Copy**. This is your bot token — fill it into
   your `DISCORD_TOKEN` line. Keep it secret; anyone with it can control your
   bot.
4. Open **OAuth2 → URL Generator**. Check the **bot** scope, then check these
   permissions: **Send Messages**, **Read Message History**, and
   **Manage Messages** (the last one lets the bot delete its own messages for
   `!clear`). Copy the generated URL, open it in your browser, and add the bot
   to your server.

#### 1.2 Find the channel and your user IDs

1. In Discord, open **Settings → Advanced** and turn on **Developer Mode**.
2. Right-click the channel you want the bot to use and choose **Copy Channel
   ID** (`DISCORD_CHANNEL_ID`).
3. Right-click your own name and choose **Copy User ID** (`DISCORD_USER_ID`).
   The bot only responds to this user.

#### 1.3 Get an LLM API key

Any OpenAI-compatible provider works — billing is per use, and one person's
daily use costs very little. [DeepSeek](https://platform.deepseek.com) is a
cheap example:

1. Sign up at [platform.deepseek.com](https://platform.deepseek.com) and add a
   little credit.
2. Open **API keys**, create a key, and copy it right away (it is shown only
   once). This is `LLM_API_KEY`.
3. Note the endpoint and model name. For DeepSeek that's
   `https://api.deepseek.com` (`LLM_BASE_URL`) and a model name from their
   docs, e.g. `deepseek-v4-flash` (`LLM_MODEL`).

### 2. Install

The commands from here on go into a **terminal**: on Windows, search for
**PowerShell** in the Start menu; on macOS, open **Terminal** (Applications →
Utilities). Copy them exactly.

You do **not** need to install Python: the project uses
[uv](https://docs.astral.sh/uv/), which downloads the right Python by itself.

**First, install uv.** On Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

On macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then **close and reopen the terminal** — the `uv` command isn't found until
you do.

**Next, download the project.** Two ways; pick one:

- **With git** (easier to update later). If you don't have git: on Windows,
  install it from [git-scm.com](https://git-scm.com/downloads) (accepting
  every default is fine); on macOS, running `git` in the terminal for the
  first time offers to install it. Then:

  ```
  git clone https://github.com/EllyL0615/procrastination-terminator.git
  cd procrastination-terminator
  ```

- **Without git.** On the
  [project page](https://github.com/EllyL0615/procrastination-terminator),
  click **Code → Download ZIP** and unzip it. Then move the terminal into the
  unzipped folder: type `cd ` (with a trailing space), drag the folder onto
  the terminal window, and press Enter. (Updating later means re-downloading
  the ZIP instead of running `git pull`.)

**Finally, install the dependencies:**

```
uv sync
```

### 3. Configure

Create your configuration file from the template — on Windows:

```powershell
copy .env.example .env
```

on macOS / Linux:

```bash
cp .env.example .env
```

Keep the file named exactly `.env` — Windows Notepad may try to add `.txt`
when saving.

Then open `.env` in a text editor and paste in the six lines you prepared in
[step 1](#1-preparation), replacing the matching lines already there.
Everything else in the file is optional — customize it to taste with
[Configuration](#configuration-env), or leave it alone. Your `.env` holds
secrets — never share it or commit it to version control.

### 4. First run

#### 4.1 Write a plan

Create a folder `data` inside the project, and inside it a file `plan.txt` —
format in [Writing your plan](#writing-your-plan-dataplantxt); starting with
just today and two or three tasks is fine. Optionally, also add a
`data/context.txt` with standing notes for the bot (see
[Standing context](#standing-context-datacontexttxt-optional)).

If you'd rather keep your plan in Notion than in local files, set that up
instead — see [Using Notion](#using-notion-optional).

#### 4.2 Run it

```bash
uv run python -m procrastination_terminator
```

The bot logs in and loads your plan. To check everything works, send
`!progress` in the bot's channel — you should get back a table of today's
tasks. From here on it just runs alongside your day — see
[Talking to the bot](#talking-to-the-bot).

Good to know:

- The bot can only nag you **while it is running**: close the terminal or let
  the computer sleep, and it stays silent until you start it again. Your own
  computer is fine for everyday use — see [Deployment](#deployment) for
  hands-off options.
- Stopping and restarting is always safe — tasks and progress live in `data/`
  (or Notion), and the bot picks up from there.
- If you edit `plan.txt` while the bot is running, send `!sync` to apply it.
- To keep it alive through the day, stop the computer from sleeping: on
  Windows, Settings → System → Power → set Sleep to **Never** while plugged
  in; on macOS, start the bot with
  `caffeinate -i uv run python -m procrastination_terminator`.

---

## Usage

### Configuration (`.env`)

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
| `DAY_END` | No | Daily summary + plan nag time, `HH:MM` (default: `23:00`). May run past midnight, but no later than the next day's `DAY_START`. |
| `POLL_SECONDS` | No | Supervisor poll interval in seconds (default: `60`). |
| `PERSONALITY_GRANULARITY` | No | How often the message personality is re-chosen: `per_task` (default), `per_message`, or `per_day`. |
| `MESSAGE_LANG` | No | Language of the bot's messages: `zh` or `en` (default: `en`). |
| `DIALOGUE_HISTORY` | No | How many recent messages to use as conversational context (default: `12`). |
| `PLAN_PATH`, `PROGRESS_PATH`, `HISTORY_PATH`, `CONTEXT_PATH` | No | File-backend data file locations (defaults under `data/`). |
| `STORAGE_BACKEND` | No | `file` (default) or `notion`. |
| `NOTION_API_KEY`, `NOTION_DB_ID`, `NOTION_PLAN_PAGE_ID`, `NOTION_CONTEXT_PAGE_ID` | If `notion` | See [Using Notion](#using-notion-optional). |

### Writing your plan (`data/plan.txt`)

Your plan is plain text in `data/plan.txt`. Only the start of each line
matters:

- A line starting with a **date** (`MM.DD`, e.g. `07.01`) opens a day.
  Anything after the date on that line (a weekday, a note to yourself) is
  ignored.
- A line starting with a **time** (`HH:MM`, 24-hour) is a task under the
  current day; the rest of the line is the task's name.
- **Every other line is free text.** Lines under a task describe what it
  involves; the bot reads them as that task's notes.

Include meals, sleep, and breaks: they aren't nagged, but each task ends where
the next one starts, so the bot needs them to know when work is meant to stop.

```
07.01 Wednesday
09:00 Finish the monthly report
    the summary section is still missing
12:30 Lunch
14:00 Study Spanish
    lesson 12 plus its exercises
18:00 Dinner
19:00 Clean the apartment
23:00 Sleep
```

Rules worth knowing:

- Times are **24-hour**: `2:30` is half past two at night; an afternoon task
  is `14:30`.
- There is no `24:00` — write `00:00`, and keep after-midnight tasks
  (00:00–03:59) under the **same day's** date header (see below).
- Don't start a free-text line with a time, or it becomes a new task.
- Tasks must not overlap — each one ends when the next begins.
- A task's identity is its date + time + the first word of its name. Change
  any of those and `!sync` treats it as a new task, resetting its progress —
  harmless before you've started it.
- Clear names help the bot judge what to nag: study and work get nagged;
  things like `Dinner` or `Sleep` don't. If it judges wrong, edit that row's
  `type` column by hand (`study` / `work` / `outing` / `other`).

#### The daily window

A day runs from **day start** (04:00) to the next day's 04:00 — so "tonight
past midnight" still belongs to today. If on `07.01` you stay up until a
2 a.m. bedtime, the line `02:00 Sleep` goes under the `07.01` header.

### Standing context (`data/context.txt`, optional)

You can keep a file `data/context.txt` with standing notes for the bot: your
terms and abbreviations, tone preferences, background about yourself. The bot
reads it (never writes it) and uses it to understand what you mean and to
phrase its messages. It does **not** change when or whether you get nagged —
timing and decisions come only from your plan and the clock (bot language is
`MESSAGE_LANG`, timezone is `TIMEZONE`). Edits apply immediately in file mode;
in Notion mode send `!reloadcontext`.

### Talking to the bot

Most of the time you simply reply in plain language, in the bot's channel:

- Tell it you've started ("starting now", "on it") and it moves the task
  forward.
- Answer its check-ins with what you actually did ("finished the first two
  problems"); it records a short summary.
- Tell it you're done and it marks the task complete.

If a reply is vague ("ok", "in a sec"), the bot treats it as not-yet-started
and keeps nagging — be specific when you've genuinely begun. When several
tasks are active at once and it can't tell which you mean, it asks instead of
guessing.

For anything you want to be exact about, use a command.

#### Commands

Type these in the bot's channel. `<task>` is a **fuzzy reference** — you don't
need the exact task code, just something recognizable, like `Programming` or
"the afternoon one".

| Command | What it does |
|---|---|
| `!sync` | Re-read your plan and update the task list to match it. |
| `!progress` | Show a table of today's tasks: status (as an emoji), start time, and name. |
| `!progress detailed` | The same table with each task's latest progress note. |
| `!whattodo [task]` | Break a task into 3–5 small, do-it-now steps. With no task, it uses the one active right now. |
| `!started <task>` | Mark a task as started; stops the start reminders. |
| `!completed <task>` | Mark a task as completed. |
| `!modify <instruction>` | Edit tasks in plain language, e.g. `!modify move the run to 19:00`. |
| `!reloadcontext` | Reload your context notes (only needed in Notion mode). |
| `!clear [N \| 30m \| all]` | Delete the bot's own messages: the latest, the latest `N`, those from the last `30m`/`2h`/`1d`, or `all`. |

### Using Notion (optional)

Instead of local files, you can store your plan, progress, and context in
Notion, so you can view and edit them from any device.

1. **Create a Notion connection.** Go to
   [notion.so/my-integrations](https://www.notion.so/my-integrations), create
   a new **internal** connection with a **token**, and copy the token. Keep it
   secret, and add it to your `.env` right away:

   ```
   NOTION_API_KEY=your-token
   ```
2. **Create a parent page** in your workspace (for example, "Procrastination
   Terminator"), then:
   - Give the connection access to it: the page's `···` menu →
     **Connections**.
   - Copy a link to it: **Share → Copy link** (if you use Notion in a
     browser, the page's address works too).
3. **Provision the database and pages.** Run:

   ```bash
   uv run python -m procrastination_terminator init-notion <parent-page-url-or-id>
   ```

   Replace `<parent-page-url-or-id>` with the page link you copied in step 2.
   This creates a `tasks` database and empty `plan` and `context` pages under
   your parent page, and prints three IDs.
4. **Finish your `.env`.** Add the printed IDs and switch the backend:

   ```
   STORAGE_BACKEND=notion
   NOTION_DB_ID=...
   NOTION_PLAN_PAGE_ID=...
   NOTION_CONTEXT_PAGE_ID=...
   ```
5. **Write your plan** on the `plan` page (same format as above), then start
   the bot and send `!sync`. Your tasks appear in the `tasks` database.

One thing to set up **once by hand**: the Notion API can't configure table
views, so open the `tasks` database and adjust its view yourself. This is
purely cosmetic — the bot reads and sorts the data on its own.

1. **Sort rows**: add a sort on the `code` column, ascending. The code encodes
   logical-day order (after-midnight tasks count as hours 24–27), so this
   single sort shows rows exactly as `!progress` does.
2. **Arrange columns** to taste, e.g. `date`, `planned_time`, `task`, `type`,
   `status`, `notes`, `actual_time`, `latest_progress`,
   `latest_progress_time`, `code`, `archived` — and feel free to hide `code`
   (it's the machine-facing row identity; everything you'd read is in the
   other columns).

After you edit the `context` page, send `!reloadcontext` to apply the change
immediately; otherwise it refreshes at the next day start.

---

## Deployment

For everyday use on your own computer, [First run](#4-first-run) already covers it —
the options below keep the bot running without you thinking about it.

### Start on login (Windows)

Any Windows machine that stays on can run the bot automatically. Create a file
`procrastination-terminator.bat` containing the following, with the path on
the second line **replaced by where you actually put the project**:

```bat
@echo off
cd /d C:\path\to\procrastination-terminator
uv run python -m procrastination_terminator
```

Press `Win+R`, type `shell:startup`, press Enter, and move the file into the
folder that opens. The bot now starts every time you log in, in a terminal
window that stays open — closing that window stops the bot.

### Running 24/7 with systemd

On a Linux server, the tidiest way to keep the bot running — restarting it if
it crashes and starting it on boot — is a systemd service. After you've cloned
the project, run `uv sync`, and filled in `.env` (see [Setup](#setup)), create
the service file (adjust `User` and the two paths to match your machine;
`which uv` prints the uv path):

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
accidental shutdown or reboot the bot comes back on its own. Day-to-day
management:

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

`git pull` never touches your `.env` or `data/` (both gitignored), so updating
is safe.

For a full walkthrough on Oracle Cloud's free ARM (Ampere A1) instance —
creating the VM, connecting, and getting your plan onto it — see
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
