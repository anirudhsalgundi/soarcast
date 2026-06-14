# main script to run the SOARcast digest and notification process
# Running as a cronjob with the keys in a private repo

from soarcast.nightplan import get_relevant_runs, build_digest
from soarcast.notify import send_soarcast_digest, send_slack_failure
import logging
from datetime import datetime
from pathlib import Path
import os
SOARCAST_WEBHOOK = os.environ.get("SOARCAST_WEBHOOK")


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
        relevant_runs = get_relevant_runs()
        digest = build_digest(relevant_runs)
        send_slack_digest(digest)
    except Exception as e:
        logging.error(f"SOARcast failed: {e}")
        send_slack_failure(e, SOARCAST_WEBHOOK)

if __name__ == "__main__":
    main()