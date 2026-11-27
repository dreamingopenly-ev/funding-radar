"""Förderdatenbank des Bundes — via the weekly open dataset published by CorrelAid
(https://fdb.cdl.correlaid.org, CC BY-ND 4.0, built from the official XML export).

We keep programmes open to associations ("Verband/Vereinigung") that give grants
("Zuschuss"), and store only title, official link, dates and categories — no
descriptions — with attribution. The CSV (~50 MB) is refreshed weekly upstream, so
we only download it once a week (on `download_weekday`).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date

import requests

from common import Opportunity, USER_AGENT, iso_date, tag_audiences

log = logging.getLogger(__name__)

CSV_URL = "https://fdb.cdl.correlaid.org/data/programme.csv"
ATTRIBUTION = "Förderdatenbank des Bundes (BMWE) · data via CorrelAid, CC BY-ND 4.0"
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")

# Fördergebiet codes -> our scope. Anything that isn't EU-wide or "bundesweit" is a Land.
LAND_HINT = re.compile(r"baden|bayern|berlin|brandenburg|bremen|hamburg|hessen|mecklenburg|niedersachsen|"
                       r"nordrhein|rheinland|saarland|sachsen|schleswig|th(ue|ü)ringen", re.I)


LAND_NAMES = {
    "baden_wuerttemberg": "Baden-Württemberg", "bayern": "Bayern", "berlin": "Berlin", "brandenburg": "Brandenburg",
    "bremen": "Bremen", "hamburg": "Hamburg", "hessen": "Hessen", "mecklenburg_vorpommern": "Mecklenburg-Vorpommern",
    "niedersachsen": "Niedersachsen", "nordrhein_westfalen": "Nordrhein-Westfalen", "rheinland_pfalz": "Rheinland-Pfalz",
    "saarland": "Saarland", "sachsen": "Sachsen", "sachsen_anhalt": "Sachsen-Anhalt",
    "schleswig_holstein": "Schleswig-Holstein", "thueringen": "Thüringen",
}
AREA_THEMES = {  # Förderbereich -> our themes
    "kultur_medien_sport": "culture", "umwelt_naturschutz": "sustainability",
    "energieeffizienz_erneuerbare_energien": "sustainability", "mobilitaet": "sustainability",
    "gesundheit_soziales": "inclusion", "frauenfoerderung": "inclusion", "aus_weiterbildung": "education",
}


def clean_title(t: str) -> str:
    """The upstream export turns dashes and quotes into '?'."""
    t = re.sub(r"(?<=\d)\?(?=\d)", "–", t)
    t = re.sub(r" \? ", " – ", t)
    t = re.sub(r"\?(\w[^?]*?)\?", r"„\1“", t)
    return t.strip()


class SkipToday(Exception):
    """Not a download day: keep last week's entries."""


def _arr(value: str) -> list[str]:
    if not value:
        return []
    try:
        v = json.loads(value)
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]
    except (ValueError, TypeError):
        return [x.strip() for x in re.split(r"[;,|]", value) if x.strip()]


def _short(code: str) -> str:
    """'https://…/fdb#verband_vereinigung' or 'fdb:verband_vereinigung' -> 'verband_vereinigung'."""
    return re.split(r"[#:/]", code)[-1].lower()


def _deadline(text: str, today: date) -> tuple[str | None, bool]:
    """Return (earliest future date, all_dates_past)."""
    dates = []
    for d, m, y in DATE_RE.findall(text or ""):
        try:
            dates.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    future = sorted(x for x in dates if x >= today)
    return (future[0].isoformat() if future else None, bool(dates) and not future)


def parse_rows(rows, cfg: dict, today: date) -> list[Opportunity]:
    want_app = [w.lower() for w in cfg.get("eligible_contains", ["verband", "verein"])]
    want_type = [w.lower() for w in cfg.get("funding_type_contains", ["zuschuss"])]
    skip_area = re.compile(cfg.get("exclude_area_regex", r"$^"), re.I)
    out, seen_area = [], {}
    for r in rows:
        if str(r.get("absent", "")).lower() in ("true", "1"):
            continue
        apps = [_short(x) for x in _arr(r.get("eligible_applicants", ""))]
        types = [_short(x) for x in _arr(r.get("funding_type", ""))]
        if not any(w in a for a in apps for w in want_app):
            continue
        if not any(w in t for t in types for w in want_type):
            continue
        areas = [_short(x) for x in _arr(r.get("funding_area", ""))]
        for a in areas:
            seen_area[a] = seen_area.get(a, 0) + 1
        if areas and all(skip_area.search(a) for a in areas):
            continue
        deadline, expired = _deadline(r.get("deadlines", ""), today)
        if expired:
            continue
        locs = [_short(x) for x in _arr(r.get("funding_location", ""))]
        lands = sorted({LAND_NAMES.get(l, l.replace("_", "-").title()) for l in locs if LAND_HINT.search(l)})
        title = clean_title(r.get("title") or "")
        if not title or not r.get("url"):
            continue
        text = " ".join([title, r.get("keywords", ""), " ".join(areas)])
        out.append(Opportunity(
            id=f"fdb-{r.get('id_hash') or r.get('id_url')}",
            title=title,
            url=r["url"],
            source="foerderdatenbank",
            source_name=ATTRIBUTION,
            type="grant",
            scope=["DE"],
            audiences=tag_audiences(text, base=[AREA_THEMES[a] for a in areas if a in AREA_THEMES], title=title),
            regions=lands or ["Bundesweit"],
            language="de",
            programme=", ".join(a.replace("_", " ").title() for a in areas[:2]) or None,
            deadline=deadline,
            opens=iso_date(r.get("date_of_issue")),
            rolling=deadline is None,
            summary="",
        ))
    log.info("foerderdatenbank: kept %s | funding areas seen: %s", len(out),
             dict(sorted(seen_area.items(), key=lambda x: -x[1])))
    return out


def collect(cfg: dict, today: date | None = None, force: bool = False) -> list[Opportunity]:
    today = today or date.today()
    if not force and today.weekday() != int(cfg.get("download_weekday", 0)):
        raise SkipToday("weekly source, not a download day")
    r = requests.get(cfg.get("url", CSV_URL), headers={"User-Agent": USER_AGENT}, timeout=180)
    r.raise_for_status()
    csv.field_size_limit(50_000_000)
    text = r.content.decode("utf-8-sig", errors="replace")
    sample = text[:5000]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    return parse_rows(csv.DictReader(io.StringIO(text), delimiter=delim), cfg, today)
