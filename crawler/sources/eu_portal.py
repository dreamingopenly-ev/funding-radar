"""EU Funding & Tenders Portal — official public search API (no key needed).

Reads open + forthcoming calls for proposals and keeps the programmes listed in
config/sources.yaml (Erasmus+, ESC, CERV, Creative Europe, AMIF, ...).
"""
from __future__ import annotations

import json
import re
import logging
import time
from datetime import date

import requests

from common import Opportunity, USER_AGENT, clean_text, iso_date, tag_audiences, guess_type

log = logging.getLogger(__name__)

API = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{}"
STATUS = {"31094501": "forthcoming", "31094502": "open", "31094503": "closed"}
# type 1 = call for proposals topic, 2 = call for proposals (non-topic), 8 = cascade funding
QUERY = {"bool": {"must": [
    {"terms": {"type": ["1", "2", "8"]}},
    {"terms": {"status": ["31094501", "31094502"]}},
]}}


def _first(meta: dict, key: str):
    v = meta.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _all(meta: dict, key: str) -> list:
    v = meta.get(key)
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def fetch_page(session: requests.Session, page: int, page_size: int = 100) -> dict:
    params = {"apiKey": "SEDIA", "text": "***", "pageSize": page_size, "pageNumber": page}
    files = {
        "query": ("blob", json.dumps(QUERY), "application/json"),
        "languages": ("blob", json.dumps(["en"]), "application/json"),
        "sort": ("blob", json.dumps({"field": "sortStatus", "order": "ASC"}), "application/json"),
    }
    r = session.post(API, params=params, files=files, timeout=60)
    if r.status_code >= 400:  # fallback: plain JSON body
        r = session.post(API, params=params, json=QUERY, timeout=60)
    r.raise_for_status()
    return r.json()


def parse_result(res: dict, prefixes: dict, cascade_kw: list[str], today: date,
                 exclude: list[str] | None = None) -> Opportunity | None:
    meta = res.get("metadata") or {}
    ident = (_first(meta, "identifier") or _first(meta, "callIdentifier") or "").strip()
    title = clean_text(_first(meta, "title") or res.get("summary") or ident)
    if not ident or not title:
        return None
    if any(x.upper() in ident.upper() for x in exclude or []):
        return None

    rtype = str(_first(meta, "type") or "")
    head = ident.split("-")[0].upper()
    programme = prefixes.get(head)
    text_blob = " ".join([title, clean_text(_first(meta, "descriptionByte")), clean_text(res.get("content"))])

    if programme is None:
        is_cascade = rtype == "8"
        if not (is_cascade and any(re.search(rf"\b{re.escape(k)}\b", text_blob, re.I) for k in cascade_kw)):
            return None
        programme = "EU cascade funding"

    # earliest deadline still in the future (two-stage calls have several)
    deadlines = sorted(d for d in (iso_date(x) for x in _all(meta, "deadlineDate")) if d)
    future = [d for d in deadlines if d >= today.isoformat()]
    if deadlines and not future:
        return None  # expired
    deadline = future[0] if future else None

    url = res.get("url") or TOPIC_URL.format(ident.lower())
    if url.endswith(".json") or "topicDetails" in url:
        url = TOPIC_URL.format(ident.lower())

    return Opportunity(
        id=f"eu-{ident}",
        title=title,
        url=url,
        source="eu_portal",
        source_name="EU Funding & Tenders Portal",
        type=guess_type(title, "grant"),
        scope=["EU"],
        audiences=tag_audiences(text_blob + " " + programme, title=title + " " + programme),
        language="en",
        programme=f"{programme} · {ident}",
        deadline=deadline,
        opens=iso_date(_first(meta, "startDate")),
        rolling=False,
        summary=clean_text(_first(meta, "descriptionByte") or res.get("content"), 280),
    )


def collect(cfg: dict, today: date | None = None) -> list[Opportunity]:
    today = today or date.today()
    prefixes = {k.upper(): v for k, v in (cfg.get("programme_prefixes") or {}).items()}
    cascade_kw = cfg.get("cascade_keywords") or []
    exclude = cfg.get("exclude_identifier_contains") or []
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    out: dict[str, Opportunity] = {}
    page, total = 1, None
    while True:
        data = fetch_page(s, page)
        results = data.get("results") or []
        total = total or int(data.get("totalResults") or 0)
        for res in results:
            opp = parse_result(res, prefixes, cascade_kw, today, exclude)
            if opp:
                out.setdefault(opp.id, opp)
        log.info("eu_portal page %s: %s results (kept %s total)", page, len(results), len(out))
        if not results or page * 100 >= total or page >= 30:
            break
        page += 1
        time.sleep(1)
    return list(out.values())
