"""Copy built pages into the GitHub Pages site so they serve at /audit/<slug>/.

Only index.html and the shots are copied. capture.json stays behind because it
holds our own notes, and pages.csv stays behind because it lists every prospect
in the batch. Neither belongs on a public host.

Usage:
    python publish.py --dry-run
    python publish.py
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

import prospect as prospect_lib

SITE_ROOT = prospect_lib.PACKAGE_DIR.parent
PUBLIC_FILES = ("index.html",)
PUBLIC_DIRS = ("shots",)


def _slug_dirs(source: Path) -> list[Path]:
    if not source.exists():
        return []
    return sorted(
        path
        for path in source.iterdir()
        if path.is_dir() and prospect_lib.is_valid_slug(path.name)
    )


def _copy_slug(slug_dir: Path, target: Path, dry_run: bool) -> list[str]:
    actions = []
    for name in PUBLIC_FILES:
        source_file = slug_dir / name
        if not source_file.exists():
            continue
        destination = target / name
        if destination.exists() and filecmp.cmp(source_file, destination, shallow=False):
            continue
        actions.append(f"  {name}")
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)

    for name in PUBLIC_DIRS:
        source_dir = slug_dir / name
        if not source_dir.is_dir():
            continue
        for shot in sorted(source_dir.iterdir()):
            if not shot.is_file():
                continue
            destination = target / name / shot.name
            if destination.exists() and filecmp.cmp(shot, destination, shallow=False):
                continue
            actions.append(f"  {name}/{shot.name}")
            if not dry_run:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(shot, destination)
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy built audit pages into the published site directory."
    )
    parser.add_argument("--source", help="build directory, default dist/audit")
    parser.add_argument(
        "--target",
        help="published directory, default the audit folder at the site root",
    )
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="list changes only")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete published slugs that no longer exist in the build directory",
    )
    args = parser.parse_args(argv)

    config = prospect_lib.load_config(args.config)
    source = Path(args.source) if args.source else prospect_lib.DEFAULT_OUTPUT_DIR
    target_root = (
        Path(args.target)
        if args.target
        else SITE_ROOT / config["site"]["audit_path"].strip("/")
    )

    slug_dirs = _slug_dirs(source)
    if not slug_dirs:
        print(f"no built pages found in {source}")
        return 2

    changed = 0
    for slug_dir in slug_dirs:
        actions = _copy_slug(slug_dir, target_root / slug_dir.name, args.dry_run)
        if actions:
            changed += 1
            print(f"{slug_dir.name}")
            for action in actions:
                print(action)

    if args.prune and target_root.exists():
        live = {slug_dir.name for slug_dir in slug_dirs}
        for published in sorted(target_root.iterdir()):
            if published.is_dir() and published.name not in live:
                print(f"removing {published.name}")
                if not args.dry_run:
                    shutil.rmtree(published)

    verb = "would update" if args.dry_run else "updated"
    print(f"\n{verb} {changed} of {len(slug_dirs)} page(s) under {target_root}")
    if not args.dry_run and changed:
        print("commit the audit directory to publish these pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
