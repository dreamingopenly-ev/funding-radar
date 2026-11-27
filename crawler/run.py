"""Run all sources, clean the results and write docs/data/opportunities.json.

    python crawler/run.py                # live run
    python crawler/run.py --offline DIR  # use saved fixtures (for tests)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from common import Opportunity, norm_key  # noqa: E402
from sources import curated, eu_portal, foerderdatenbank, rss  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
OUT = ROOT / "docs" / "data" / "opportunities.json"
SOURCE_PRIORITY = {"curated": 0, "eu_portal": 1, "foerderdatenbank": 2, "rss": 3}  # who wins a duplicate

log = logging.getLogger("run")


def load_yaml(name: str):
    p = CONFIG / name
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None


def load_previous() -> dict[str, dict]:
    if OUT.exists():
        data = json.loads(OUT.read_text(encoding="utf-8"))
        return {o["id"]: o for o in data.get("items", [])}
    return {}


def collect_all(offline: Path | None, today: date) -> tuple[list[Opportunity], dict[str, str]]:
    cfg = load_yaml("sources.yaml") or {}
    status: dict[str, str] = {}
    items: list[Opportunity] = []

    def run(name, fn):
        try:
            got = fn()
            items.extend(got)
            status[name] = f"ok ({len(got)})"
        except foerderdatenbank.SkipToday as exc:
            status[name] = f"skipped: {exc}"
        except Exception as exc:
            log.exception("source %s failed", name)
            status[name] = f"failed: {exc.__class__.__name__}"

    run("curated", lambda: curated.collect(load_yaml("curated.yaml") or [], today))

    eu_cfg = cfg.get("eu_portal") or {}
    if eu_cfg.get("enabled", True):
        if offline:
            def eu_offline():
                data = json.loads((offline / "eu_portal.json").read_text())
                pre = {k.upper(): v for k, v in eu_cfg["programme_prefixes"].items()}
                res = [eu_portal.parse_result(r, pre, eu_cfg.get("cascade_keywords", []), today)
                       for r in data["results"]]
                return [r for r in res if r]
            run("eu_portal", eu_offline)
        else:
            run("eu_portal", lambda: eu_portal.collect(eu_cfg, today))

    fdb_cfg = cfg.get("foerderdatenbank") or {}
    if fdb_cfg.get("enabled", False) and not offline:
        prev_fdb = [o for o in load_previous().values() if o.get("source") == "foerderdatenbank"]
        have_fdb = bool(prev_fdb) and all("regions" in o for o in prev_fdb)  # re-download after schema changes
        run("foerderdatenbank", lambda: foerderdatenbank.collect(fdb_cfg, today, force=not have_fdb))

    feeds = cfg.get("rss") or []
    if offline:
        def rss_offline():
            out = []
            for f in feeds:
                p = offline / f"{f['name'].replace(' ', '_')}.xml"
                if p.exists():
                    out += rss.parse_feed(p.read_bytes(), f, today)
            return out
        run("rss", rss_offline)
    else:
        run("rss", lambda: rss.collect(feeds, today))
    return items, status


def merge(items: list[Opportunity], previous: dict[str, dict], status: dict[str, str],
          removed: set[str], today: date) -> list[dict]:
    now = today.isoformat()
    failed_sources = {k for k, v in status.items() if v.startswith(("failed", "skipped"))}

    # 1. keep last known items of sources that failed this run (a broken feed shouldn't empty the site)
    current = {o.id: o.to_dict() for o in items}
    for oid, old in previous.items():
        if old.get("source") in failed_sources and oid not in current:
            current[oid] = old

    # 2. dates, removals, expiry
    out = {}
    for oid, o in current.items():
        if oid in removed:
            continue
        if o.get("deadline") and o["deadline"] < now:
            continue
        prev = previous.get(oid)
        o["first_seen"] = (prev or {}).get("first_seen") or now
        o["last_seen"] = now
        out[oid] = o

    # 3. duplicates across sources (same title) -> keep the most reliable source
    by_key: dict[str, dict] = {}
    for o in sorted(out.values(), key=lambda x: SOURCE_PRIORITY.get(x["source"], 9)):
        k = norm_key(o["title"])
        if k and k in by_key:
            continue
        by_key[k or o["id"]] = o

    return sorted(by_key.values(), key=lambda o: (o["deadline"] is None, o["deadline"] or "", o["title"]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", type=Path, help="folder with fixtures instead of live requests")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    today = date.fromisoformat(args.today) if args.today else date.today()
    removed = {r["id"] for r in (load_yaml("removed.yaml") or []) if isinstance(r, dict) and r.get("id")}
    items, status = collect_all(args.offline, today)
    final = merge(items, load_previous(), status, removed, today)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": status,
        "count": len(final),
        "items": final,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("wrote %s items -> %s | %s", len(final), OUT, status)


if __name__ == "__main__":
    main()
