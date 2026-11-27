"""Shared helpers: the Opportunity record, text cleaning, deadline parsing, tagging."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime

USER_AGENT = "FundingRadarBot/0.1 (+non-profit funding finder by Dreaming OPEnly e.V.)"


@dataclass
class Opportunity:
    id: str
    title: str
    url: str
    source: str                      # adapter key, e.g. "eu_portal"
    source_name: str                 # human name, e.g. "EU Funding & Tenders Portal"
    type: str = "grant"              # grant | contest | subsidy | training | news
    scope: list[str] = field(default_factory=list)      # EU, DE, ES, PT, FR, IT, ...
    audiences: list[str] = field(default_factory=list)  # youth, migrants, culture, ...
    regions: list[str] = field(default_factory=list)    # sub-national, e.g. German Länder
    language: str = "en"
    programme: str | None = None
    deadline: str | None = None      # ISO date
    opens: str | None = None
    rolling: bool = False
    summary: str = ""
    first_seen: str | None = None
    last_seen: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def make_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()[:10]
    return f"{prefix}-{h}"


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(s: str | None, limit: int | None = None) -> str:
    if not s:
        return ""
    s = html.unescape(TAG_RE.sub(" ", s))
    s = WS_RE.sub(" ", s).strip()
    if limit and len(s) > limit:
        s = s[: limit].rsplit(" ", 1)[0] + "…"
    return s


def norm_key(title: str) -> str:
    """Key for detecting the same opportunity from two sources."""
    t = clean_text(title).lower()
    t = re.sub(r"[^a-z0-9äöüßáéíóúñçàèìòùâêôãõ ]", "", t)
    return WS_RE.sub(" ", t).strip()


# ---------- deadlines ----------
MONTHS = {
    # de
    "januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
    # en
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12,
    # es / pt / it / fr (common forms)
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "settembre": 9,
    "ottobre": 10, "dicembre": 12,
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "juin": 6, "juillet": 7, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}
DEADLINE_WORDS = (
    r"(?:frist|bewerbungsfrist|einsendeschluss|bewerbungsschluss|antragsfrist|stichtag|deadline|"
    r"bis zum|bis|plazo|fecha límite|prazo|scadenza|date limite|date limite|avant le|until|by)"
)
NUM_DATE = re.compile(DEADLINE_WORDS + r"[^0-9]{0,25}(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{2,4})", re.I)
WORD_DATE = re.compile(
    DEADLINE_WORDS + r"[^0-9]{0,25}(\d{1,2})\.?\s+(?:de\s+)?([a-zäöüéèûôçã]+)\s+(?:de\s+)?(\d{4})", re.I
)


def find_deadline(text: str, today: date | None = None) -> str | None:
    """Best-effort: first future date that follows a deadline word."""
    today = today or date.today()
    found: list[date] = []
    for m in NUM_DATE.finditer(text or ""):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            found.append(date(y, mo, d))
        except ValueError:
            pass
    for m in WORD_DATE.finditer(text or ""):
        mo = MONTHS.get(m.group(2).lower())
        if mo:
            try:
                found.append(date(int(m.group(3)), mo, int(m.group(1))))
            except ValueError:
                pass
    future = sorted(d for d in found if d >= today)
    return future[0].isoformat() if future else None


def iso_date(value) -> str | None:
    if not value:
        return None
    s = str(value)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    for fmt in ("%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


# ---------- tagging ----------
AUDIENCE_RULES = {
    "migrants": r"migra|refugee|geflüchte|flüchtling|asyl|asylum|integration of (?:migrants|refugees|third)|integrationsarbeit|integrationsprojekt|"
                r"diaspora|newcomer|third[- ]country national|amif|réfugi|rifugiat|refugiad",
    "latam": r"latin america|lateinamerika|latinoam[eé]rica|am[eé]rica latina|latino",
    "youth": r"youth|jugend|juvent|jóvenes|jovens|giovan|jeunes|young people|junge menschen|solidarity corps|jugendarbeit|jugendverband",
    "culture": r"cultur|kultur|\bart\b|\barts\b|kunst|artist|künstl|music|musik|theat|film|creative",
    "democracy": r"democra|demokrat|citizen|bürger|civic|participation|beteiligung|rule of law|rights",
    "sustainability": r"climate|klima|sustainab|nachhaltig|environment|umwelt|green|biodivers|energy transition",
    "inclusion": r"inclusi|inklusi|disabilit|behinder|equality|gleichstellung|anti-?discrim|antidiskrim",
    "volunteering": r"volunteer|ehrenamt|freiwillig|voluntari|bénévol",
}
TYPE_RULES = [
    ("contest", r"wettbewerb|preis\b|award|prize|contest|concurso|premio|prémio|prix\b|concorso"),
    ("training", r"training course|seminar|workshop|fortbildung|weiterbildung|formación|formação|formazione"),
    ("subsidy", r"zuschuss|subvenci|subsídio|sovvenzion|subvention"),
]
COMPILED_AUD = {k: re.compile(v, re.I) for k, v in AUDIENCE_RULES.items()}
COMPILED_TYPE = [(k, re.compile(v, re.I)) for k, v in TYPE_RULES]

# Things that are clearly not for NGOs (used to drop noise automatically)
NOT_FOR_NGOS = re.compile(
    r"\b(procurement|call for tender|ausschreibung von bauleistungen|startup only|sme instrument|"
    r"kredit|darlehen|loan|bürgschaft|venture capital)\b", re.I
)


STRICT_TAGS = {"migrants", "latam"}  # avoid tagging on one passing mention in a long text


def tag_audiences(text: str, base: list[str] | None = None, title: str = "") -> list[str]:
    tags = set(base or [])
    for k, rx in COMPILED_AUD.items():
        if k in STRICT_TAGS:
            if rx.search(title or "") or len(rx.findall(text or "")) >= 2:
                tags.add(k)
        elif rx.search(text or ""):
            tags.add(k)
    if "latam" in tags:
        tags.add("migrants") if COMPILED_AUD["migrants"].search(text or "") else None
    return sorted(tags)


def guess_type(text: str, default: str = "grant") -> str:
    for k, rx in COMPILED_TYPE:
        if rx.search(text or ""):
            return k
    return default
