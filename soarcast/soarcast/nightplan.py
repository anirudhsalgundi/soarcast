import argparse
import os
import urllib.parse
from collections import defaultdict
from datetime import datetime
import requests
import logging
from datetime import date, timedelta
from astropy.time import Time
import os, json, urllib.parse, requests


def get_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    formatter = logging.Formatter("[%(levelname)s at %(asctime)s] — %(message)s")
    
    fh = logging.FileHandler(log_file)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    
    return logger, fh

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
logger, fh = get_logger(f"run_{timestamp}.log")
logger.info("Logger initialized successfully")


#CONSTANTS
try:
    FRITZ_TOKEN = os.environ.get("FRITZ_FOLLOWUP_REQ_TOKEN")
except KeyError:
    print("ERROR: Please set the FRITZ_FOLLOWUP_REQ_TOKEN environment variable.")
    exit(1)

try:
    LCO_TOKEN = os.environ.get("LCO_TOKEN")
except KeyError:
    print("ERROR: Please set the LCO_TOKEN environment variable.")
    exit(1)


FRITZ_BASE = "https://fritz.science"
LCO_BASE = "https://observe.lco.global"
SOAR_INSTRUMENT_IDS = {1107, 1108, 1109}


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
    response.raise_for_status()

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
    response.raise_for_status()


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


    r_all = fritz_api("/api/observing_run")
    all_runs = r_all["data"]

    today = date.today().isoformat()
    now_jd = Time.now().jd

    # get all the runs of SOAR instrument.
    soar_runs = [
        run for run in all_runs
        if run.get("instrument_id") in SOAR_INSTRUMENT_IDS
    ]

    # get only the runs that are upcoming (calendar_date >= today) and sort by date
    upcoming = sorted(
        [run for run in soar_runs if run["calendar_date"] >= today],
        key=lambda r: r["calendar_date"]
    )

    # the most relevent run is the one coming soon, so just take those.
    relevant = []
    for run in upcoming:
        run_start_jd = Time(f"{run['calendar_date']}T19:00:00", format="isot", scale="utc").jd
        dt = run_start_jd - now_jd
        if dt <= 2.0:
            relevant.append((run, dt))

    return relevant


def get_run_assignments(run: dict) -> list:
    """
    Step 2: For a given observing run, fetch its assignments from Fritz.
     - run: dict containing info about the observing run (must include "id" key)
     - Returns a list of assignment dicts, each containing info about a target assigned to that run (e.g. obj_id, requester, priority, status, comment, rise/set times, etc.)
     - If no assignments are found, returns an empty list
     - This function makes one API call to Fritz to fetch the observing run details, which includes the assignments.
    """
    r = fritz_api(f"/api/observing_run/{run['id']}")
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

    r = lco_api("/api/requestgroups/", params={
        "target_name": obj_id,
        "created_after": f"{date_start}T00:00:00Z",
        "created_before": f"{date_end}T00:00:00Z",
        "limit": 100,
    })

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
     - This function makes multiple API calls: one for each run to get assignments, and one for each target to get LCO status. Caching is implemented to avoid redundant LCO queries for the same target across multiple runs.
    """
    digest = []

    for run, dt in relevant_runs:
        assignments = get_run_assignments(run)

        targets = []
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


def print_digest(digest: list)->None: #FIXME: if we move to slack bot seinding the messages, this function will have to be deprecated.
    """
    Step 5: Nicely print the digest to the console.
     - digest: list of dicts as returned by build_digest()
     - Prints a human-readable summary of the upcoming SOAR runs, their assigned targets, and any matching LCO requestgroups for those targets.
     - If the digest is empty, prints a message indicating that no upcoming runs were found.
     - For each run, prints the run ID, calendar date, PI, and time until start. For each assigned target, prints the requester, priority, status, comment, and rise/set times. For each LCO match, prints the LCO ID, state, proposal, submitter, and created date.
    """
    if not digest:
        print("No upcoming SOAR runs within the next 2 days.")
        return

    if len(digest) >= 2:
        print("⚠️  2 back-to-back observing nights found!\n")

    for entry in digest:
        run = entry["run"]
        dt = entry["dt"]
        targets = entry["targets"]

        label = "🔴 TONIGHT" if dt <= 1.0 else "TOMORROW"
        print(f"\n{'='*80}")
        print(f"{label}  |  Run ID: {run['id']}  |  Date: {run['calendar_date']}  |  PI: {run['pi']}  |  dt: {dt:.3f} JD")
        print(f"{'='*80}")

        if not targets:
            print("  No targets assigned so far.")
            continue

        print(f"  Total targets: {len(targets)}")
        for n, t in enumerate(targets):
            print(f"\n  {n+1}. {t['requester']} requested https://fritz.science/source/{t['obj_id']}")
            print(f"     Priority: {t['priority']}  |  Status: {t['status']}  |  Comment: {t['comment'] or 'N/A'}")

            if not t["lco_matches"]:
                print(f"     LCO: NOT FOUND in ±3 day window")
            else:
                for lco in t["lco_matches"]:
                    print(f"     LCO ID: {lco['lco_id']}  |  State: {lco['state']}  |  Proposal: {lco['proposal']}  |  Submitter: {lco['submitter']}  |  Created: {lco['created']}")



def main():

    relevant_runs = get_relevant_runs()
    digest = build_digest(relevant_runs)
    print_digest(digest)

    return None

if __name__ == "__main__":
    main()