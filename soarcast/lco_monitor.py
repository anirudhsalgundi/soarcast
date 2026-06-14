import os
import json
import csv
import logging
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from astropy.time import Time

# constants
LCO_TOKEN = os.environ.get("LCO_TOKEN")
LCO_BASE = "https://observe.lco.global"
SNAPSHOT_PATH = Path.home() / ".soarcast" / "lco_state.json"
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

if not LCO_TOKEN:
    logger.error("LCO_TOKEN environment variable is not set.")

def lco_api(endpoint, params=None):
    headers = {"Authorization": f"Token {LCO_TOKEN}"}
    url = urllib.parse.urljoin(LCO_BASE, endpoint)
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
    if not SNAPSHOT_PATH.exists():
        logger.info("No snapshot file found. This is likely the first run.")
        return {}

    try:
        with open(SNAPSHOT_PATH, "r") as f:
            snapshot = json.load(f)
        logger.info(f"Loaded snapshot with {len(snapshot)} requestgroups from {SNAPSHOT_PATH}")
        return snapshot
    except Exception as e:
        logger.error(f"Failed to load snapshot from {SNAPSHOT_PATH}: {e}")
        return {}


def save_snapshot(requestgroups: list) -> None:
    """
    Save the current state of all requestgroups to the snapshot file.
    - requestgroups: flat list of requestgroup dicts as returned by get_all_requestgroups()
    - Saves a dict mapping requestgroup ID to state
    - Creates the snapshot directory if it doesn't exist
    """
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {str(rg["id"]): rg["state"] for rg in requestgroups}

    try:
        with open(SNAPSHOT_PATH, "w") as f:
            json.dump(snapshot, f, indent=2)
        logger.info(f"Saved snapshot with {len(snapshot)} requestgroups to {SNAPSHOT_PATH}")
    except Exception as e:
        logger.error(f"Failed to save snapshot to {SNAPSHOT_PATH}: {e}")


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


def load_aeon_nights(csv_path: str) -> list:
    """
    Load AEON observing nights from a CSV file.
    - csv_path: path to the CSV file with columns: date, obs_type, reducer
    - Returns a list of dicts with keys: date, obs_type, reducer
    - If file not found or malformed, returns an empty list
    """
    csv_path = Path(csv_path)

    if not csv_path.exists():
        logger.error(f"AEON nights CSV file not found at {csv_path}")
        return []

    nights = []
    try:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                nights.append({
                    "date": row["date"].strip(),
                    "obs_type": row["obs_type"].strip(),
                    "reducer": row["reducer"].strip(),
                })
        logger.info(f"Loaded {len(nights)} AEON nights from {csv_path}")
    except Exception as e:
        logger.error(f"Failed to load AEON nights from {csv_path}: {e}")
        return []

    return nights


def get_aeon_reminder(requestgroups: list, aeon_nights: list) -> dict | None:
    """
    Check if there is an upcoming AEON night within 1.5 JD and return pending targets for it.
    - requestgroups: flat list of requestgroup dicts as returned by get_all_requestgroups()
    - aeon_nights: list of dicts as returned by load_aeon_nights()
    - Returns a dict with keys: date, obs_type, reducer, dt, pending_targets
    - If no upcoming AEON night found within 1.5 JD, returns None
    """
    now_jd = Time.now().jd
    logger.info("Checking for upcoming AEON nights within 1.5 JD...")

    for night in sorted(aeon_nights, key=lambda n: n["date"]):
        night_date = date.fromisoformat(night["date"])
        if night_date < date.today():
            continue

        night_jd = Time(f"{night['date']}T19:00:00", format="isot", scale="utc").jd
        dt = night_jd - now_jd

        if dt < -0.75:
            logger.info(f"Skipping past AEON night {night['date']} (JD {night_jd:.2f}, dt {dt:.2f})")
            continue

        if dt > 1.5:
            logger.info(f"Next AEON night {night['date']} is {dt:.2f} JD away — too far.")
            break

        logger.info(f"Upcoming AEON night found: {night['date']} in {dt:.2f} JD")

        # filter pending requestgroups whose window overlaps with the AEON night
        pending = []
        for rg in requestgroups:
            if rg["state"] != "PENDING":
                continue
            try:
                window_start = rg["requests"][0]["windows"][0]["start"]
                window_end = rg["requests"][0]["windows"][0]["end"]
                night_start = f"{night['date']}T19:00:00Z"
                night_end = f"{night['date']}T23:59:59Z"
                if window_start <= night_end and window_end >= night_start:
                    pending.append(rg)
            except (KeyError, IndexError):
                continue

        logger.info(f"Found {len(pending)} pending targets for AEON night {night['date']}")

        return {
            "date": night["date"],
            "obs_type": night["obs_type"],
            "reducer": night["reducer"],
            "dt": dt,
            "pending_targets": pending,
        }

    logger.info("No upcoming AEON nights found within 1.5 JD.")
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
        - "has_aeon": bool, True if there is an upcoming AEON night
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
    aeon_nights = load_aeon_nights("/Users/ani/work/projects/soar/soarcast/aeon_nights.csv")
    aeon_reminder = get_aeon_reminder(requestgroups, aeon_nights)
    return build_lco_digest(changes, aeon_reminder)


# def main():
#     return None
    # # test run
    # proposals = get_active_proposals()
    # requestgroups = get_all_requestgroups(proposals)
    # snapshot = load_snapshot()
    # changes = detect_changes(requestgroups, snapshot)
    # save_snapshot(requestgroups)

    # print(f"\n--- CHANGES ---")
    # print(f"New: {len(changes['new'])}")
    # print(f"Changed: {len(changes['changed'])}")
    # for c in changes["changed"]:
    #     print(f"  {c['requestgroup']['name']} | {c['old_state']} → {c['new_state']}")

    # aeon_nights = load_aeon_nights("/Users/ani/work/projects/soar/soarcast/aeon_nights.csv")
    # aeon_reminder = get_aeon_reminder(requestgroups, aeon_nights)
    # digest = build_lco_digest(changes, aeon_reminder)
    # # digest = build_lco_digest(changes, None)  # no aeon reminder for now
    # print(f"\n--- DIGEST ---")
    # print(json.dumps({k: v for k, v in digest.items() if k != "changes"}, indent=2))
    # print(f"\n--- CHANGES DETAIL ---")
    # if not changes["new"] and not changes["changed"]:
    #     print("No changes detected.")
    # else:
    #     if changes["new"]:
    #         print(f"\nNEW ({len(changes['new'])}):")
    #         for rg in changes["new"]:
    #             print(f"  {rg['name']} | {rg['proposal']} | {rg['state']} | submitted by {rg['submitter']} | created {rg['created'][:10]}")
        
    #     if changes["changed"]:
    #         print(f"\nCHANGED ({len(changes['changed'])}):")
    #         for c in changes["changed"]:
    #             rg = c["requestgroup"]
    #             print(f"  {rg['name']} | {rg['proposal']} | {c['old_state']} → {c['new_state']} | submitted by {rg['submitter']}")

    # print(f"\n--- AEON REMINDER ---")
    # if not digest["has_aeon"]:
    #     print("No upcoming AEON nights within 1.5 JD.")
    # else:
    #     a = digest["aeon_reminder"]
    #     print(f"AEON Night: {a['date']} in {a['dt']:.2f} JD | {a['obs_type']} | Reducer: {a['reducer']}")
    #     print(f"Pending targets ({len(a['pending_targets'])}):")
    #     for rg in a["pending_targets"]:
    #         print(f"  {rg['name']} | {rg['proposal']} | submitted by {rg['submitter']} | window: {rg['requests'][0]['windows'][0]['start'][:10]} → {rg['requests'][0]['windows'][0]['end'][:10]}")

if __name__ == "__main__":
    main()