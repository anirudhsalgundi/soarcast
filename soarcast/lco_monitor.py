import json
import logging
import urllib.parse
from pytz import timezone
from datetime import date, datetime, timedelta

import requests
from astropy.time import Time

from soarcast.constants import Constants
from soarcast.sheets import load_aeon_nights

logger = logging.getLogger(__name__)

if not Constants.LCO_TOKEN:
    logger.error("LCO_TOKEN environment variable is not set.")


def lco_api(endpoint, params=None):
    headers = {"Authorization": f"Token {Constants.LCO_TOKEN}"}
    url = urllib.parse.urljoin(Constants.LCO_BASE, endpoint)
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def get_active_proposals() -> list:
    """
    Fetch all LCO proposals the user is a member of and return only the active ones.
    - Returns a list of proposal ID strings (e.g. ["SOAR2026A-021", "SOAR2026A-018"])
    - If no active proposals found, returns an empty list
    """
    logger.info("Fetching active proposals from LCO...")
    r = lco_api("/api/proposals/", params={"limit": 100})

    if "results" not in r:
        logger.error("Failed to fetch proposals from LCO or 'results' key missing in response.")
        return []

    active = [p["id"] for p in r["results"] if p.get("active")]

    if not active:
        logger.warning("No active proposals found.")
    else:
        logger.info(f"Found {len(active)} active proposals: {active}")

    return active


def get_all_requestgroups(proposals: list) -> list:
    """
    Fetch all requestgroups across a list of active proposal IDs.
    - proposals: list of proposal ID strings as returned by get_active_proposals()
    - Returns a flat list of requestgroup dicts
    - If no requestgroups found, returns an empty list
    - Makes one API call per proposal
    """
    logger.info(f"Fetching requestgroups for {len(proposals)} active proposals...")
    all_rgs = []

    for proposal_id in proposals:
        r = lco_api("/api/requestgroups/", params={"proposal": proposal_id, "limit": 100})

        if "results" not in r:
            logger.error(f"Failed to fetch requestgroups for proposal {proposal_id}.")
            continue

        logger.info(f"Fetched {len(r['results'])} requestgroups for proposal {proposal_id}.")
        all_rgs.extend(r["results"])

    logger.info(f"Fetched {len(all_rgs)} total requestgroups across all active proposals.")
    return all_rgs


def load_snapshot() -> dict:
    """
    Load the last known state of all requestgroups from the snapshot file.
    - Returns a dict mapping requestgroup ID to state (e.g. {2535060: "PENDING"})
    - If no snapshot file found, returns an empty dict (first run)
    """
    if not Constants.LCO_SNAPSHOT_PATH.exists():
        logger.info("No snapshot file found. This is likely the first run.")
        return {}

    try:
        with open(Constants.LCO_SNAPSHOT_PATH, "r") as f:
            snapshot = json.load(f)
        logger.info(f"Loaded snapshot with {len(snapshot)} requestgroups from {Constants.LCO_SNAPSHOT_PATH}")
        return snapshot
    except Exception as e:
        logger.error(f"Failed to load snapshot from {Constants.LCO_SNAPSHOT_PATH}: {e}")
        return {}


def save_snapshot(requestgroups: list) -> None:
    """
    Save the current state of all requestgroups to the snapshot file.
    - requestgroups: flat list of requestgroup dicts as returned by get_all_requestgroups()
    - Saves a dict mapping requestgroup ID to state
    - Creates the snapshot directory if it doesn't exist
    """
    Constants.LCO_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {str(rg["id"]): rg["state"] for rg in requestgroups}

    try:
        with open(Constants.LCO_SNAPSHOT_PATH, "w") as f:
            json.dump(snapshot, f, indent=2)
        logger.info(f"Saved snapshot with {len(snapshot)} requestgroups to {Constants.LCO_SNAPSHOT_PATH}")
    except Exception as e:
        logger.error(f"Failed to save snapshot to {Constants.LCO_SNAPSHOT_PATH}: {e}")


def detect_changes(requestgroups: list, snapshot: dict) -> dict:
    """
    Compare current requestgroups against the last snapshot to detect new or changed ones.
    - requestgroups: flat list of requestgroup dicts as returned by get_all_requestgroups()
    - snapshot: dict mapping requestgroup ID to state as returned by load_snapshot()
    - Returns a dict with two keys:
        - "new": list of requestgroup dicts that were not in the snapshot
        - "changed": list of dicts with keys "requestgroup", "old_state", "new_state"
    """
    logger.info(f"Detecting changes across {len(requestgroups)} requestgroups...")
    new = []
    changed = []

    for rg in requestgroups:
        rg_id = str(rg["id"])
        current_state = rg["state"]

        if rg_id not in snapshot:
            logger.info(f"New requestgroup found: {rg['name']} (ID: {rg_id}) with state {current_state}")
            new.append(rg)
        elif snapshot[rg_id] != current_state:
            logger.info(f"State change detected for {rg['name']} (ID: {rg_id}): {snapshot[rg_id]} → {current_state}")
            changed.append({
                "requestgroup": rg,
                "old_state": snapshot[rg_id],
                "new_state": current_state,
            })

    logger.info(f"Detected {len(new)} new and {len(changed)} changed requestgroups.")
    return {"new": new, "changed": changed}


from pytz import timezone
from datetime import datetime

def get_aeon_reminder(requestgroups: list, aeon_nights: list | None = None) -> dict | None:
    """
    Check if there is an AEON night within the next 1 day (or currently underway)
    and return pending targets for it.
    - requestgroups: flat list of requestgroup dicts as returned by get_all_requestgroups()
    - aeon_nights: list of dicts as returned by sheets.load_aeon_nights(); fetched if not given
    - Returns a dict with keys: date, obs_type, reducer, dt, started, pending_targets
    - If no AEON night found within the next 1 day, returns None
    """
    if aeon_nights is None:
        aeon_nights = load_aeon_nights()

    now = datetime.utcnow()
    chile_tz = timezone("America/Santiago")
    now_chile = now.astimezone(chile_tz)
    now_jd = Time(now).jd

    logger.info("Checking for AEON nights within the next 1.5 days...")

    for night in sorted(aeon_nights, key=lambda n: n["date"]):
        night_date = date.fromisoformat(night["date"])
        night_start_chile = chile_tz.localize(datetime.combine(night_date, datetime.min.time())).replace(hour=15)  # 3 PM Chile time
        night_end_chile = night_start_chile + timedelta(hours=16)  # Ends at 7 AM next day Chile time

        # Convert to UTC for Julian Date calculations
        night_start_utc = night_start_chile.astimezone(timezone("UTC"))
        night_end_utc = night_end_chile.astimezone(timezone("UTC"))

        night_start_jd = Time(night_start_utc).jd
        night_end_jd = Time(night_end_utc).jd
        dt = night_start_jd - now_jd

        if now_jd > night_end_jd:
            # night is fully over, ignore
            continue

        if dt > 1.0:
            logger.info(f"Next AEON night {night['date']} is {dt:.2f} JD away — too far.")
            break

        started = now_jd >= night_start_jd
        logger.info(f"AEON night in range: {night['date']} (dt={dt:.2f} JD, started={started})")

        pending = []
        for rg in requestgroups:
            if rg["state"] != "PENDING":
                continue
            try:
                window_start = rg["requests"][0]["windows"][0]["start"]
                window_end = rg["requests"][0]["windows"][0]["end"]
                if window_start <= night_end_utc.isoformat() and window_end >= night_start_utc.isoformat():
                    pending.append(rg)
            except (KeyError, IndexError):
                continue

        logger.info(f"Found {len(pending)} pending targets for AEON night {night['date']}")

        return {
            "date": night["date"],
            "obs_type": night["obs_type"],
            "reducer": night["reducer"],
            "dt": dt,
            "started": started,
            "pending_targets": pending,
        }

    logger.info("No AEON nights found within next 1.5 days.")
    return None


def build_lco_digest(changes: dict, aeon_reminder: dict | None) -> dict:
    """
    Combine detected changes and AEON reminder into a single digest structure.
    - changes: dict with keys "new" and "changed" as returned by detect_changes()
    - aeon_reminder: dict as returned by get_aeon_reminder(), or None if no upcoming night
    - Returns a dict with keys:
        - "changes": the changes dict
        - "aeon_reminder": the aeon_reminder dict or None
        - "has_changes": bool, True if there are any new or changed requestgroups
        - "has_aeon": bool, True if there is an AEON night within the next day
    """
    has_changes = bool(changes["new"] or changes["changed"])
    has_aeon = aeon_reminder is not None

    logger.info(f"Building LCO digest — changes: {has_changes}, aeon reminder: {has_aeon}")

    return {
        "changes": changes,
        "aeon_reminder": aeon_reminder,
        "has_changes": has_changes,
        "has_aeon": has_aeon,
    }


def main():
    proposals = get_active_proposals()
    requestgroups = get_all_requestgroups(proposals)
    snapshot = load_snapshot()
    changes = detect_changes(requestgroups, snapshot)
    save_snapshot(requestgroups)
    aeon_nights = load_aeon_nights()
    aeon_reminder = get_aeon_reminder(requestgroups, aeon_nights)
    return build_lco_digest(changes, aeon_reminder)


if __name__ == "__main__":
    main()
