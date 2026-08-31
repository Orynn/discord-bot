# discord-bot (Arkann) — notes for agents

Python Discord bot for D&D: character sheets, combat, SRD lookups (5etools), campaign/lore tools, image generation.

## Run and test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # for lint/tests locally
python main.py
```

```bash
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
```

CI runs the same lint + unittest steps on push/PR.

## Layout

- `main.py` — entry point
- `bot/` — Discord events, slash commands, help, error handling
- `sheets/`, `combat/`, `srd/`, `campaign/`, `initiative/`, `roll/` — feature modules
- `data/db.py` — SQLite persistence
- `5etools/` — bundled 5e.tools data + optional homebrew JSON
- `tests/` — unittest suite (mirror module names where possible)

## Config and secrets

- Token: `.env` (`DISCORD_TOKEN`) — never commit
- Bot settings: `config.json` (copy from `config.example.json`)
- Homebrew: `5etools/homebrew.json` (gitignored)

## Conventions

- Command prefix is `;` (see `readme.md` for full command list)
- Keep changes minimal; match existing module boundaries
- Do not commit unless explicitly asked
- Prefer extending existing handlers over new parallel systems
