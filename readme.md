# Arkann — Discord D&D Bot

## Setup

1. Copy env and config templates:

```bash
cp .env.example .env
cp config.example.json config.json
```

2. Put your Discord bot token in `.env`:

```bash
DISCORD_TOKEN=your_token_here
```

3. **5etools data** — the repo bundles the [5etools-src](https://github.com/5etools-mirror-3/5etools-src) site under `5etools/` (official JSON in `5etools/data/`). Export your homebrew from [5e.tools](https://5e.tools) (*Manage Content → Export*) to `5etools/homebrew.json`, or keep a merged copy at `5etools/5etools.json`.

4. Install and run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

To keep the bot up after crashes (and after logout), install the user systemd service:

```bash
chmod +x deploy/install-service.sh scripts/run.sh
./deploy/install-service.sh
# logs: journalctl --user -u arkann.service -f
```

`scripts/run.sh` is the same restart loop without systemd. Daily snapshots of `data/arkann.db` land in `data/backups/` (14 kept).

This machine has no NVIDIA GPU, so `;image` uses a **CPU** worker (`stabilityai/sd-turbo`, ~512px) when `scripts/install-image.sh` has been run. `image_provider` defaults to `auto`: local first, Pollinations if the worker is still loading or down.

```bash
chmod +x scripts/install-image.sh
./scripts/install-image.sh
# logs: journalctl --user -u arkann-image.service -f
```

`config.json` holds bot settings (prefix, catch-up, campaign category, 5etools paths). The token lives only in `.env` (gitignored).

## Project structure

```
discord-bot/
├── main.py              # Entry point
├── 5etools/             # Bundled 5e.tools site + data (official rules JSON)
│   ├── data/            # Loaded at runtime for ;srd lookups
│   ├── homebrew.json    # Your 5e.tools export (optional, gitignored)
│   └── 5etools.json     # Merged export backup (optional, gitignored)
├── deploy/              # systemd user units (auto-restart + daily DB backup)
├── scripts/             # 5etools export, run loop, SQLite backup
├── config.py            # Loads config.json / env
├── data/
│   └── db.py            # SQLite storage + JSON migration
├── bot/
├── sheets/              # Character sheets (;sheet)
├── srd/
│   └── fivetools/       # 5etools index, lookup, export utilities
└── tests/
```

## 5etools utilities

At runtime the bot loads **official rules** from `5etools/data/` and **homebrew** from `5etools/homebrew.json` (preferred) or `5etools/5etools.json`.

```bash
# Build a merged export (backup / sharing)
python scripts/export_5etools_official.py build

# Extract homebrew-only from a merged export
python scripts/export_5etools_official.py extract-homebrew --from 5etools/5etools.json
```

## Commands

Use `;help` or `;aide` in Discord for the full in-game list (sectioned embed + emoji buttons).

| Module         | Commands                                                                                          |
| -------------- | ------------------------------------------------------------------------------------------------- |
| **help**       | `;help`, `;aide`                                                                                  |
| **image**      | `;image` / `;dessine` / `;draw` — illustrate this channel's RP (optional prompt focuses the shot) |
| **sheets**     | `;sheet create/show/set/hp/money/prof/spells/slots/condition/inspire/deathsave/rest/info/import/delete` |
| **initiative** | `;init add/next/show/remove/clear`                                                                |
| **roll**       | `;roll` / `;r`                                                                                    |
| **srd**        | `;srd spell/species/class/background/feat/condition/monster/weapon/armor/item` (5etools) |
| **campaign**   | `;campaign` / `;lore` (admin) — including `;campaign document` parchment                          |
| **players**    | `;player setup/list/remove @member` (admin) — private category + channels + sheet                 |
| **slash**      | `/roll`, `/sheet_show`, `/sheet_hp`, `/sheet_slots`, `/init_next`, `/srd`                       |

Re-export from 5e.tools when you add or update homebrew, then save to `5etools/homebrew.json`.

## Tests

```bash
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
```

Uses the bundled `5etools/data/` plus any homebrew export present locally.
