# main script to run the SOARcast digest and notification process
# Running as a cronjob with the keys in a private repo

from soarcast.nightplan import get_relevant_runs, build_digest
from soarcast.notify import send_soarcast_digest, send_slack_failure
from soarcast.constants import Constants
import logging
from datetime import datetime


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s at %(asctime)s] — %(message)s",
        handlers=[
            logging.FileHandler(Constants.LOG_DIR / f"run_{timestamp}.log"),
            logging.StreamHandler()
        ]
    )

    try:
        relevant_runs = get_relevant_runs()
        digest = build_digest(relevant_runs)
        send_soarcast_digest(digest)
    except Exception as e:
        logging.error(f"SOARcast failed: {e}")
        send_slack_failure(e, Constants.SOARCAST_WEBHOOK)

if __name__ == "__main__":
    main()