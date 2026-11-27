"""Runs on DOPE's PC once a day (next to Ollama).

For every funder in config/funders.yaml:
  1. download its calls page and reduce it to readable text + links
  2. if the text changed since last time, ask the local model to list the open calls
  3. add new calls for organisations based in Europe to review/queue.yaml (status: pending)
Then commit + push, so GitHub publishes the calls the admin approves.

    python monitor/local_monitor.py            # normal daily run
    python monitor/local_monitor.py --all      # re-read every page, even unchanged ones
    python monitor/local_monitor.py --only ID  # test one funder, no push
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
FUNDERS = ROOT / "config" / "funders.yaml"
QUEUE = ROOT / "review" / "queue.yaml"
STATE = ROOT / "monitor" / "state.json"

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
UA = "Mozilla/5.0 (FundingRadar monitor by Dreaming OPEnly e.V.; non-profit funding finder)"
MAX_CHARS = 14000
QUEUE_HEADER = ("# Calls found by the local AI monitor. ADMIN: change \"status: pending\" to \"approved\" or \"rejected\".\n"
                "# Approved calls appear on the site at the next refresh. Rejected ones are never suggested again.\n")

CALL_SCHEMA = {
    "type": "object",
    "properties": {"calls": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "url": {"type": "string"},
            "deadline": {"type": ["string", "null"], "description": "YYYY-MM-DD or null"},
            "rolling": {"type": "boolean"},
            "is_open_now_or_upcoming": {"type": "boolean"},
            "open_to_organisations": {"type": "boolean"},
            "open_to_applicants_in_europe": {"type": "boolean"},
            "who_can_apply": {"type": "string"},
            "eligible_countries": {"type": "array", "items": {"type": "string"}},
            "amount": {"type": ["string", "null"]},
            "summary_en": {"type": "string"},
        },
        "required": ["title", "url", "deadline", "rolling", "is_open_now_or_upcoming",
                     "open_to_organisations", "open_to_applicants_in_europe", "who_can_apply",
                     "eligible_countries", "amount", "summary_en"],
    }}},
    "required": ["calls"],
}

PROMPT = """You read a funder's web page and list its funding calls.
Today is {today}. Funder: {name}.

Rules:
- Only real calls/programmes someone can apply to (grants, open calls, prizes/awards for projects). Not news, not past winners, not events.
- is_open_now_or_upcoming: true only if applications are open now or will open; false if closed/past.
- deadline: the next application deadline as YYYY-MM-DD, or null if none is given. rolling=true if applications are accepted any time.
- open_to_organisations: true if NGOs, associations, collectives or informal groups can apply (false if only individuals, universities or companies).
- open_to_applicants_in_europe: true if an organisation based in at least one European country can apply.
- eligible_countries: ISO-2 codes or "EU"/"Europe"/"worldwide" as stated.
- url: the most specific link for this call (use the LINKS list), absolute.
- title: keep the original language. summary_en: one neutral sentence in your own words (max 30 words).
- If the page lists no calls, return {{"calls": []}}. Never invent calls, dates or amounts.

PAGE TEXT:
{text}

LINKS (text -> url):
{links}
"""


def load_yaml(p: Path, default):
    return yaml.safe_load(p.read_text(encoding="utf-8")) or default if p.exists() else default


def page_text(url: str) -> tuple[str, str]:
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en,de;q=0.8,es;q=0.6"}, timeout=40)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]):
        tag.decompose()
    main = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body or soup
    text = re.sub(r"\n\s*\n+", "\n", main.get_text("\n", strip=True))[:MAX_CHARS]
    links, seen = [], set()
    for a in main.find_all("a", href=True):
        label = a.get_text(" ", strip=True)[:90]
        href = urljoin(r.url, a["href"])
        if label and href.startswith("http") and href not in seen:
            seen.add(href)
            links.append(f"{label} -> {href}")
    return text, "\n".join(links[:120])


def ask_model(funder: dict, text: str, links: str) -> list[dict]:
    body = {
        "model": MODEL,
        "stream": False,
        "format": CALL_SCHEMA,
        "options": {"temperature": 0, "num_ctx": 16384},
        "messages": [{"role": "user", "content": PROMPT.format(
            today=date.today().isoformat(), name=funder["name"], text=text, links=links)}],
    }
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    content = r.json()["message"]["content"]
    try:
        return json.loads(content).get("calls", [])
    except json.JSONDecodeError:
        print(f"  ! model returned invalid JSON for {funder['id']}")
        return []


def norm(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def keep(call: dict, today: str) -> bool:
    if not (call.get("open_to_organisations") and call.get("open_to_applicants_in_europe")):
        return False
    if not call.get("is_open_now_or_upcoming"):
        return False
    d = call.get("deadline")
    if d and re.match(r"\d{4}-\d{2}-\d{2}$", d) and d < today:
        return False
    return bool(call.get("title") and call.get("url", "").startswith("http"))


def git(*args) -> None:
    subprocess.run(["git", "-C", str(ROOT), *args], check=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args(argv)

    push = not (a.no_push or a.only)
    if push:
        git("pull", "--rebase", "--autostash", "-q")

    funders = load_yaml(FUNDERS, [])
    queue = load_yaml(QUEUE, [])
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    known = {q["id"] for q in queue}
    today = date.today().isoformat()
    added = 0

    for f in funders:
        if a.only and f["id"] != a.only:
            continue
        if f.get("enabled") is False:
            continue
        print(f"- {f['id']}: {f['calls_url']}")
        try:
            text, links = page_text(f["calls_url"])
        except Exception as exc:
            print(f"  ! download failed: {exc}")
            state.setdefault(f["id"], {})["error"] = str(exc)[:200]
            continue
        h = hashlib.sha1(text.encode()).hexdigest()
        if not a.all and state.get(f["id"], {}).get("hash") == h:
            print("  unchanged")
            continue
        calls = ask_model(f, text, links)
        for c in calls:
            if not keep(c, today):
                continue
            cid = f"{f['id']}-{hashlib.sha1(norm(c['title']).encode()).hexdigest()[:8]}"
            if cid in known:
                continue
            queue.append({
                "id": cid, "status": "pending", "funder": f["id"], "funder_name": f["name"],
                "title": c["title"], "url": c["url"], "deadline": c.get("deadline"),
                "rolling": bool(c.get("rolling")), "who_can_apply": c.get("who_can_apply", ""),
                "eligible_countries": c.get("eligible_countries", []), "amount": c.get("amount"),
                "summary": c.get("summary_en", ""), "found_at": today,
            })
            known.add(cid)
            added += 1
            print(f"  + {c['title'][:80]}")
        state[f["id"]] = {"hash": h, "checked": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        time.sleep(2)

    QUEUE.write_text(QUEUE_HEADER + yaml.safe_dump(queue, allow_unicode=True, sort_keys=False, width=120),
                     encoding="utf-8")
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"done: {added} new call(s) waiting for review")

    if push:
        git("add", "review/queue.yaml", "monitor/state.json")
        if subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--quiet"]).returncode:
            git("commit", "-q", "-m", f"Monitor: {added} new call(s) for review ({today})")
            try:
                git("push", "-q")
            except subprocess.CalledProcessError:  # the site bot pushed meanwhile: rebase and retry once
                git("pull", "--rebase", "-q")
                git("push", "-q")


if __name__ == "__main__":
    sys.exit(main())
