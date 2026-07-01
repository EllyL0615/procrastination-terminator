# Procrastination Terminator

A single-user Discord bot that nags a student through their daily study plan. It
reads a hand-written `plan.txt`, treats each study/work task as a lifecycle
object, and messages you (in a dedicated channel) to start, checks your progress at the midpoint and end, and
prompts you each night to plan tomorrow.

The full product spec lives in [`docs/SPEC.md`](docs/SPEC.md).

## How it works (in one breath)

- Two files drive everything: `plan.txt` (you write it) and `progress.csv` (the
  bot maintains it; you may hand-edit it too). `history.csv` archives past days.
- A stateless **supervisor** runs every minute, reads the current `progress.csv`,
  and decides each task's next action from its state and the current time. It
  dedupes via timestamps in the file, so restarts and manual edits just work.
- The LLM does the judgement: parsing the plan, classifying task type, deciding
  whether a reply is genuine, condensing progress, and writing the message tone.

## Layout

```
src/procrastination_terminator/
  config.py        # Config from env vars (SPEC §7)
  models.py        # Task / Status / TaskType (SPEC §2)
  backoff.py       # nag backoff curve, pure          [implemented + tested]
  daytime.py       # logical-day / cross-midnight, pure [implemented + tested]
  monitor.py       # per-minute decision table, pure   [stub]
  store.py         # progress.csv / history.csv IO      [stub]
  plan_parser.py   # parse plan.txt + set-diff sync     [stub]
  llm.py           # OpenAI-compatible LLM client       [stub]
  bot.py           # discord.py wiring                  [stub]
tests/             # unit tests for the pure modules
```

## Develop

```bash
uv sync                 # create the env and install deps
uv run pytest           # run tests
uv run ruff check       # lint
uv run ruff format      # format
uv run mypy .           # type-check (strict)
```

## Run

```bash
cp .env.example .env    # then fill in the secrets
uv run python -m procrastination_terminator
```

## Deploy

`progress.csv` must live on storage that survives restarts. Many free hosts have
ephemeral filesystems that wipe on restart, which would lose all task state — use
a persistent volume (Railway Volume, Render Disk) or a VPS. See SPEC §9.
