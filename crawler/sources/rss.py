"""Generic RSS/Atom adapter for funding blogs and news pages.

Only the title, link, date and an auto-detected deadline are stored — not the
article text — and every entry links back to the original source.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import feedparser
import requests

from common import Opportunity, USER_AGENT, clean_text, find_deadline, make_id, tag_audiences, guess_type, NOT_FOR_NGOS

log = logging.getLogger(__name__)
MAX_AGE_DAYS = 120  # undated posts older than this are dropped


def _published(entry) -> date | None:
    for k in ("published_parsed", "updated_parsed"):
        t = entry.get(k)
        if t:
            return datetime(*t[:6]).date()
    return None


def parse_feed(raw: bytes | str, feed_cfg: dict, today: date) -> list[Opportunity]:
    parsed = feedparser.parse(raw)
    out = []
    for e in parsed.entries:
        title = clean_text(e.get("title"))
        link = e.get("link")
        if not title or not link:
            continue
        body = clean_text(e.get("summary") or "") + " " + " ".join(
            clean_text(c.get("value")) for c in e.get("content", []) or []
        )
        blob = f"{title} {body}"
        if NOT_FOR_NGOS.search(blob):
            continue
        deadline = find_deadline(blob, today)
        pub = _published(e)
        # Drop old posts with no future deadline: they are almost always expired
        if not deadline and pub and (today - pub) > timedelta(days=MAX_AGE_DAYS):
            continue
        out.append(Opportunity(
            id=make_id("rss", link),
            title=title,
            url=link,
            source="rss",
            source_name=feed_cfg["name"],
            type=guess_type(blob, "grant") if deadline else "news",  # no deadline found -> article/tip
            scope=list(feed_cfg.get("scope") or []),
            audiences=tag_audiences(blob),
            language=feed_cfg.get("language", "de"),
            deadline=deadline,
            opens=pub.isoformat() if pub else None,
            rolling=False,
            summary="",  # we don't copy third-party text
        ))
    return out


def collect(feeds: list[dict], today: date | None = None) -> list[Opportunity]:
    today = today or date.today()
    out: list[Opportunity] = []
    tried = failed = 0
    for f in feeds or []:
        if f.get("enabled") is False:
            continue
        tried += 1
        try:
            r = requests.get(f["url"], headers={"User-Agent": USER_AGENT}, timeout=40)
            r.raise_for_status()
            items = parse_feed(r.content, f, today)
            log.info("rss %s: %s items", f["name"], len(items))
            out.extend(items)
        except Exception as exc:  # one broken feed must not stop the run
            failed += 1
            log.warning("rss %s failed: %s", f.get("name"), exc)
    if tried and failed == tried:
        raise RuntimeError("all RSS feeds failed")  # keeps last known RSS entries online
    return out
