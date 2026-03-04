"""
NSU Timetable Scraper
=====================
Scrapes all group timetables from table.nsu.ru and produces a normalized
JSON file with groups, teachers, rooms, and a bell schedule.

Output structure (nsu_data.json):
{
  "bell_schedule": { "1": {...}, ... "7": {...} },
  "teachers":      { "<uuid>": "<name>", ... },
  "rooms":         { "<id>":   "<display name>", ... },
  "groups":        { "<group_id>": { "faculty_id", "faculty_name",
                                      "degree", "year", "specialty",
                                      "schedule": [...] }, ... }
}
"""

import asyncio
import json
import logging
import re
from urllib.parse import unquote, parse_qs

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiolimiter import AsyncLimiter
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = "https://table.nsu.ru"
RATE_LIMIT = AsyncLimiter(5, 1)        # max 3 requests / second
OUTPUT_FILE = "nsu_data.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Maps the start-time text shown in column 0 of the schedule table to a
# 1-based time-slot number.
TIME_TO_SLOT: dict[str, int] = {
    "9:00":  1,
    "10:50": 2,
    "12:40": 3,
    "14:30": 4,
    "16:20": 5,
    "18:10": 6,
    "20:00": 7,
}

BELL_SCHEDULE: dict[str, dict[str, str]] = {
    "1": {"half1": "9:00-9:45",   "half2": "9:50-10:35"},
    "2": {"half1": "10:50-11:35", "half2": "11:40-12:25"},
    "3": {"half1": "12:40-13:25", "half2": "13:30-14:15"},
    "4": {"half1": "14:30-15:15", "half2": "15:20-16:05"},
    "5": {"half1": "16:20-17:05", "half2": "17:10-17:55"},
    "6": {"half1": "18:10-18:55", "half2": "19:00-19:45"},
    "7": {"half1": "20:00-20:45", "half2": "20:50-21:35"},
}

DAY_NAMES: list[str] = [
    "Понедельник", "Вторник", "Среда",
    "Четверг", "Пятница", "Суббота",
]

# Russian day header → 1-based numeric day index
DAY_INDEX: dict[str, int] = {name: i for i, name in enumerate(DAY_NAMES, start=1)}

# Normalise Russian class-type strings into four English categories.
# Keys are lowered substrings matched against the title attribute of span.type.
TYPE_MAP: dict[str, str] = {
    "лекция":                 "lecture",
    "практическое занятие":  "seminar",
    "семинар":               "seminar",
    "лабораторная работа":   "labs",
    "лабораторная":          "labs",
    "факультатив":           "elective",
}

# ---------------------------------------------------------------------------
# Normalised data store  (populated during scraping)
# ---------------------------------------------------------------------------
data_store: dict = {
    "bell_schedule": BELL_SCHEDULE,
    "teachers": {},   # uuid  -> name
    "rooms": {},      # id    -> display name
    "groups": {},     # gid   -> { meta + schedule }
}

# Metadata collected from faculty pages:
#   group_id -> { faculty_id, faculty_name, degree, year, specialty }
_group_meta: dict[str, dict] = {}


# ===================================================================
# HTTP helpers
# ===================================================================
async def fetch(session: ClientSession, url: str) -> str:
    """GET *url* respecting the global rate-limiter.  Returns HTML text."""
    async with RATE_LIMIT:
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.text()
        except Exception as exc:
            log.error("Error fetching %s: %s", url, exc)
            return ""


# ===================================================================
# Step 1 – discover faculties
# ===================================================================
async def get_faculty_ids(session: ClientSession) -> list[tuple[str, str]]:
    """Return list of (faculty_slug, faculty_display_name)."""
    html = await fetch(session, f"{BASE_URL}/faculties")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if href.startswith("/faculty/"):
            slug = href.split("/")[-1]
            name = a.get_text(strip=True)
            results.append((slug, name))
    return results


# ===================================================================
# Step 2 – scrape faculty page  →  group metadata
# ===================================================================
async def scrape_faculty(
    session: ClientSession, faculty_slug: str, faculty_name: str
) -> set[str]:
    """Parse one faculty page, populate *_group_meta*, return group IDs."""
    html = await fetch(session, f"{BASE_URL}/faculty/{faculty_slug}")
    if not html:
        return set()

    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all("div", class_="schedule-block")

    group_ids: set[str] = set()

    # --- Block 0: grouped by degree level (Бакалавриат / Магистратура) ------
    if len(blocks) >= 1:
        block0 = blocks[0]
        for table in block0.find_all("table", class_="degree_groups"):
            current_degree: str | None = None
            current_year: int | None = None
            for tr in table.find_all("tr"):
                h4 = tr.find("h4")
                if h4:
                    a_h4 = h4.find("a", href=True)
                    if a_h4:
                        # Year from text: "1 курс" → 1
                        year_match = re.search(r"(\d+)", a_h4.get_text())
                        current_year = int(year_match.group(1)) if year_match else None
                        # Degree from query string: ?degree=Бакалавриат
                        href = a_h4["href"]
                        if "?" in href:
                            qs = parse_qs(href.split("?", 1)[1])
                            if "degree" in qs:
                                current_degree = unquote(qs["degree"][0])
                for a_grp in tr.find_all("a", class_="group", href=True):
                    gid = a_grp.get_text(strip=True)
                    group_ids.add(gid)
                    _group_meta.setdefault(gid, {}).update({
                        "faculty_id": faculty_slug,
                        "faculty_name": faculty_name,
                        "degree": current_degree,
                        "year": current_year,
                    })

    # --- Block 1: grouped by specialty / programme -------------------------
    if len(blocks) >= 2:
        block1 = blocks[1]
        for col in block1.find_all("div", class_="col-xs-6"):
            # First child <div> holds the specialty name
            specialty_div = col.find("div", recursive=False)
            specialty_name = specialty_div.get_text(strip=True) if specialty_div else None
            for a_grp in col.find_all("a", class_="group", href=True):
                gid = a_grp.get_text(strip=True)
                group_ids.add(gid)
                _group_meta.setdefault(gid, {}).update({
                    "specialty": specialty_name,
                })
                # If not already captured from block 0, fill basics
                _group_meta[gid].setdefault("faculty_id", faculty_slug)
                _group_meta[gid].setdefault("faculty_name", faculty_name)

    return group_ids


# ===================================================================
# Step 3 – parse one group's timetable HTML
# ===================================================================
def _extract_room(cell_div: Tag) -> tuple[str | None, str | None]:
    """Return (room_id, room_display_name) from a div.cell element."""
    room_div = cell_div.find("div", class_="room")
    if room_div is None:
        return None, None

    room_a = room_div.find("a")
    display = room_div.get_text(strip=True)
    if not display:
        return None, None

    if room_a and room_a.get("onclick"):
        # onclick="return room_view('nk',5,301,798)"
        m = re.search(r"room_view\((.+?)\)", room_a["onclick"])
        if m:
            raw_args = m.group(1).replace("'", "").replace('"', "")
            room_id = "_".join(raw_args.split(","))
        else:
            room_id = display
    else:
        # No link — use display text as ID
        room_id = display

    return room_id, display


def _extract_teacher(cell_div: Tag) -> tuple[str | None, str | None]:
    """Return (teacher_uuid, display_name) from a div.cell element."""
    a_tutor = cell_div.find("a", class_="tutor", href=True)
    if a_tutor is None:
        return None, None
    uuid = a_tutor["href"].split("/")[-1]
    name = a_tutor.get_text(strip=True)
    return uuid, name


def _extract_type(cell_div: Tag) -> str:
    """Return normalised English class type: lecture / seminar / labs / elective / other."""
    span = cell_div.find("span", class_="type")
    if span is None:
        return "other"
    raw = (span.get("title") or span.get_text(strip=True) or "").lower()
    for ru_key, en_val in TYPE_MAP.items():
        if ru_key in raw:
            return en_val
    return "other"


def _extract_week(cell_div: Tag) -> str | None:
    """Return 'odd', 'even', or None."""
    week_div = cell_div.find("div", class_="week")
    if week_div is None:
        return None
    raw = week_div.get_text(strip=True).lower()
    if "нечет" in raw:
        return "odd"
    if "чет" in raw:
        return "even"
    return raw  # fallback – keep original text


def parse_timetable(html: str) -> list[dict]:
    """Parse a group schedule page and return a list of class entries."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="time-table")
    if table is None:
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    schedule: list[dict] = []

    # Row 0 is the header (Время | Пн | Вт | …).
    # Rows 1..7 correspond to time-slots 1..7.
    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue

        time_text = cells[0].get_text(strip=True)
        slot = TIME_TO_SLOT.get(time_text)
        if slot is None:
            log.warning("Unknown time text '%s', skipping row", time_text)
            continue

        # Cells 1‥6 → days Mon‥Sat
        for day_idx, td in enumerate(cells[1:], start=0):
            if day_idx >= len(DAY_NAMES):
                break
            day_name = DAY_NAMES[day_idx]
            day_num = day_idx + 1  # 1-based numeric day

            # A single <td> may contain 0, 1, or 2 div.cell elements
            # (2 = different classes on odd / even weeks)
            cell_divs = td.find_all("div", class_="cell", recursive=False)
            if not cell_divs:
                continue

            for cell_div in cell_divs:
                # Subject
                subj_div = cell_div.find("div", class_="subject")
                subject_short = subj_div.get_text(strip=True) if subj_div else None
                subject_full = (
                    subj_div.get("title", subject_short) if subj_div else None
                )
                if not subject_short:
                    continue

                # Type
                class_type = _extract_type(cell_div)

                # Teacher
                teacher_id, teacher_name = _extract_teacher(cell_div)
                if teacher_id:
                    data_store["teachers"][teacher_id] = teacher_name

                # Room
                room_id, room_display = _extract_room(cell_div)
                if room_id:
                    data_store["rooms"][room_id] = room_display

                # Week parity
                week = _extract_week(cell_div)

                # Apply fallback rule:
                # if neither teacher nor room → type = "other"
                if not teacher_id and not room_id:
                    class_type = "other"

                schedule.append({
                    "day": day_num,
                    "slot": slot,
                    "subject": subject_short,
                    "subject_full": subject_full,
                    "type": class_type,
                    "teacher_id": teacher_id,
                    "room_id": room_id,
                    "week": week,
                })

    return schedule


# ===================================================================
# Step 4 – process one group  (fetch + parse)
# ===================================================================
_processed_count = 0
_total_groups = 0


async def process_group(session: ClientSession, group_id: str) -> None:
    global _processed_count
    if not group_id.isnumeric() and '.' not in group_id:
        log.warning("Skipping group with unexpected ID format: %s", group_id)
        return
    html = await fetch(session, f"{BASE_URL}/group/{group_id}")
    if not html:
        log.warning("Empty response for group %s", group_id)
        return

    schedule = parse_timetable(html)
    meta = _group_meta.get(group_id, {})
    _processed_count += 1
    log.info(
        "[%d/%d] Group %s (%s, %s, year %s): %d classes.",
        _processed_count, _total_groups, group_id,
        meta.get("faculty_id", "?"), meta.get("degree", "?"),
        meta.get("year", "?"), len(schedule),
    )

    data_store["groups"][group_id] = {
        "faculty_id":   meta.get("faculty_id"),
        "faculty_name": meta.get("faculty_name"),
        "degree":       meta.get("degree"),
        "year":         meta.get("year"),
        "specialty":    meta.get("specialty"),
        "schedule":     schedule,
    }


# ===================================================================
# Main
# ===================================================================
async def main() -> None:
    connector = TCPConnector(limit=10)
    async with ClientSession(
        timeout=ClientTimeout(total=60), connector=connector
    ) as session:
        # 1. Faculties
        log.info("Fetching list of faculties …")
        faculties = await get_faculty_ids(session)
        log.info("Found %d faculties.", len(faculties))

        # 2. Groups + metadata  (sequential per faculty to stay ordered)
        all_group_ids: set[str] = set()
        for slug, name in faculties:
            gids = await scrape_faculty(session, slug, name)
            all_group_ids.update(gids)
            log.info("  %s: %d groups found.", name, len(gids))
        log.info("Discovered %d unique groups across all faculties.", len(all_group_ids))

        # 3. Timetables  (concurrent, rate-limited)
        global _total_groups, _processed_count
        _total_groups = len(all_group_ids)
        _processed_count = 0
        tasks = [process_group(session, gid) for gid in all_group_ids]
        await asyncio.gather(*tasks)

        # 4. Persist
        log.info("Writing %s …", OUTPUT_FILE)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
            json.dump(data_store, fh, indent=2, ensure_ascii=False)

        n_teachers = len(data_store["teachers"])
        n_rooms = len(data_store["rooms"])
        n_classes = sum(
            len(g["schedule"]) for g in data_store["groups"].values()
        )
        log.info(
            "Done. %d groups, %d teachers, %d rooms, %d class entries.",
            len(all_group_ids), n_teachers, n_rooms, n_classes,
        )


if __name__ == "__main__":
    asyncio.run(main())
