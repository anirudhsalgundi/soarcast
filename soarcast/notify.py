import os
import requests
import logging
from soarcast.nightplan import get_relevant_runs, build_digest


# constants
SOARCAST_WEBHOOK = os.environ.get("SOARCAST_WEBHOOK")
if not SOARCAST_WEBHOOK:
    logger.error("SOARCAST_WEBHOOK environment variable is not set.")
LCO_STATE_EMOJI = {
    "COMPLETED": ":white_check_mark:",
    "PENDING": ":hourglass_flowing_sand:",
    "CANCELED": ":x:",
    "WINDOW_EXPIRED": ":timer_clock:",
}
logger = logging.getLogger(__name__)


def format_lco_status(lco_matches: list) -> str:
    """
    Format the LCO matches for a target into a Slack-friendly string.
    """
    if not lco_matches:
        logger.warning("No LCO matches found for target. Returning NOT FOUND message.")
        return ":bangbang: NOT FOUND in ±3 day window" #slack message with warning emoji

    lines = []
    logger.info(f"Formatting {len(lco_matches)} LCO matches for target.")
    for lco in lco_matches:
        emoji = LCO_STATE_EMOJI.get(lco["state"], ":question:")
        lines.append(f"• {emoji} {lco['state']} ({lco['submitter']}, {lco['created']})")
    return "\n".join(lines)


def format_digest_slack(digest: list) -> list: #this function is mostly ai slop, but works
    """
    Format the digest into Slack Block Kit format for sending as a message.
     - digest: list of dicts as returned by build_digest()
     - Returns a list of Slack Block Kit blocks
     - If digest is empty, returns a single block indicating no nights found
     - For each run, includes a header with run info and a section for each target with LCO status formatted using format_lco_status()
    """
    blocks = []

    if not digest:
        logger.info("No relevant runs found. Returning message indicating no nights.")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":black_circle: No immediate SOAR nights found."}
        })
        return blocks

    if len(digest) >= 2:
        logger.warning(f"{len(digest)} relevant runs found. Adding warning about back-to-back nights.")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":warning: *2 back-to-back observing nights found!*"}
        })

    logger.info(f"Formatting digest with {len(digest)} runs for Slack message.")

    for entry in digest:
        logger.info(f"Processing run ID {entry['run']['id']} with dt={entry['dt']:.1f} days and {len(entry['targets'])} targets.")
        run = entry["run"]
        dt = entry["dt"]
        targets = entry["targets"]

        label = ":red_circle: *TONIGHT*" if dt <= 1.0 else ":telescope: *Upcoming SOAR night*"

        # run header
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{label} in *{dt:.1f} days*: on *{run['calendar_date']}* | "
                    f"<https://fritz.science/run/{run['id']}|Run #{run['id']}> | "
                    f"PI: {run['pi']}"
                )
            }
        })

        if not targets:
            logger.warning(f"No targets assigned for run ID {run['id']}. Adding message indicating no targets.")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "No targets assigned yet."}
            })
            continue

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*TARGETS ASSIGNED:*"}
        })

        for n, t in enumerate(targets):
            comment = t["comment"] or "N/A"

            lco_lines = "\n".join(
                f">     {LCO_STATE_EMOJI.get(lco['state'], ':question:')} "
                f"LCO #{lco['lco_id']} | {lco['state']} | "
                f"{lco['proposal']} | {lco['submitter']} | {lco['created']}"
                for lco in t["lco_matches"]
            ) if t["lco_matches"] else ">     :bangbang: LCO: NOT FOUND in ±3 day window"

            blockquote = (
                f"> *{n+1}. <https://fritz.science/source/{t['obj_id']}|{t['obj_id']}>*\n"
                f">     Requester: *{t['requester']}*  |  Priority: *{t['priority']}*  |  "
                f"Status: {t['status']}  |  Comment: _{comment}_\n"
                f"{lco_lines}"
            )

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": blockquote}
            })

    return blocks


def send_slack_digest(digest: list) -> None:
    """
    Send the digest as a Slack message via the SOARcast webhook.
     - digest: list of dicts as returned by build_digest()
     - Formats the digest into Slack Block Kit blocks and sends via webhook.
     - Prints a success or error message to the console.
    """
    blocks = format_digest_slack(digest)
    payload = {"blocks": blocks}
    response = requests.post(SOARCAST_WEBHOOK, json=payload)
    if response.status_code == 200:
        logger.info("Slack message sent successfully.")
    else:
        logger.error(f"Failed to send Slack message. Status code: {response.status_code}, Response: {response.text}")
        print(f"Error sending Slack message: {response.status_code} - {response.text}")


def send_slack_failure(error: Exception) -> None:
    payload = {"text": f":rotating_light: SOARcast failed to run: `{error}`"}
    requests.post(SOARCAST_WEBHOOK, json=payload)


def main():
    relevant_runs = get_relevant_runs()
    digest = build_digest(relevant_runs)
    try:
        send_slack_digest(digest)
    except Exception as e:
        logger.error(f"Error sending Slack message: {e}")
        send_slack_failure(e)


if __name__ == "__main__":
    main()