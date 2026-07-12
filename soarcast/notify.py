import requests
import logging
from datetime import date, datetime, timezone
from soarcast.nightplan import get_relevant_runs, build_digest
from soarcast.lco_monitor import main as get_lco_digest
from soarcast.constants import Constants
from soarcast.state import DaemonState
from soarcast.sheets import get_calendar_last_date, get_roster_last_date
logger = logging.getLogger(__name__)

# constants
SOARCAST_WEBHOOK = Constants.SOARCAST_WEBHOOK
LCO_CHANGES_WEBHOOK = Constants.LCO_CHANGES_WEBHOOK
LCO_AEON_WEBHOOK = Constants.LCO_AEON_WEBHOOK
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


def _target_blocks(targets: list, start_index: int = 1) -> list:
    blocks = []
    for n, t in enumerate(targets, start=start_index):
        comment = t["comment"] or "N/A"

        lco_lines = "\n".join(
            f">     {LCO_STATE_EMOJI.get(lco['state'], ':question:')} "
            f"LCO #{lco['lco_id']} | {lco['state']} | "
            f"{lco['proposal']} | {lco['submitter']} | {lco['created']}"
            for lco in t["lco_matches"]
        ) if t["lco_matches"] else ">     :bangbang: LCO: NOT FOUND in ±3 day window"

        blockquote = (
            f"> *{n}. <https://fritz.science/source/{t['obj_id']}|{t['obj_id']}>*\n"
            f">     Requester: *{t['requester']}*  |  Priority: *{t['priority']}*  |  "
            f"Status: {t['status']}  |  Comment: _{comment}_\n"
            f"{lco_lines}"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": blockquote}
        })
    return blocks


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

        blocks.extend(_target_blocks(targets))

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


def _pending_target_blocks(pending_targets: list) -> list:
    blocks = []
    if not pending_targets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No pending targets found for this night."}
        })
        return blocks

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*{len(pending_targets)} pending target(s):*"}
    })
    for rg in pending_targets:
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


def format_lco_aeon_slack(digest: dict) -> list:
    """
    Format the "no AEON night upcoming" state into Slack Block Kit format.
    Countdown / night-begun messages are handled separately by
    maybe_send_aeon_reminder(), since those are stateful (rate-limited /
    sent-once) rather than a plain digest.
    """
    blocks = []

    if not digest["has_aeon"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":black_circle: No AEON nights found within next 1 day."}
        })
        return blocks

    a = digest["aeon_reminder"]
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f":telescope: *AEON Night — {a['date']}*\n"
                f":satellite: {a['obs_type']} | Reducer: *{a['reducer']}*"
            )
        }
    })
    blocks.extend(_pending_target_blocks(a["pending_targets"]))
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

    try:
        response = requests.post(SOARCAST_WEBHOOK, json=payload)
        if response.status_code == 200:
            logger.info("Slack message sent successfully.")
        else:
            logger.error(f"Failed to send Slack message. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending SOARcast Slack message: {e}")


def maybe_send_soar_run_updates(digest: list, state: DaemonState) -> None:
    """
    Stateful SOAR run announcer for the always-on daemon:
    - Per SOAR run (== a night on the AEON queue), announce once: "SOAR AEON
      night found for {date}".
    - After that, keep monitoring and post newly-assigned targets as "Target
      Assigned for {date}: ..." — never re-posting a target already sent for
      that run.
    - Back-to-back nights are handled naturally since state is tracked per
      run id, so each date gets its own announcement/target stream.
    """
    if not LCO_AEON_WEBHOOK:
        logger.error("LCO_AEON_WEBHOOK environment variable is not set.")
        return

    for entry in digest:
        run = entry["run"]
        run_id = run["id"]
        run_date = run["calendar_date"]
        targets = entry["targets"]

        run_state = state.get_soar_run_state(run_id)
        if not run_state.get("announced"):
            _post_aeon_text(f"SOAR AEON night found for {run_date}")
            state.mark_soar_run_announced(run_id)

        already_posted = state.get_posted_targets(run_id)
        new_targets = [t for t in targets if t["obj_id"] not in already_posted]
        if not new_targets:
            continue

        blocks = [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Target Assigned for {run_date}:*"}
        }]
        blocks.extend(_target_blocks(new_targets, start_index=len(already_posted) + 1))
        response = requests.post(LCO_AEON_WEBHOOK, json={"blocks": blocks})
        if response.status_code == 200:
            logger.info(f"Posted {len(new_targets)} new target(s) for run {run_id} ({run_date}).")
            state.add_posted_targets(run_id, [t["obj_id"] for t in new_targets])
        else:
            logger.error(f"Failed to post target updates for run {run_id}. Status: {response.status_code} | {response.text}")


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
    Used by the one-shot / cron entrypoints. For the always-on daemon, use
    maybe_send_aeon_reminder() instead, which is stateful and rate-limited.
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


def _post_aeon_text(text: str, pending_targets: list = None) -> None:
    if not LCO_AEON_WEBHOOK:
        logger.error("LCO_AEON_WEBHOOK environment variable is not set.")
        return
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if pending_targets is not None:
        blocks.extend(_pending_target_blocks(pending_targets))
    response = requests.post(LCO_AEON_WEBHOOK, json={"blocks": blocks})
    if response.status_code == 200:
        logger.info(f"AEON reminder sent: {text}")
    else:
        logger.error(f"Failed to send AEON reminder. Status: {response.status_code} | {response.text}")


def maybe_send_aeon_reminder(digest: dict, state: DaemonState) -> None:
    """
    Stateful AEON night reminder for the always-on daemon:
    - No AEON night within the next day: nothing is posted (avoids spamming
      Slack every poll cycle — this is only logged).
    - AEON night found but not started: post "X hours left for the next AEON
      night on {date}, reducer {name}" at most once every 3 hours.
    - AEON night has started: post "AEON night of {date} has begun, reducer
      {name}" exactly once.
    """
    if not digest["has_aeon"]:
        logger.info("No AEON nights found within next 1 day.")
        return

    a = digest["aeon_reminder"]
    night_date = a["date"]
    night_state = state.get_aeon_night_state(night_date)
    now = datetime.now(timezone.utc)

    if a["started"]:
        if not night_state.get("night_begun_announced"):
            text = f"AEON night of {night_date} has begun, reducer {a['reducer']}"
            _post_aeon_text(text, pending_targets=a["pending_targets"])
            state.set_aeon_night_state(night_date, night_begun_announced=True)
        return

    last = night_state.get("last_countdown_at")
    due = True
    if last:
        elapsed = (now - datetime.fromisoformat(last)).total_seconds()
        due = elapsed >= Constants.AEON_REMINDER_INTERVAL_SEC

    if due:
        hours_left = a["dt"] * 24
        text = f"{hours_left:.1f} hours left for the next AEON night on {night_date}, reducer {a['reducer']}"
        _post_aeon_text(text)
        state.set_aeon_night_state(night_date, last_countdown_at=now.isoformat())


def _maybe_nag(state: DaemonState, key: str, text: str, now: datetime) -> None:
    last = state.get_nag_last_sent(key)
    due = True
    if last:
        elapsed = (now - datetime.fromisoformat(last)).total_seconds()
        due = elapsed >= Constants.NAG_INTERVAL_SEC
    if due:
        _post_aeon_text(text)
        state.set_nag_last_sent(key, now.isoformat())


def maybe_send_sheet_nags(state: DaemonState) -> None:
    """
    Nag Slack, repeating every NAG_INTERVAL_SEC, when the AEON night calendar
    or scanning roster sheet is running out of scheduled dates and needs to
    be extended. Stops nagging as soon as the sheet's last date moves further
    into the future.
    """
    now = datetime.now(timezone.utc)
    today = date.today()

    calendar_last = get_calendar_last_date()
    if calendar_last is not None and (calendar_last - today).days <= Constants.SEMESTER_END_WARNING_DAYS:
        _maybe_nag(state, "aeon_calendar", "Reminder to update the AEON night calendar", now)

    roster_last = get_roster_last_date()
    if roster_last is not None and (roster_last - today).days <= Constants.SEMESTER_END_WARNING_DAYS:
        _maybe_nag(state, "scanning_roster", "Update the scanning roster", now)


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
    lco_digest = get_lco_digest()
    try:
        send_lco_changes(lco_digest)
        send_lco_aeon_reminder(lco_digest)
    except Exception as e:
        logger.error(f"Error sending LCO Slack message: {e}")
        send_slack_failure(e, LCO_CHANGES_WEBHOOK)


if __name__ == "__main__":
    main()