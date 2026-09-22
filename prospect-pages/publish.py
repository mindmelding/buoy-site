"""Publish generated audit pages to the repository root so GitHub Pages serves them.

The live site is served by GitHub Pages from the repo root (custom domain
buoydesk.com, see CNAME). To make a page live at buoydesk.com/audit/<slug>/,
its generated dist/audit/<slug>/ folder must be copied to <repo_root>/audit/<slug>/.

Privacy tradeoff, stated plainly: pages copied to the repo root are publicly
reachable by anyone who has the exact unguessable URL, and they are committed
to the repository (so the HTML and screenshots live in git history). Only
publish a prospect you intend to host, and never add /audit/ to sitemap.xml.

Usage:
    python publish.py            # copy every slug under dist/audit into ../audit
    python publish.py --dry-run  # print what would be copied, change nothing
"""
import argparse
import pathlib
import shutil

from common import chdir_to_script_dir, load_config

SKIP_NAMES = {"prospects.csv", "prospects.resolved.json"}


def main(argv=None):
    chdir_to_script_dir(__file__)
    parser = argparse.ArgumentParser(description="Copy dist/audit slug folders to the repo root /audit.")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be copied.")
    parser.add_argument("--config", default="config.json", help="Path to config.json.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    site_base = config.get("site_base_url", "").rstrip("/")

    src_root = pathlib.Path("dist/audit")
    dest_root = pathlib.Path("../audit")

    if not src_root.exists():
        print(f"[publish] Nothing to publish: {src_root} does not exist.")
        return 0

    slug_dirs = [d for d in sorted(src_root.iterdir())
                 if d.is_dir() and d.name not in SKIP_NAMES]
    if not slug_dirs:
        print("[publish] No slug directories found under dist/audit.")
        return 0

    if not args.dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)

    for slug_dir in slug_dirs:
        slug = slug_dir.name
        dest = dest_root / slug
        public_url = f"{site_base}/audit/{slug}/"
        if args.dry_run:
            print(f"[publish] would copy {slug_dir} -> {dest}  ({public_url})")
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(slug_dir, dest)
        print(f"[publish] copied {slug_dir} -> {dest}")
        print(f"[publish] live at {public_url}")

    if args.dry_run:
        print("[publish] dry run complete, nothing was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
