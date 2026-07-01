# Deploying on an Oracle Cloud free ARM instance

This walks through running the bot 24/7 on an [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/)
Ampere A1 (ARM) instance. The bot is a long-running process (not a cron job), so it is
managed as a systemd service that restarts on crash and starts on boot.

The bot only makes **outbound** connections (to Discord and your LLM), so you do **not**
need to open any inbound ports or change security rules.

## 1. Create the instance

1. In the Oracle Cloud console, go to **Compute → Instances → Create instance**.
2. Under **Image and shape**, pick an **Ampere (ARM)** shape (`VM.Standard.A1.Flex`);
   1 OCPU / 6 GB RAM is plenty. Choose a **Ubuntu 22.04 or 24.04** image.
3. Add (or generate) an SSH key pair — keep the private key.
4. Create the instance and note its **public IP**.

> Free-tier A1 capacity is sometimes unavailable in a region; if creation fails with an
> out-of-capacity error, retry later or pick another availability domain.

## 2. Connect

Point `-i` at the private key you downloaded when creating the instance (the default
user on Ubuntu images is `ubuntu`):

```bash
ssh -i <path-to-private-key> ubuntu@<public-ip>
```

On Windows PowerShell the key path uses `$env:USERPROFILE`, e.g.:

```powershell
ssh -i $env:USERPROFILE\.ssh\<your-key> ubuntu@<public-ip>
```

If your key lives in the default location (`~/.ssh/id_*`), you can drop the `-i` flag.

## 3. Install Python (via uv) and git

```bash
sudo apt update && sudo apt install -y git
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env   # put uv on PATH (as the installer prints)
```

## 4. Get the code

```bash
cd ~
git clone https://github.com/EllyL0615/procrastination-terminator.git
cd procrastination-terminator
uv sync
```

## 5. Configure secrets and data

`.env` and `data/` are gitignored, so they don't exist on a fresh clone. The easiest
way is to prepare these files in an editor on your own machine, then `scp` them up. How
many files you send depends on the storage backend:

- **Notion mode** (`STORAGE_BACKEND=notion`) — just `.env`. Your plan, progress, and
  context all live in Notion. See the README's
  [Using Notion](../README.md#using-notion-optional) section.
- **File mode** (the default) — three files: `.env`, `data/plan.txt`, and
  `data/context.txt`. `progress.csv` / `history.csv` are created automatically.

On your own machine, fill in `.env` (copy `.env.example` and edit — the `DISCORD_*`,
`LLM_*`, and storage settings) and, in file mode, write your `data/plan.txt` and
`data/context.txt`. Then copy them up (run locally, not on the instance):

```bash
# .env — everyone
scp -i <path-to-private-key> .env ubuntu@<public-ip>:~/procrastination-terminator/.env

# plan and context — file mode only
scp -i <path-to-private-key> data/plan.txt data/context.txt \
  ubuntu@<public-ip>:~/procrastination-terminator/data/
```

Back on the instance, confirm it runs, then stop it with Ctrl+C:

```bash
uv run python -m procrastination_terminator
```

## 6. Run it as a service

Follow the [Running 24/7 with systemd](../README.md#running-247-with-systemd) section
of the README to install the systemd unit, then enable it:

```bash
sudo systemctl enable --now procrastination-terminator
sudo systemctl status procrastination-terminator
```

`status` should show **active (running)**. Right after startup it's captured before the
bot has logged in, so confirm the Discord connection from the logs:

```bash
journalctl -u procrastination-terminator -n 20 --no-pager
```

You want to see `logging in using static token` followed by `connected to Gateway`. Then
you're done — the bot runs in the background and survives logout and reboots, so you can
close the SSH session.

For day-to-day management — updating, restarting, stopping, and following the logs — see
the README's [Running 24/7 with systemd](../README.md#running-247-with-systemd) section.

## Using VS Code Remote-SSH (optional)

If you'd rather edit files and browse logs in VS Code instead of a terminal editor, the
[Remote-SSH](https://code.visualstudio.com/docs/remote/ssh) extension lets you open the
instance as if it were a local folder. It complements the steps above — you still run
the `systemctl` / `journalctl` commands, but in VS Code's built-in terminal, and you
edit `.env`, `data/plan.txt`, etc. in the normal editor.

### Set it up

1. Install the **Remote - SSH** extension in VS Code (Extensions → search
   "Remote - SSH", by Microsoft).
2. Add the instance to your SSH config so you don't retype the key each time. Open the
   Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) → **Remote-SSH: Open SSH
   Configuration File** → pick your user config (`~/.ssh/config`), and add:

   ```
   Host oracle-bot
       HostName <public-ip>
       User ubuntu
       IdentityFile ~/.ssh/<your-private-key>
   ```

3. Command Palette → **Remote-SSH: Connect to Host** → `oracle-bot`. VS Code installs
   its server on the instance the first time (takes a minute).
4. Once connected (bottom-left shows **SSH: oracle-bot**), **File → Open Folder** →
   `/home/ubuntu/procrastination-terminator`.

### What it makes easier

- **Editing config.** Open `.env` directly in the editor instead of `nano` — the same
  file the bot reads. Save, then restart the service (next point) to apply.
- **Editing your plan (file backend).** Open and edit `data/plan.txt` in the editor;
  send `!sync` in Discord afterward. No more `scp` round-trips.
- **Running commands.** Use **Terminal → New Terminal** — it opens a shell *on the
  instance*, so `sudo systemctl restart procrastination-terminator`,
  `git pull && uv sync`, and `journalctl -u procrastination-terminator -f` all run there.

### What it does not change

The systemd service runs independently of VS Code — closing the window or disconnecting
does **not** stop the bot. Remote-SSH is only your editing/terminal front-end; the
service keeps running on the instance regardless.

## Notes

- **Timezone.** The bot's logic uses its configured `TIMEZONE` (default `Europe/London`)
  with tz-aware datetimes bundled via the `tzdata` dependency, so the instance's OS
  timezone (usually UTC) doesn't matter — you don't need to change it.
- **Data durability.** Oracle may reclaim idle free-tier instances. In `file` mode, back
  up `data/*.csv` periodically (e.g. `scp` them down, or a cron `rsync`); in `notion`
  mode there's nothing to back up.
