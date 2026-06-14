import os
import requests
import logging
from datetime import date
from soarcast.nightplan import get_relevant_runs, build_digest
from soarcast.lco_monitor import main as get_lco_digest
logger = logging.getLogger(__name__)

# constants
SOARCAST_WEBHOOK = os.environ.get("SOARCAST_WEBHOOK")
LCO_CHANGES_WEBHOOK = os.environ.get("LCO_CHANGES_WEBHOOK")
LCO_AEON_WEBHOOK = os.environ.get("LCO_AEON_WEBHOOK")
if not SOARCAST_WEBHOOK:
    logger.error("SOARCAST_WEBHOOK environment variable is not set.")
if not LCO_CHANGES_WEBHOOK:
    logger.error("LCO_CHANGES_WEBHOOK environment variable is not set.")
if not LCO_AEON_WEBHOOK:
    logger.error("LCO_AEON_WEBHOOK environment variable is not set.")
LCO_STATE_EMOJI = {
    "COMPLETED": ":white_check_mark:",
    "PENDING": ":hourglass_flowing_sand:",
    "CANCELED": ":x:",
    "WINDOW_EXPIRED": ":timer_clock:",
}



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


def format_lco_changes_slack(digest: dict) -> list:
    """
    Format the LCO changes into Slack Block Kit format.
    - digest: dict as returned by build_lco_digest()
    - Returns a list of Slack Block Kit blocks
    """
    blocks = []

    if not digest["has_changes"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":white_check_mark: No LCO portal changes detected."}
        })
        return blocks

    changes = digest["changes"]
    today = date.today().isoformat()
    n_new = len(changes["new"])
    n_changed = len(changes["changed"])

    # header
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f":bell: *LCO Portal Update* — {today}\n*{n_new} new request(s), {n_changed} state change(s)*"
        }
    })

    # new requestgroups
    if changes["new"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*NEW*"}
        })
        new_lines = "\n".join(
            f"> {LCO_STATE_EMOJI.get(rg['state'], ':question:')} "
            f"*<https://observe.lco.global/requestgroups/{rg['id']}|{rg['name']}>* — "
            f"{rg['proposal']} | {rg['submitter']} | {rg['created'][:10]}"
            for rg in changes["new"]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": new_lines}
        })

    # changed requestgroups
    if changes["changed"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*CHANGED*"}
        })
        changed_lines = "\n".join(
            f"> *<https://observe.lco.global/requestgroups/{c['requestgroup']['id']}|{c['requestgroup']['name']}>* — "
            f"{c['old_state']} → {LCO_STATE_EMOJI.get(c['new_state'], ':question:')} {c['new_state']} | "
            f"{c['requestgroup']['submitter']}"
            for c in changes["changed"]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": changed_lines}
        })

    return blocks


def format_lco_aeon_slack(digest: dict) -> list:
    """
    Format the AEON night reminder into Slack Block Kit format.
    - digest: dict as returned by build_lco_digest()
    - Returns a list of Slack Block Kit blocks
    """
    blocks = []

    if not digest["has_aeon"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":black_circle: No upcoming AEON nights within 1.5 JD."}
        })
        return blocks

    a = digest["aeon_reminder"]

    # header
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f":telescope: *AEON Night in {a['dt']:.1f} days — {a['date']}*\n"
                f":satellite: {a['obs_type']} | Reducer: *{a['reducer']}*"
            )
        }
    })

    if not a["pending_targets"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No pending targets found for this night."}
        })
        return blocks

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*{len(a['pending_targets'])} pending target(s):*"}
    })

    for rg in a["pending_targets"]:
        if not (rg.get("requests") and rg["requests"][0].get("windows")):
            continue
        text = (
            f"> *<https://observe.lco.global/requestgroups/{rg['id']}|{rg['name']}>*,   "
            f"Window: {rg['requests'][0]['windows'][0]['start'][:10]} → {rg['requests'][0]['windows'][0]['end'][:10]}\n"
            f"> submitted by _{rg['submitter']}_ · {rg['proposal']}"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text}
        })

    return blocks


def send_soarcast_digest(digest: list) -> None:
    """
    Send the digest as a Slack message via the SOARcast webhook.
     - digest: list of dicts as returned by build_digest()
     - Formats the digest into Slack Block Kit blocks and sends via webhook.
     - Prints a success or error message to the console.
    """
    blocks = format_digest_slack(digest)
    payload = {"blocks": blocks}
    # response = requests.post(SOARCAST_WEBHOOK, json=payload)
    # if response.status_code == 200:
    #     logger.info("Slack message sent successfully.")
    # else:
    #     logger.error(f"Failed to send Slack message. Status code: {response.status_code}, Response: {response.text}")
    #     print(f"Error sending Slack message: {response.status_code} - {response.text}")

    try:
        response = requests.post(SOARCAST_WEBHOOK, json=payload)
        if response.status_code == 200:
            logger.info("Slack message sent successfully.")
        else:
            logger.error(f"Failed to send Slack message. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending SOARcast Slack message: {e}")


def send_lco_changes(digest: dict) -> None:
    """
    Send the LCO changes digest to the changes Slack channel.
    - digest: dict as returned by build_lco_digest()
    """
    if not LCO_CHANGES_WEBHOOK:
        logger.error("LCO_CHANGES_WEBHOOK environment variable is not set.")
        return

    blocks = format_lco_changes_slack(digest)
    response = requests.post(LCO_CHANGES_WEBHOOK, json={"blocks": blocks})
    if response.status_code == 200:
        logger.info("LCO changes Slack message sent successfully.")
    else:
        logger.error(f"Failed to send LCO changes Slack message. Status: {response.status_code} | {response.text}")


def send_lco_aeon_reminder(digest: dict) -> None:
    """
    Send the AEON night reminder to the AEON Slack channel.
    - digest: dict as returned by build_lco_digest()
    """
    if not LCO_AEON_WEBHOOK:
        logger.error("LCO_AEON_WEBHOOK environment variable is not set.")
        return

    blocks = format_lco_aeon_slack(digest)
    response = requests.post(LCO_AEON_WEBHOOK, json={"blocks": blocks})
    if response.status_code == 200:
        logger.info("LCO AEON reminder Slack message sent successfully.")
    else:
        logger.error(f"Failed to send LCO AEON reminder Slack message. Status: {response.status_code} | {response.text}")


def send_slack_failure(error: Exception, webhook: str) -> None:
    """
    Send a failure alert to a Slack channel.
    - error: the exception that caused the failure
    - webhook: the Slack webhook URL to send the message to
    """
    payload = {"text": f":rotating_light: SOARcast failed to run: `{error}`"}
    response = requests.post(webhook, json=payload)
    if response.status_code == 200:
        logger.info("Failure alert sent to Slack successfully.")
    else:
        logger.error(f"Failed to send failure alert to Slack. Status: {response.status_code} | {response.text}")


def main():
    # SOARcast digest
    # relevant_runs = get_relevant_runs()
    # digest = build_digest(relevant_runs)
    # # try:
    # #     send_soarcast_digest(digest)
    # # except Exception as e:
    # #     logger.error(f"Error sending SOARcast Slack message: {e}")
    # #     send_slack_failure(e, SOARCAST_WEBHOOK)

    # # LCO changes + AEON reminder
    lco_digest = get_lco_digest()
    # print("has_changes:", lco_digest["has_changes"])
    # print("has_aeon:", lco_digest["has_aeon"])
    # print("aeon_reminder:", lco_digest["aeon_reminder"])
    try:
        send_lco_changes(lco_digest)
        send_lco_aeon_reminder(lco_digest)
    except Exception as e:
        logger.error(f"Error sending LCO Slack message: {e}")
        send_slack_failure(e, LCO_CHANGES_WEBHOOK)


if __name__ == "__main__":
    main()