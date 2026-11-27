# Funding Radar (working name)

A public, multilingual list of funding for NGOs, youth organisations and migrant-led collectives in Germany and Europe. It refreshes itself every day. Built by Dreaming OPEnly e.V.

## How it works

```
config/            ← the only place you normally edit
  sources.yaml     which sources are crawled (EU portal programmes, RSS feeds)
  curated.yaml     programmes added by hand (rolling funds, foundations)
  removed.yaml     ADMIN ONLY: ids hidden from the site
crawler/           Python: fetch → clean → tag → merge → docs/data/opportunities.json
docs/              the website (GitHub Pages serves this folder)
.github/workflows  daily refresh at 04:17 UTC + manual "Run workflow" button
```

**Automatic cleaning, on every run:** expired calls are dropped, duplicates across sources are merged (the most reliable source is kept), loans and procurement are filtered out, EU calls are limited to NGO-relevant programmes (Erasmus+, ESC, CERV, Creative Europe, AMIF, ESF+, LIFE…), and old blog posts with no future deadline are removed. If a source fails, its last known entries stay up until the next run that works.

**Tags:** youth, migrants, Latin America, culture, democracy, sustainability, inclusion and volunteering are detected from keywords in six languages.

**Reports:** each entry has a "Report" link. It opens a pre-filled GitHub issue if `repo` is set in `docs/config.js`, otherwise an e-mail to `reportEmail`. Only the admin removes entries, by adding the id to `config/removed.yaml`. The change goes live on the next run, which starts by itself after a push to `config/`.

## One-time setup on GitHub

1. Push this folder to the repository.
2. **Settings → Pages →** Source: *Deploy from a branch*, Branch: `main`, folder `/docs`.
3. **Actions →** enable workflows, open *Refresh opportunities* and click **Run workflow** for the first crawl.
4. Set `repo` (and optionally `reportEmail`) in `docs/config.js`.

## Foundation calls (watchlist + local AI)

`config/funders.yaml` lists funders with open calls. DOPE's PC reads their pages every day with the
local AI and puts new calls in `review/queue.yaml`. The admin approves them, and approved calls go live.
Setup and review steps: [monitor/README.md](monitor/README.md).

## Adding sources

- **RSS feed:** add `name / url / scope / language` under `rss:` in `sources.yaml`.
- **Hand-picked programme:** add an item to `curated.yaml`, with a short summary in your own words.
- **New EU programme:** add its identifier prefix under `programme_prefixes`.

Only the title, link, dates and tags are stored from third-party feeds, never their article text. Every entry links back to the original.

## Local test

```
pip install -r requirements.txt
python crawler/run.py --offline tests/fixtures --today 2026-11-27   # fixtures, no internet
python -m http.server -d docs 8000                                  # open http://localhost:8000
```

## Roadmap

- More national sources for ES, PT, FR, IT (and other EU countries), with a focus on migrant and diaspora organisations
- Optional AI step (DOPE's local AI via n8n) to read pages without RSS and fill in deadline and eligibility
- Translated summaries
- Name, logo and branding
