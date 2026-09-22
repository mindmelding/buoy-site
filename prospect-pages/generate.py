"""Render one prospect's audit preview page.

Usage:
    python generate.py --input examples/prospect.json
    python generate.py --input examples/prospect.json --capture
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

import capture as capture_lib
import prospect as prospect_lib

TEMPLATE_DIR = prospect_lib.PACKAGE_DIR / "templates"
TEMPLATE_NAME = "audit.html.j2"
SLOW_LOAD_MS = 4000


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml", "j2"], default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def tracking_src(config: dict[str, Any], slug: str) -> str:
    """Build the pageview pixel URL. Off unless config turns it on."""
    tracking = config.get("view_tracking", {})
    endpoint = str(tracking.get("endpoint", "")).strip()
    if not tracking.get("enabled") or not endpoint:
        return ""
    params = {str(tracking.get("slug_param", "slug")): slug}
    for key, value in (tracking.get("extra_params") or {}).items():
        params[str(key)] = str(value)
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(params)}"


def build_flags(cap: dict[str, Any] | None) -> list[dict[str, str]]:
    """Turn the capture diagnosis into short technical notes for the page."""
    if not cap or not cap.get("ok"):
        return []

    flags: list[dict[str, str]] = []
    status = cap.get("status") or 0
    if status >= 400:
        flags.append({
            "label": f"HTTP {status}",
            "detail": "the server answers with an error rather than your site",
        })
    if cap.get("redirected_offsite"):
        flags.append({
            "label": "Redirect",
            "detail": f"the domain sends visitors to {cap.get('final_url', '')}",
        })
    if cap.get("tls_error"):
        flags.append({
            "label": "Certificate warning",
            "detail": "browsers show a security warning before the page opens",
        })
    if cap.get("scheme_downgraded"):
        flags.append({
            "label": "No https",
            "detail": "the site loads over plain http and is marked not secure",
        })
    if cap.get("has_viewport_meta") is False:
        flags.append({
            "label": "Not built for phones",
            "detail": "the page has no mobile layout, so phone visitors get the desktop version shrunk down",
        })
    load_ms = cap.get("load_ms") or 0
    if load_ms > SLOW_LOAD_MS:
        flags.append({
            "label": "Slow load",
            "detail": f"the page took {load_ms / 1000:.1f} seconds to become usable",
        })
    errors = cap.get("console_errors") or []
    if errors:
        count = len(errors)
        flags.append({
            "label": "Broken scripts",
            "detail": f"{count} script error{'s' if count != 1 else ''} fire on load",
        })
    if not cap.get("mobile"):
        flags.append({
            "label": "No phone screenshot",
            "detail": "the site did not finish rendering at phone width",
        })
    return flags


def _reviewed_on(cap: dict[str, Any] | None) -> str:
    stamp = (cap or {}).get("captured_at")
    if stamp:
        try:
            return datetime.fromisoformat(stamp).strftime("%B %-d, %Y")
        except ValueError:
            pass
    return date.today().strftime("%B %-d, %Y")


def render_page(
    record: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    output_base: str | Path | None = None,
    run_capture: bool = False,
    assign_slug: bool = True,
) -> dict[str, Any]:
    """Normalize one record, render its page, and return what was written."""
    config = config or prospect_lib.load_config()
    p = prospect_lib.normalize_prospect(record, config=config, assign_slug=assign_slug)
    slug = p["slug"]
    out_dir = prospect_lib.output_dir_for(slug, output_base)
    out_dir.mkdir(parents=True, exist_ok=True)

    if run_capture:
        cap = capture_lib.capture_site(
            p["url"], slug, config=config, output_base=output_base
        )
    else:
        cap = capture_lib.load_capture(slug, output_base)

    template = _environment().get_template(TEMPLATE_NAME)
    html = template.render(
        p=p,
        cfg=config,
        brand=config["brand"],
        cap=cap,
        flags=build_flags(cap),
        reviewed_on=_reviewed_on(cap),
        tracking_src=tracking_src(config, slug),
        mail_subject=quote(f"Audit preview for {p['business_name']}"),
    )

    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    return {
        "slug": slug,
        "business_name": p["business_name"],
        "url": p["url"],
        "page_url": p["page_url"],
        "path": index_path,
        "capture_ok": bool(cap and cap.get("ok")),
        "capture_summary": (cap or {}).get("summary", ""),
        "unknown_fields": p.get("_unknown_fields", []),
        "findings": len(p["findings"]),
        "top_service": p["top_service"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a prospect audit preview page.")
    parser.add_argument("--input", required=True, help="path to a prospect JSON file")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--output", help="output base directory, default dist/audit")
    parser.add_argument(
        "--capture",
        action="store_true",
        help="take fresh screenshots before rendering",
    )
    parser.add_argument(
        "--no-assign-slug",
        action="store_true",
        help="fail instead of inventing a slug when the record has none",
    )
    parser.add_argument(
        "--write-slug",
        action="store_true",
        help="save any newly assigned slug back into the input file",
    )
    parser.add_argument("--clean", action="store_true", help="empty the page directory first")
    args = parser.parse_args(argv)

    config = prospect_lib.load_config(args.config)
    records, shape = prospect_lib.load_prospects(args.input)
    if len(records) != 1:
        print(
            f"{args.input} holds {len(records)} prospects. Use batch.py for more than one.",
            flush=True,
        )
        return 2

    record = records[0]
    if args.clean:
        slug = str(record.get("slug", "")).strip()
        if slug:
            shutil.rmtree(prospect_lib.output_dir_for(slug, args.output), ignore_errors=True)

    result = render_page(
        record,
        config=config,
        output_base=args.output,
        run_capture=args.capture,
        assign_slug=not args.no_assign_slug,
    )

    if args.write_slug and not str(record.get("slug", "")).strip():
        record["slug"] = result["slug"]
        prospect_lib.save_prospects(args.input, records, shape)
        print(f"wrote slug {result['slug']} back to {args.input}")

    for field in result["unknown_fields"]:
        print(f"note: ignoring unrecognized field {field!r}")
    if not result["capture_ok"]:
        print(f"note: no screenshots for this page. {result['capture_summary']}")

    print(f"wrote {result['path']}")
    print(f"page url {result['page_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
