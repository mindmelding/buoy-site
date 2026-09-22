"""Generate a single prospect audit preview page from a prospect JSON file.

Loads config and a prospect, ensures a stable unguessable slug, optionally
runs the Playwright capture, and renders templates/audit.html.j2 into
dist/audit/<slug>/index.html.

Usage:
    python generate.py --input samples/healthy.json
    python generate.py --input samples/broken.json --no-capture
"""
import argparse
import json
import pathlib
import sys

from jinja2 import Environment, FileSystemLoader, select_autoescape

from common import chdir_to_script_dir, load_config, ensure_slug, dist_dir


def render_page(prospect, config, capture_status):
    """Render the audit page HTML string for a prospect."""
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("audit.html.j2")
    context = dict(prospect)
    context.setdefault("findings", [])
    context.update({
        "calendly_url": config.get("calendly_url"),
        "site_base_url": config.get("site_base_url"),
        "contact_email": config.get("contact_email"),
        "location": config.get("location"),
        "pageview_ping": config.get("pageview_ping", {"enabled": False, "endpoint": ""}),
        "capture_status": capture_status,
    })
    return template.render(**context)


def generate(input_path, config, no_capture=False, full_page=False):
    """Generate the page for one prospect. Returns (local_path, public_url)."""
    with open(input_path, "r", encoding="utf-8") as fh:
        prospect = json.load(fh)

    if not prospect.get("business_name"):
        raise ValueError(f"{input_path}: prospect is missing required field 'business_name'.")
    if not prospect.get("url"):
        raise ValueError(f"{input_path}: prospect is missing required field 'url'.")

    slug = ensure_slug(prospect, input_path)
    out_dir = dist_dir(slug)
    out_dir.mkdir(parents=True, exist_ok=True)

    capture_status = "ok"
    desktop_shot = out_dir / "shots" / "desktop.png"

    if not no_capture and not desktop_shot.exists():
        from capture import capture as run_capture
        run_capture(prospect["url"], slug, full_page=(True if full_page else None), config=config)

    cap_json = out_dir / "shots" / "capture.json"
    if cap_json.exists():
        try:
            with open(cap_json, "r", encoding="utf-8") as fh:
                capture_status = json.load(fh).get("status", "ok")
        except (json.JSONDecodeError, OSError):
            capture_status = "ok"

    html = render_page(prospect, config, capture_status)
    index_path = out_dir / "index.html"
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    public_url = f"{config.get('site_base_url', '').rstrip('/')}/audit/{slug}/"
    print(f"[generate] {slug}: wrote {index_path}")
    print(f"[generate] {slug}: public URL {public_url}")
    return index_path, public_url


def main(argv=None):
    chdir_to_script_dir(__file__)
    parser = argparse.ArgumentParser(description="Generate a prospect audit preview page.")
    parser.add_argument("--input", required=True, help="Path to a prospect JSON file.")
    parser.add_argument("--config", default="config.json", help="Path to config.json.")
    parser.add_argument("--no-capture", action="store_true", help="Skip screenshot capture.")
    parser.add_argument("--full-page", action="store_true", help="Capture the full page.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    try:
        generate(args.input, config, no_capture=args.no_capture, full_page=args.full_page)
    except Exception as exc:  # noqa: BLE001
        print(f"[generate] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
