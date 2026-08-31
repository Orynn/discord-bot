#!/usr/bin/env python3
"""Build or split 5e.tools export files for the Discord bot.

Official rules data is loaded at runtime from bundled 5etools/data/ JSON.
Use this script to:
  - build a merged export (official + homebrew) for backup/sharing
  - extract homebrew-only export to 5etools/homebrew.json

Usage:
    python scripts/export_5etools_official.py build
    python scripts/export_5etools_official.py extract-homebrew --from 5etools/5etools.json
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from srd.fivetools.export import (
    build_export,
    extract_homebrew_export,
    write_json,
)
from srd.fivetools.source import build_official_body, summarize_body

DEFAULT_DATA_DIR = ROOT / "5etools" / "data"
DEFAULT_OUTPUT = ROOT / "5etools" / "5etools.json"
DEFAULT_HOMEBREW = ROOT / "5etools" / "homebrew.json"
REPO_URL = "https://github.com/5etools-mirror-3/5etools-src.git"
CACHE_REPO = ROOT / ".cache" / "5etools-src"


def _ensure_data(data_dir: Path) -> None:
    if data_dir.is_dir() and any(data_dir.glob("*.json")):
        return

    repo_root = CACHE_REPO
    repo_root.mkdir(parents=True, exist_ok=True)
    if not (repo_root / ".git").is_dir():
        print(f"Cloning {REPO_URL} …", file=sys.stderr)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                REPO_URL,
                str(repo_root),
            ],
            check=True,
        )
    print("Checking out data/ …", file=sys.stderr)
    subprocess.run(
        ["git", "-C", str(repo_root), "sparse-checkout", "set", "data"], check=True
    )
    subprocess.run(["git", "-C", str(repo_root), "checkout"], check=True)
    target = repo_root / "data"
    if not data_dir.exists():
        data_dir.parent.mkdir(parents=True, exist_ok=True)
        data_dir.symlink_to(target, target_is_directory=True)


def cmd_build(args: argparse.Namespace) -> int:
    _ensure_data(args.data_dir)
    merge_path = None if args.no_merge else args.merge

    if (
        merge_path
        and merge_path.is_file()
        and merge_path.resolve() == args.output.resolve()
    ):
        backup = args.output.with_suffix(".json.bak")
        print(f"Backing up {args.output} → {backup}", file=sys.stderr)
        backup.write_bytes(args.output.read_bytes())

    export = build_export(args.data_dir, merge_path=merge_path)
    print(
        f"Official data: {summarize_body(build_official_body(args.data_dir))}",
        file=sys.stderr,
    )

    homebrew_count = len(export["async"]["HOMEBREW_2_STORAGE"]) - 1
    if homebrew_count:
        print(
            f"Preserved {homebrew_count} homebrew entr{'y' if homebrew_count == 1 else 'ies'}",
            file=sys.stderr,
        )

    write_json(args.output, export)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.output} ({size_mb:.1f} MB)", file=sys.stderr)
    return 0


def cmd_extract_homebrew(args: argparse.Namespace) -> int:
    export = extract_homebrew_export(args.from_file)
    count = len(export["async"]["HOMEBREW_2_STORAGE"])
    print(
        f"Extracted {count} homebrew entr{'y' if count == 1 else 'ies'}",
        file=sys.stderr,
    )
    write_json(args.output, export)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.output} ({size_mb:.1f} MB)", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Build merged official + homebrew export")
    build.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--merge", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--no-merge", action="store_true")
    build.set_defaults(func=cmd_build)

    extract = sub.add_parser(
        "extract-homebrew", help="Extract homebrew entries from a merged export"
    )
    extract.add_argument("--from", dest="from_file", type=Path, required=True)
    extract.add_argument("--output", type=Path, default=DEFAULT_HOMEBREW)
    extract.set_defaults(func=cmd_extract_homebrew)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
