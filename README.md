# SOARcast

SOARcast watches the SOAR/AEON observing pipeline and posts to Slack:

- New/changed requests on the LCO observe portal
- AEON night countdowns ("X hours left...") and night-start announcements
- SOAR observing run digests, announced once per night with newly assigned
  targets posted as they show up (no repeats)
- Reminders to update the AEON night calendar / scanning roster Google
  Sheets when they're about to run out of scheduled dates

It's meant to run continuously on an always-on machine (a lab laptop, a
small server, etc.) rather than as a cronjob — the daemon polls on its own
schedule and remembers what it has already announced, so it survives
restarts without spamming duplicate messages.

## Install

```bash
git clone <this repo>
cd soarcast
uv sync          # or: pip install -e .
```

## Configure

Set these environment variables (e.g. in `~/.bashrc` / `~/.zshrc`, or a
private `.env` you `source` before running):

```bash
export FRITZ_TOKEN="..."   # Fritz API token
export LCO_TOKEN="..."                  # LCO observe portal API token
export SOARCAST_WEBHOOK="..."           # Slack webhook: SOAR run digest
export LCO_CHANGES_WEBHOOK="..."        # Slack webhook: LCO portal changes
export LCO_AEON_WEBHOOK="..."           # Slack webhook: AEON reminders/targets
```

The AEON night calendar and scanning roster are read directly from their
Google Sheets (must be shared as "Anyone with the link can view") — no
local CSV to maintain. URLs/IDs live in `soarcast/constants.py`.

Contact anirudhsalgundi@gmail.com for slack webhook URLs if you don't any of the above.


State (LCO snapshot, what's already been announced) is stored under
`~/.soarcast/` and logs under `~/.soarcast/logs/`.

## Run

For the always-on daemon (recommended):

```bash
soarcast-daemon
```

This polls LCO/Fritz every couple of minutes and the sheets every 30
minutes, forever, until stopped.

One-shot commands are still available if you'd rather drive things from
cron:

```bash
soarcast-run     # SOAR run digest, once
lco-monitor      # LCO portal changes + AEON reminder, once
```

## Deploying on an always-on laptop

Pick whichever of these you're more comfortable with — both keep
`soarcast-daemon` running after you close the terminal / disconnect SSH.

### Option A: screen

```bash
screen -S soarcast
soarcast-daemon
# detach: Ctrl-A then D

# reattach later:
screen -r soarcast

# see running sessions:
screen -ls
```

### Option B: tmux

```bash
tmux new -s soarcast
soarcast-daemon
# detach: Ctrl-B then D

# reattach later:
tmux attach -t soarcast

# see running sessions:
tmux ls
```

Either way, once detached the daemon keeps running as long as the laptop
is on and doesn't sleep (disable sleep/screen-lock-on-lid-close if the lid
will be closed). Check `~/.soarcast/logs/daemon_*.log` for the latest run's
output if something looks off.
