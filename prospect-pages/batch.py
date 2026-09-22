"""Build audit preview pages for a list of prospects and write the link sheet.

Usage:
    python batch.py --input examples/prospects.json
    python batch.py --input examples/prospects.json --skip-capture
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import generate as generate_lib
import prospect as prospect_lib

CSV_FIELDS = [
    "business_name",
    "url",
    "page_url",
    "slug",
    "findings",
    "top_service",
    "capture_ok",
    "capture_summary",
    "generated_at",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate audit preview pages for a list of prospects."
    )
    parser.add_argument("--input", required=True, help="JSON file holding a list of prospects")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--output", help="output base directory, default dist/audit")
    parser.add_argument("--csv", help="where to write the link sheet, default <output>/pages.csv")
    parser.add_argument(
        "--skip-capture",
        action="store_true",
        help="reuse screenshots already on disk instead of taking fresh ones",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="build just this slug or business name, repeatable",
    )
    parser.add_argument(
        "--no-write-slugs",
        action="store_true",
        help="do not save newly assigned slugs back to the input file",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove each page directory before rebuilding it",
    )
    args = parser.parse_args(argv)

    config = prospect_lib.load_config(args.config)
    records, shape = prospect_lib.load_prospects(args.input)
    if not records:
        print(f"{args.input} holds no prospects")
        return 2

    wanted = {value.strip().lower() for value in args.only}
    output_base = Path(args.output) if args.output else prospect_lib.DEFAULT_OUTPUT_DIR
    csv_path = Path(args.csv) if args.csv else output_base / "pages.csv"
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    failures = []
    slugs_assigned = 0

    for index, record in enumerate(records, start=1):
        name = str(record.get("business_name", "")).strip()
        slug_before = str(record.get("slug", "")).strip()
        if wanted and name.lower() not in wanted and slug_before.lower() not in wanted:
            continue

        label = name or f"record {index}"
        print(f"[{index}/{len(records)}] {label}")
        try:
            if args.clean and slug_before:
                shutil.rmtree(
                    prospect_lib.output_dir_for(slug_before, output_base),
                    ignore_errors=True,
                )
            result = generate_lib.render_page(
                record,
                config=config,
                output_base=output_base,
                run_capture=not args.skip_capture,
            )
        except Exception as exc:  # noqa: BLE001 - one bad record must not stop the batch
            print(f"  failed: {exc}", file=sys.stderr)
            failures.append((label, str(exc)))
            continue

        if not slug_before:
            record["slug"] = result["slug"]
            slugs_assigned += 1
        for field in result["unknown_fields"]:
            print(f"  note: ignoring unrecognized field {field!r}")
        if not result["capture_ok"]:
            print(f"  no screenshots. {result['capture_summary']}")
        print(f"  {result['page_url']}")

        rows.append({
            "business_name": result["business_name"],
            "url": result["url"],
            "page_url": result["page_url"],
            "slug": result["slug"],
            "findings": result["findings"],
            "top_service": result["top_service"],
            "capture_ok": "yes" if result["capture_ok"] else "no",
            "capture_summary": result["capture_summary"],
            "generated_at": generated_at,
        })

    if slugs_assigned and not args.no_write_slugs:
        prospect_lib.save_prospects(args.input, records, shape)
        print(f"saved {slugs_assigned} new slug(s) back to {args.input}")

    if rows:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {len(rows)} page(s) and the link sheet at {csv_path}")

    if failures:
        print(f"\n{len(failures)} record(s) failed:", file=sys.stderr)
        for label, message in failures:
            print(f"  {label}: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
