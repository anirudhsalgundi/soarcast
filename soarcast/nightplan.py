import logging
import urllib.parse
from datetime import date, datetime, timedelta

import requests
from astropy.time import Time

from soarcast.constants import Constants

#CONSTANTS
FRITZ_TOKEN = Constants.FRITZ_TOKEN
LCO_TOKEN = Constants.LCO_TOKEN
FRITZ_BASE = Constants.FRITZ_BASE
LCO_BASE = Constants.LCO_BASE
SOAR_INSTRUMENT_IDS = Constants.SOAR_INSTRUMENT_IDS
logger = logging.getLogger(__name__) # simpler logging setup


# if the env variable not set in bashrc, rasie errors.
if not FRITZ_TOKEN:
    logger.error("FRITZ_FOLLOWUP_REQ_TOKEN environment variable is not set.")
if not LCO_TOKEN:
    logger.error("LCO_TOKEN environment variable is not set.")


def fritz_api(endpoint: str, params:str=None)->dict:
    """
    Helper function to query Fritz API with authentication and error handling.
     - endpoint: API endpoint path (e.g. "/api/instrument")
     - params: dict of query parameters to include in the request
    Returns the JSON response as a dict. Raises an exception if the request fails.
    """

    headers = {"Authorization": f"token {FRITZ_TOKEN}"}
    url = urllib.parse.urljoin(FRITZ_BASE, endpoint)
    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        logger.info(f"Successfully fetched data from Fritz endpoint: {endpoint}")
    else:
        logger.error(f"Failed to fetch data from Fritz endpoint: {endpoint} | Status code: {response.status_code} | Response: {response.text}")

    return response.json()


def lco_api(endpoint: str, params: str=None) -> dict:
    """
    Helper function to query LCO API with authentication and error handling.
        - endpoint: API endpoint path (e.g. "/api/requestgroups/")
        - params: dict of query parameters to include in the request
    Returns the JSON response as a dict. Raises an exception if the request fails.
    """

    headers = {"Authorization": f"Token {LCO_TOKEN}"}
    url = urllib.parse.urljoin(LCO_BASE, endpoint)
    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        logger.info(f"Successfully fetched data from LCO endpoint: {endpoint}")
    else:
        logger.error(f"Failed to fetch data from LCO endpoint: {endpoint} | Status code: {response.status_code} | Response: {response.text}")


    return response.json()


def get_relevant_runs():
    """
    Step 1: Query Fritz for all observing runs, filter to SOAR, and find those starting within the next 2 days.
     - Returns a list of tuples: (run_dict, dt_in_jd)
     - run_dict contains all info about the run from Fritz, including calendar_date, pi, instrument_id, etc.
     - dt_in_jd is the time until the run starts in Julian Days (e.g. 0.5 means 12 hours until start)
     - Only runs with instrument_id in SOAR_INSTRUMENT_IDS are considered
     - Only runs with calendar_date >= today are considered
     - The list is sorted by calendar_date ascending (soonest first)
     - If no runs are found, returns an empty list
     - This function makes one API call to Fritz to fetch all observing runs and does all filtering locally.
    """

    logger.info("Fetching all observing runs from Fritz...")
    r_all = fritz_api("/api/observing_run")

    if "data" not in r_all:
        logger.error("Failed to fetch observing runs from Fritz or 'data' key missing in response.")
        return []
    
    all_runs = r_all["data"]
    logger.info(f"Fetched {len(all_runs)} total observing runs from Fritz.")

    today = date.today().isoformat()
    now_jd = Time.now().jd

    # get all the runs of SOAR instrument.
    logger.info(f"Filtering runs for SOAR instruments with IDs: {SOAR_INSTRUMENT_IDS}")
    soar_runs = [
        run for run in all_runs
        if run.get("instrument_id") in SOAR_INSTRUMENT_IDS
    ]

    if not soar_runs:
        logger.warning("No observing runs found for SOAR instruments.")
        return []

    # get only the runs that are upcoming (calendar_date >= today) and sort by date
    logger.info(f"Filtering for upcoming runs starting from ({today})")
    upcoming = sorted(
        [run for run in soar_runs if run["calendar_date"] >= today],
        key=lambda r: r["calendar_date"]
    )
    if not upcoming:
        logger.warning("No upcoming SOAR runs found starting from today.")
        return []

    # the most relevent run is the one coming soon, so just take those.
    logger.info("Looking for runs starting within the next 2 days")
    relevant = []
    for run in upcoming:
        run_start_jd = Time(f"{run['calendar_date']}T19:00:00", format="isot", scale="utc").jd
        dt = run_start_jd - now_jd
        if dt <= 2.0:
            relevant.append((run, dt))

    if not relevant:
        logger.warning("No relevant SOAR runs found starting within the next 2 days.")
    else:
        logger.info(f"Found {len(relevant)} relevant SOAR runs starting within the next 2 days.")

    return relevant


def get_run_assignments(run: dict) -> list:
    """
    Step 2: For a given observing run, fetch its assignments from Fritz.
     - run: dict containing info about the observing run (must include "id" key)
     - Returns a list of assignment dicts, each containing info about a target assigned to that run (e.g. obj_id, requester, priority, status, comment, rise/set times, etc.)
     - If no assignments are found, returns an empty list
     - This function makes one API call to Fritz to fetch the observing run details, which includes the assignments.
    """

    logger.info(f"Fetching assignments for observing run ID: {run['id']} from Fritz")
    r = fritz_api(f"/api/observing_run/{run['id']}")

    if "data" not in r or "assignments" not in r["data"]:
        logger.error(f"Failed to fetch assignments for run ID: {run['id']} or 'assignments' key missing in response.")
        return []
    else:
        logger.info(f"Found {len(r['data']['assignments'])} assignments for run ID: {run['id']}")

    return r["data"].get("assignments", [])


def get_lco_status(obj_id: str, run_date: str) -> list:
    """
    Step 3: For a given target (obj_id) and run date, query LCO observe portal for any requestgroups matching that target created within ±3 days of the run date.
        - obj_id: string identifier of the target (e.g. "ZTF20aaelulu")
        - run_date: string in "YYYY-MM-DD" format representing the calendar date of the observing run
        - Returns a list of dicts, each containing info about a matching LCO requestgroup (e.g. lco_id, state, proposal, submitter, created date)
        - If no matches are found, returns an empty list
        - This function makes one API call to LCO to fetch requestgroups matching the target name and created within the specified date window.
    """
    run_date = date.fromisoformat(run_date) if isinstance(run_date, str) else run_date
    date_start = (run_date - timedelta(days=3)).isoformat()
    date_end = (run_date + timedelta(days=3)).isoformat()

    logger.info(f"Querying LCO for requestgroups matching target '{obj_id}' created between {date_start} and {date_end}")
    r = lco_api("/api/requestgroups/", params={
        "target_name": obj_id,
        "created_after": f"{date_start}T00:00:00Z",
        "created_before": f"{date_end}T00:00:00Z",
        "limit": 100,
    })

    if "results" not in r:
        logger.error(f"Failed to fetch requestgroups from LCO or 'results' key missing in response.")
        return []
    else:
        logger.info(f"Fetched {len(r['results'])} requestgroups from LCO matching target '{obj_id}' in the specified date window.")

        matches = [
            {
                "lco_id": rg["id"],
                "target_name": rg["requests"][0]["configurations"][0]["target"]["name"],
                "state": rg["state"],
                "proposal": rg["proposal"],
                "submitter": rg["submitter"],
                "created": rg["created"][:10],
            }
            for rg in r["results"]
            if rg["requests"][0]["configurations"][0]["target"]["name"] == obj_id
        ]

    return matches


def build_digest(relevant_runs: list) -> list:
    """
    Step 4: For each relevant observing run, fetch its assignments and LCO status for
    each assigned target, and combine into a digest structure.
     - relevant_runs: list of tuples (run_dict, dt_in_jd) as returned by get_relevant_runs()
     - Returns a list of dicts
     - If no relevant runs are provided, returns an empty list
     - This function makes multiple API calls: one for each run to get assignments, and one for each target to get LCO status.
    """
    digest = []

    logger.info(f"Building digest for {len(relevant_runs)} relevant runs")
    for run, dt in relevant_runs:
        assignments = get_run_assignments(run)

        targets = []
        logger.info(f"Processing {len(assignments)} assignments for run ID: {run['id']}")
        for a in assignments:

            obj_id = a["obj_id"]
            lco_matches = get_lco_status(obj_id, run["calendar_date"])

            targets.append({
                "obj_id": obj_id,
                "requester": a["requester"]["username"],
                "priority": a["priority"],
                "status": a["status"],
                "comment": a.get("comment"),
                "rise_time_utc": a.get("rise_time_utc"),
                "set_time_utc": a.get("set_time_utc"),
                "lco_matches": lco_matches,
            })

        digest.append({
            "run": run,
            "dt": dt,
            "targets": targets,
        })

    return digest


def main():
    
    # get the relevant runs starting within the next 2 days, then build and print the digest.
    relevant_runs = get_relevant_runs()
    if not relevant_runs:
        logger.info("No relevant SOAR runs starting within the next 2 days. Exiting.")
        return

    # for each relevant run, get the assignments and LCO status for each target, and build a digest structure.
    digest = build_digest(relevant_runs)

    if not digest:
        logger.info("No digest information to display. Exiting.")
        return

    return None

if __name__ == "__main__":
    main()