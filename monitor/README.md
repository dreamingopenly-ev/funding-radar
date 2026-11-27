# Foundation-calls monitor (runs on DOPE's PC)

Every day this script reads the calls page of each funder in `config/funders.yaml`.
When a page has changed, your local AI (Ollama) lists the open calls. New calls for
organisations based in Europe go to `review/queue.yaml` with `status: pending`,
and the script pushes them to GitHub.

## One-time setup (Windows)

1. Install **Git for Windows** and **Python 3.12** (tick "Add python.exe to PATH").
2. Clone the repository, for example into `C:\DOPE\funding-radar`:
   `git clone https://github.com/dreamingopenly-ev/funding-radar C:\DOPE\funding-radar`
   The first push will ask you to sign in to GitHub with the DOPE account.
3. Install the libraries: `pip install -r C:\DOPE\funding-radar\monitor\requirements.txt`
4. Choose the model. The default is `qwen2.5:14b` (`ollama pull qwen2.5:14b`). To use one you
   already have, set an environment variable `OLLAMA_MODEL`, e.g. `setx OLLAMA_MODEL "llama3.1:8b"`.
   It needs a model that can follow instructions and return JSON. Bigger models make fewer mistakes.
5. Test with one funder (nothing is pushed):
   `python C:\DOPE\funding-radar\monitor\local_monitor.py --only eyf`
6. Schedule it: **Task Scheduler → Create Basic Task → Daily**, at the hour the PC is on,
   action "Start a program" → `C:\DOPE\funding-radar\monitor\run_monitor.bat`.
   (Alternative: an n8n Schedule node followed by an "Execute Command" node running the same .bat.)

The log of the last runs is in `monitor\last_run.log`.

## Reviewing calls (admin)

Open `review/queue.yaml` on GitHub, click the pencil icon, and change `status: pending` to
`approved` or `rejected`. Saving (commit) refreshes the site within a few minutes.
Rejected calls are never suggested again.

## Adding funders

Add an entry to `config/funders.yaml` with the URL of the page where the funder lists its calls.
Use `python monitor/local_monitor.py --only <id>` to test it.
