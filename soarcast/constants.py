import os
from pathlib import Path


class Constants:
    # tokens / webhooks
    LCO_TOKEN = os.environ.get("LCO_TOKEN")
    FRITZ_TOKEN = os.environ.get("FRITZ_TOKEN")
    SOARCAST_WEBHOOK = os.environ.get("SOARCAST_WEBHOOK")
    LCO_CHANGES_WEBHOOK = os.environ.get("LCO_CHANGES_WEBHOOK")
    LCO_AEON_WEBHOOK = os.environ.get("LCO_AEON_WEBHOOK")

    # base URLs
    LCO_BASE = "https://observe.lco.global"
    FRITZ_BASE = "https://fritz.science"

    # AEON night calendar (Google Sheet, published as CSV)
    AEON_CALENDAR_SHEET_ID = "10L463nYJEF1SbErWGjLQcZLusjS8v9MCGTrDZLXfZtY"
    AEON_CALENDAR_GID = "0"
    AEON_CALENDAR_CSV_URL = (
        f"https://docs.google.com/spreadsheets/d/{AEON_CALENDAR_SHEET_ID}"
        f"/export?format=csv&gid={AEON_CALENDAR_GID}"
    )

    # scanning roster (Google Sheet, published as CSV)
    SCANNING_ROSTER_SHEET_ID = "10SA_ZYQPheFbJ9Ib6AgBS9y5syDA2Ce-MBHxKfp_bG0"
    SCANNING_ROSTER_GID = "1776126771"
    SCANNING_ROSTER_CSV_URL = (
        f"https://docs.google.com/spreadsheets/d/{SCANNING_ROSTER_SHEET_ID}"
        f"/export?format=csv&gid={SCANNING_ROSTER_GID}"
    )

    # local persistent state (survives restarts of the always-on daemon)
    STATE_DIR = Path.home() / ".soarcast"
    LCO_SNAPSHOT_PATH = STATE_DIR / "lco_state.json"
    DAEMON_STATE_PATH = STATE_DIR / "daemon_state.json"
    LOG_DIR = STATE_DIR / "logs"

    # instrument ids on Fritz that correspond to SOAR
    SOAR_INSTRUMENT_IDS = {1107, 1108, 1109}

    # timing knobs
    LCO_POLL_INTERVAL_SEC = 120          # how often to poll LCO for portal changes ("instantly" within reason)
    AEON_REMINDER_INTERVAL_SEC = 3 * 60 * 60   # "every 3 hours" countdown reminder
    SEMESTER_END_WARNING_DAYS = 10       # start nagging this many days before calendar/roster run out
    NAG_INTERVAL_SEC = 6 * 60 * 60       # how often to repeat "please update the sheet" nags


Constants.STATE_DIR.mkdir(parents=True, exist_ok=True)
Constants.LOG_DIR.mkdir(parents=True, exist_ok=True)
