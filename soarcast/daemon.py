# Always-on daemon for SOARcast.
#
# Unlike run_soarcast.py / run_lco_monitor.py (meant for cron, one-shot),
# this is meant to be started once on an always-on laptop (see README for
# screen/tmux setup) and left running: it polls LCO/Fritz/the AEON sheets on
# their own cadences and only posts to Slack when something is actually new,
# using soarcast/state.py to remember what's already been announced.

import logging
import time
from datetime import datetime
from pathlib import Path

from soarcast.constants import Constants
from soarcast.state import DaemonState
from soarcast.nightplan import get_relevant_runs, build_digest
from soarcast.lco_monitor import (
    get_active_proposals,
    get_all_requestgroups,
    load_snapshot,
    save_snapshot,
    detect_changes,
    get_aeon_reminder,
    build_lco_digest,
)
from soarcast.notify import (
    send_lco_changes,
    maybe_send_aeon_reminder,
    maybe_send_soar_run_updates,
    maybe_send_sheet_nags,
    send_slack_failure,
)

logger = logging.getLogger(__name__)

SHEET_CHECK_INTERVAL_SEC = 30 * 60


def _setup_logging() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    Constants.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s at %(asctime)s] — %(message)s",
        handlers=[
            logging.FileHandler(Constants.LOG_DIR / f"daemon_{timestamp}.log"),
            logging.StreamHandler(),
        ],
    )


def poll_lco_and_aeon(state: DaemonState) -> None:
    proposals = get_active_proposals()
    requestgroups = get_all_requestgroups(proposals)

    snapshot = load_snapshot()
    changes = detect_changes(requestgroups, snapshot)
    save_snapshot(requestgroups)
    if changes["new"] or changes["changed"]:
        send_lco_changes(build_lco_digest(changes, None))

    aeon_reminder = get_aeon_reminder(requestgroups)
    lco_digest = build_lco_digest(changes, aeon_reminder)
    maybe_send_aeon_reminder(lco_digest, state)


def poll_soar_runs(state: DaemonState) -> None:
    relevant_runs = get_relevant_runs()
    digest = build_digest(relevant_runs)
    maybe_send_soar_run_updates(digest, state)


def run_forever() -> None:
    _setup_logging()
    state = DaemonState()
    last_sheet_check = 0.0

    logger.info("SOARcast daemon starting up.")

    while True:
        try:
            poll_lco_and_aeon(state)
        except Exception as e:
            logger.error(f"LCO/AEON poll failed: {e}")
            send_slack_failure(e, Constants.LCO_CHANGES_WEBHOOK)

        try:
            poll_soar_runs(state)
        except Exception as e:
            logger.error(f"SOAR run poll failed: {e}")
            send_slack_failure(e, Constants.SOARCAST_WEBHOOK)

        if time.time() - last_sheet_check >= SHEET_CHECK_INTERVAL_SEC:
            try:
                maybe_send_sheet_nags(state)
            except Exception as e:
                logger.error(f"Sheet staleness check failed: {e}")
            last_sheet_check = time.time()

        time.sleep(Constants.LCO_POLL_INTERVAL_SEC)


def main():
    try:
        run_forever()
    except KeyboardInterrupt:
        logger.info("SOARcast daemon stopped by user.")


if __name__ == "__main__":
    main()
