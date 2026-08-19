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

`config.json` holds bot settings (prefix, catch-up, campaign category, 5etools paths). The token lives only in `.env` (gitignored).

## Project structure

```
discord-bot/
├── main.py              # Entry point
├── 5etools/             # Bundled 5e.tools site + data (official rules JSON)
│   ├── data/            # Loaded at runtime for ;srd lookups
│   ├── homebrew.json    # Your 5e.tools export (optional, gitignored)
│   └── 5etools.json     # Merged export backup (optional, gitignored)
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
| **sheets**     | `;sheet create/show/set/hp/money/prof/spells/slots/condition/inspire/deathsave/rest/info/import/delete` |
| **initiative** | `;init add/next/show/remove/clear`                                                                |
| **roll**       | `;roll` / `;r`                                                                                    |
| **srd**        | `;srd spell/species/class/background/feat/condition/monster/weapon/armor/item` (5etools) |
| **campaign**   | `;campaign` / `;lore` (admin)                                                                     |
| **players**    | `;player setup/list/remove @member` (admin) — private category + channels + sheet                 |
| **slash**      | `/roll`, `/sheet_show`, `/sheet_hp`, `/sheet_slots`, `/init_next`, `/srd`                       |

Re-export from 5e.tools when you add or update homebrew, then save to `5etools/homebrew.json`.

## Tests

```bash
python -m unittest discover -s tests -v
```

Uses the bundled `5etools/data/` plus any homebrew export present locally.
