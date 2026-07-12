from soarcast.lco_monitor import main as get_lco_digest
from soarcast.notify import send_lco_changes, send_lco_aeon_reminder, send_slack_failure
from soarcast.constants import Constants
from datetime import datetime
import logging


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
        digest = get_lco_digest()
        send_lco_changes(digest)
        send_lco_aeon_reminder(digest)
    except Exception as e:
        send_slack_failure(e, Constants.LCO_CHANGES_WEBHOOK)

if __name__ == "__main__":
    main()