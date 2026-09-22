"""Generate audit preview pages for a batch of prospects.

Reads a JSON array of prospect objects, ensures a stable slug for each,
captures and generates each page, and writes a summary CSV.

Usage:
    python batch.py --input samples/prospects.example.json
    python batch.py --input prospects.json --no-capture
"""
import argparse
import csv
import json
import pathlib
import sys

from common import chdir_to_script_dir, load_config, ensure_slug
from generate import generate


def main(argv=None):
    chdir_to_script_dir(__file__)
    parser = argparse.ArgumentParser(description="Batch generate prospect audit pages.")
    parser.add_argument("--input", required=True, help="Path to a JSON array of prospects.")
    parser.add_argument("--config", default="config.json", help="Path to config.json.")
    parser.add_argument("--no-capture", action="store_true", help="Skip screenshot capture.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    site_base = config.get("site_base_url", "").rstrip("/")

    with open(args.input, "r", encoding="utf-8") as fh:
        prospects = json.load(fh)
    if not isinstance(prospects, list):
        print("[batch] ERROR: input must be a JSON array of prospect objects.", file=sys.stderr)
        return 2

    dist_audit = pathlib.Path("dist/audit")
    dist_audit.mkdir(parents=True, exist_ok=True)

    # Ensure slugs for the whole list first, then persist the resolved list.
    for prospect in prospects:
        ensure_slug(prospect)
    resolved_path = dist_audit / "prospects.resolved.json"
    with open(resolved_path, "w", encoding="utf-8") as fh:
        json.dump(prospects, fh, indent=2)
        fh.write("\n")

    rows = []
    for prospect in prospects:
        slug = prospect["slug"]
        # Write each prospect to its own temp JSON so generate/capture can read it
        # and persist any slug (already present here).
        tmp_path = dist_audit / f"_prospect-{slug}.json"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(prospect, fh, indent=2)

        capture_status = "ok"
        try:
            generate(str(tmp_path), config, no_capture=args.no_capture)
        except Exception as exc:  # noqa: BLE001
            print(f"[batch] ERROR generating {slug}: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            cap_json = dist_audit / slug / "shots" / "capture.json"
            if cap_json.exists():
                try:
                    with open(cap_json, "r", encoding="utf-8") as fh:
                        capture_status = json.load(fh).get("status", "ok")
                except (json.JSONDecodeError, OSError):
                    pass
            tmp_path.unlink(missing_ok=True)

        page_url = f"{site_base}/audit/{slug}/"
        rows.append({
            "business_name": prospect.get("business_name", ""),
            "url": prospect.get("url", ""),
            "slug": slug,
            "page_url": page_url,
            "capture_status": capture_status,
        })

    csv_path = dist_audit / "prospects.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["business_name", "url", "slug", "page_url", "capture_status"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n[batch] Summary")
    print(f"{'business_name':<28} {'capture':<12} page_url")
    print("-" * 78)
    for row in rows:
        print(f"{row['business_name']:<28} {row['capture_status']:<12} {row['page_url']}")
    print(f"\n[batch] Wrote {csv_path} ({len(rows)} rows) and {resolved_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
