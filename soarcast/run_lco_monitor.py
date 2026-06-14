import os
from soarcast.lco_monitor import main as get_lco_digest
from soarcast.notify import send_lco_changes, send_lco_aeon_reminder, send_slack_failure
from datetime import datetime
from pathlib import Path
import logging
LCO_CHANGES_WEBHOOK = os.environ.get("LCO_CHANGES_WEBHOOK")

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR = Path.home() / ".soarcast" / "logs"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s at %(asctime)s] — %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"run_{timestamp}.log"),
        logging.StreamHandler()
        ]
    )

    try:
        digest = get_lco_digest()
        send_lco_changes(digest)
        send_lco_aeon_reminder(digest)
    except Exception as e:
        send_slack_failure(e, os.environ.get("LCO_CHANGES_WEBHOOK"))

if __name__ == "__main__":
    main()