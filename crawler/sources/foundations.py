"""Approved calls from review/queue.yaml (found by the local AI monitor, checked by the admin)."""
from __future__ import annotations

from datetime import date

from common import Opportunity, guess_type, iso_date, tag_audiences

EU_CODES = {"EU", "EUROPE", "WORLDWIDE", "GLOBAL"}


def collect(queue: list[dict], funders: list[dict], today: date | None = None) -> list[Opportunity]:
    today = today or date.today()
    by_id = {f["id"]: f for f in funders or []}
    out = []
    for q in queue or []:
        if q.get("status") != "approved":
            continue
        deadline = iso_date(q.get("deadline"))
        if deadline and deadline < today.isoformat():
            continue
        f = by_id.get(q.get("funder"), {})
        countries = [str(c).upper() for c in q.get("eligible_countries") or f.get("eligible") or []]
        scope = ["EU"] if not countries or any(c in EU_CODES for c in countries) else sorted(set(countries))
        text = " ".join([q.get("title", ""), q.get("summary", ""), q.get("who_can_apply", "")])
        out.append(Opportunity(
            id=f"fnd-{q['id']}",
            title=q["title"],
            url=q["url"],
            source="foundations",
            source_name=q.get("funder_name") or f.get("name", "Foundation"),
            type=guess_type(text, "grant"),
            scope=scope,
            audiences=tag_audiences(text, base=f.get("themes", []), title=q.get("title", "")),
            language=f.get("language", "en"),
            programme=q.get("amount") or None,
            deadline=deadline,
            rolling=bool(q.get("rolling")) and not deadline,
            summary=q.get("summary", ""),
        ))
    return out
