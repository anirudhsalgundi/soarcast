#!/usr/bin/env python3
"""
soarcast.py

Sends a Slack digest of upcoming SOAR observing runs and their LCO status
to the SOARcast Slack workspace.

Usage:
    python soarcast.py
"""

import os
import requests
from fritz_lco_status import get_relevant_runs, build_digest


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SOARCAST_WEBHOOK = os.environ.get("SOARCAST_WEBHOOK")

LCO_STATE_EMOJI = {
    "COMPLETED": ":white_check_mark:",
    "PENDING": ":hourglass_flowing_sand:",
    "CANCELED": ":x:",
    "WINDOW_EXPIRED": ":timer_clock:",
}


def format_lco_status(lco_matches: list) -> str:
    if not lco_matches:
        return ":bangbang: NOT FOUND in ±3 day window"

    lines = []
    for lco in lco_matches:
        emoji = LCO_STATE_EMOJI.get(lco["state"], ":question:")
        lines.append(f"• {emoji} {lco['state']} ({lco['submitter']}, {lco['created']})")
    return "\n".join(lines)


def format_digest_slack(digest: list) -> list:
    blocks = []

    if not digest:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":black_circle: No immediate SOAR nights found."}
        })
        return blocks

    if len(digest) >= 2:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":warning: *2 back-to-back observing nights found!*"}
        })

    for entry in digest:
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

            # build LCO lines
            if not t["lco_matches"]:
                lco_lines = ">     :bangbang: LCO: NOT FOUND in ±3 day window"
            else:
                lco_lines = "\n".join(
                    f">     {LCO_STATE_EMOJI.get(lco['state'], ':question:')} "
                    f"LCO #{lco['lco_id']} | {lco['state']} | "
                    f"{lco['proposal']} | {lco['submitter']} | {lco['created']}"
                    for lco in t["lco_matches"]
                )

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


# ---------------------------------------------------------------------------
# Send Slack message
# ---------------------------------------------------------------------------

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
        print("✅ Slack message sent successfully")
    else:
        print(f"❌ Slack error: {response.status_code} — {response.text}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    relevant_runs = get_relevant_runs()
    digest = build_digest(relevant_runs)
    send_slack_digest(digest)


if __name__ == "__main__":
    main()