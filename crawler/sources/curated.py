"""Hand-curated programmes from config/curated.yaml."""
from __future__ import annotations

from datetime import date

from common import Opportunity, iso_date


def collect(items: list[dict], today: date | None = None) -> list[Opportunity]:
    today = today or date.today()
    out = []
    for it in items or []:
        deadline = iso_date(it.get("deadline"))
        if deadline and deadline < today.isoformat():
            continue
        out.append(Opportunity(
            id=it["id"],
            title=it["title"],
            url=it["url"],
            source="curated",
            source_name=it.get("source_name", "Curated by the network"),
            type=it.get("type", "grant"),
            scope=list(it.get("scope") or []),
            audiences=sorted(it.get("audiences") or []),
            language=it.get("language", "en"),
            programme=it.get("programme"),
            deadline=deadline,
            rolling=bool(it.get("rolling")),
            summary=it.get("summary", ""),
        ))
    return out
