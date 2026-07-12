import csv
import io
import logging
from datetime import date, datetime

import requests

from soarcast.constants import Constants

logger = logging.getLogger(__name__)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _fetch_csv(url: str) -> list[dict]:
    """Fetch a published Google Sheet as CSV and return a list of row dicts."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch sheet at {url}: {e}")
        return []

    reader = csv.DictReader(io.StringIO(resp.text))
    return [row for row in reader]


def _resolve_year(month: int, day: int, today: date) -> int:
    """
    The AEON calendar sheet only has Month/Day, no year. Assume the row belongs
    to the current year unless that would put it more than ~6 months in the
    past, in which case it must be next year (handles semesters that wrap
    across a Jan 1 boundary).
    """
    year = today.year
    candidate = date(year, month, day)
    if (today - candidate).days > 180:
        candidate = date(year + 1, month, day)
    return candidate.year


def load_aeon_nights() -> list[dict]:
    """
    Load AEON observing nights from the AEON night calendar Google Sheet.
    - Returns a list of dicts with keys: date (YYYY-MM-DD str), obs_type, reducer
    - Only rows whose Comments field mentions "AEON" are included.
    - If the sheet can't be fetched or parsed, returns an empty list.
    """
    rows = _fetch_csv(Constants.AEON_CALENDAR_CSV_URL)
    if not rows:
        logger.error("AEON calendar sheet returned no rows.")
        return []

    today = date.today()
    nights = []
    for row in rows:
        month_str = (row.get("Month") or "").strip().lower()[:3]
        day_str = (row.get("Day") or "").strip()
        comments = (row.get("Comments") or "").strip()

        if month_str not in MONTHS or not day_str.isdigit():
            continue
        if "aeon" not in comments.lower():
            continue

        try:
            month = MONTHS[month_str]
            day = int(day_str)
            year = _resolve_year(month, day, today)
            night_date = date(year, month, day)
        except ValueError:
            continue

        nights.append({
            "date": night_date.isoformat(),
            "obs_type": (row.get("Instruments") or "").strip(),
            "reducer": (row.get("Support_scientist") or "").strip(),
        })

    logger.info(f"Loaded {len(nights)} AEON nights from calendar sheet.")
    return sorted(nights, key=lambda n: n["date"])


def get_calendar_last_date() -> date | None:
    """
    Returns the last scheduled date anywhere in the AEON calendar sheet
    (not just AEON nights), used to detect that the semester schedule is
    running out and needs to be extended/updated.
    """
    rows = _fetch_csv(Constants.AEON_CALENDAR_CSV_URL)
    if not rows:
        return None

    today = date.today()
    dates = []
    for row in rows:
        month_str = (row.get("Month") or "").strip().lower()[:3]
        day_str = (row.get("Day") or "").strip()
        if month_str not in MONTHS or not day_str.isdigit():
            continue
        try:
            month = MONTHS[month_str]
            day = int(day_str)
            year = _resolve_year(month, day, today)
            dates.append(date(year, month, day))
        except ValueError:
            continue

    return max(dates) if dates else None


def load_scanning_roster() -> list[dict]:
    """
    Load the scanning roster from the scanning roster Google Sheet.
    - Returns a list of dicts with keys: start (YYYY-MM-DD), end (YYYY-MM-DD), reducer
    - If the sheet can't be fetched or parsed, returns an empty list.
    """
    rows = _fetch_csv(Constants.SCANNING_ROSTER_CSV_URL)
    if not rows:
        logger.error("Scanning roster sheet returned no rows.")
        return []

    roster = []
    for row in rows:
        start = (row.get("Date start") or "").strip()
        end = (row.get("Date end") or "").strip()
        reducer = (row.get("Reduction") or "").strip()
        try:
            datetime.fromisoformat(start)
            datetime.fromisoformat(end)
        except ValueError:
            continue
        roster.append({"start": start, "end": end, "reducer": reducer})

    logger.info(f"Loaded {len(roster)} scanning roster entries.")
    return sorted(roster, key=lambda r: r["start"])


def get_roster_last_date() -> date | None:
    """Returns the last "Date end" found in the scanning roster sheet."""
    roster = load_scanning_roster()
    if not roster:
        return None
    return max(date.fromisoformat(r["end"]) for r in roster)
