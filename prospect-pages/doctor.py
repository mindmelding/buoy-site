"""Run the pipeline against real websites and write a report to send back.

This exists because the generator was built and tested without network access to
any real prospect site. Run it on a machine that can reach the open internet,
then send the report so the rules can be checked against reality.

Usage:
    python doctor.py --urls https://a.example https://b.example
    python doctor.py --input prospects.json --limit 5
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import capture as capture_lib
import generate as generate_lib
import prospect as prospect_lib
import research as research_lib

REPORT_NAME = "doctor-report.json"
TEXT_SAMPLE = 400


def _versions() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        import playwright  # noqa: PLC0415

        info["playwright"] = getattr(playwright, "__version__", "unknown")
    except ImportError:
        info["playwright"] = "not installed"
    try:
        import jinja2  # noqa: PLC0415

        info["jinja2"] = jinja2.__version__
    except ImportError:
        info["jinja2"] = "not installed"
    return info


def _shot_facts(slug: str, base: str | Path | None) -> dict[str, Any]:
    """File sizes tell us whether a screenshot is real or a blank frame."""
    shots = prospect_lib.output_dir_for(slug, base) / "shots"
    facts: dict[str, Any] = {}
    for name in ("desktop.png", "mobile.png"):
        path = shots / name
        facts[name] = path.stat().st_size if path.exists() else None
    return facts


def inspect(url: str, name: str, config: dict, base: str | Path | None) -> dict[str, Any]:
    """Capture one real site and report everything worth checking."""
    record = prospect_lib.normalize_prospect(
        {"business_name": name, "url": url}, config=config
    )
    slug = record["slug"]
    cap = capture_lib.capture_site(url, slug, config=config, output_base=base)
    signals = cap.get("signals") or {}
    drafts = research_lib.draft_findings(cap, record, max_findings=8)

    return {
        "name": name,
        "requested_url": url,
        "final_url": cap.get("final_url"),
        "ok": cap.get("ok"),
        "status": cap.get("status"),
        "error_kind": cap.get("error_kind"),
        "error": cap.get("error"),
        "summary": cap.get("summary"),
        "challenged": cap.get("challenged", False),
        "challenge_hits": cap.get("challenge_hits", []),
        "challenge_title": (signals.get("challenge") or {}).get("title", ""),
        "tls_error": cap.get("tls_error"),
        "scheme_downgraded": cap.get("scheme_downgraded"),
        "redirected_offsite": cap.get("redirected_offsite"),
        "load_ms": cap.get("load_ms"),
        "server": cap.get("server", ""),
        "challenge_waited_ms": cap.get("challenge_waited_ms"),
        "incomplete_render": cap.get("incomplete_render", False),
        "failed_assets": (cap.get("failed_assets") or []) + (cap.get("mobile_failed_assets") or []),
        "page_title": cap.get("title", ""),
        "screenshot_bytes": _shot_facts(slug, base),
        "signals": {k: v for k, v in signals.items() if k != "challenge"},
        "script_errors": (cap.get("script_errors") or [])[:5],
        "other_script_errors": (cap.get("other_script_errors") or [])[:5],
        "console_errors": (cap.get("console_errors") or [])[:5],
        "drafted": [
            {"rule": d["rule"], "confidence": d["confidence"],
             "title": d["title"], "evidence": d["evidence"]}
            for d in drafts
        ],
        "flags": generate_lib.build_flags(cap),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the pipeline against real websites and write a report."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--urls", nargs="+", help="websites to test")
    source.add_argument("--input", help="a prospect JSON file to pull urls from")
    parser.add_argument("--limit", type=int, default=8, help="how many to test")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--output", help="capture directory, default dist/audit")
    parser.add_argument("--report", help=f"where to write the report, default {REPORT_NAME}")
    args = parser.parse_args(argv)

    config = prospect_lib.load_config(args.config)

    targets: list[tuple[str, str]] = []
    if args.urls:
        targets = [(url, f"Test Site {i}") for i, url in enumerate(args.urls, start=1)]
    else:
        records, _ = prospect_lib.load_prospects(args.input)
        for record in records:
            url = str(record.get("url", "")).strip()
            if url:
                targets.append((url, str(record.get("business_name", "Unnamed"))))
    targets = targets[: args.limit]
    if not targets:
        print("no urls to test")
        return 2

    results = []
    for index, (url, name) in enumerate(targets, start=1):
        print(f"[{index}/{len(targets)}] {name} {url}")
        try:
            result = inspect(url, name, config, args.output)
        except Exception as exc:  # noqa: BLE001 - a crash here is itself the finding
            print(f"  CRASHED: {exc}")
            results.append({"name": name, "requested_url": url, "crashed": repr(exc)})
            continue

        if result["challenged"]:
            print(f"  bot protection: {', '.join(result['challenge_hits'])}")
        elif result["error_kind"] in capture_lib.OUR_SIDE_KINDS:
            print(f"  failed on our side, not the site's fault: {result['error']}")
        elif not result["ok"]:
            print(f"  did not load: {result['error_kind']} {result['error']}")
        else:
            shots = result["screenshot_bytes"]
            print(
                f"  loaded, status {result['status']}, {result['load_ms']}ms, "
                f"desktop {shots.get('desktop.png')} bytes, "
                f"{len(result['drafted'])} draft finding(s)"
            )
            if result["incomplete_render"]:
                print("  WARNING scripts or styles did not load, so the screenshot may not "
                      f"be what a customer sees: {result['failed_assets'][0]}")
        results.append(result)

    report = {"environment": _versions(), "results": results}
    path = Path(args.report) if args.report else Path(REPORT_NAME)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    loaded = sum(1 for r in results if r.get("ok") and not r.get("challenged"))
    blocked = sum(1 for r in results if r.get("challenged"))
    ours = sum(1 for r in results if r.get("error_kind") in capture_lib.OUR_SIDE_KINDS)
    failed = len(results) - loaded - blocked - ours
    print(f"\n{loaded} loaded, {blocked} bot-blocked, {ours} failed on our side, {failed} failed")
    tls = sum(1 for r in results if r.get("tls_error") or r.get("error_kind") == "tls")
    if len(results) >= 3 and tls == len(results):
        print(
            "Every site came back with a certificate error. That is almost always a "
            "proxy re-signing TLS on this machine, not the sites. Point BUOY_TRUST_CA "
            "at the proxy's CA bundle and run again."
        )
    print(f"report written to {path}")
    print("Send that file back. Check the screenshots yourself before trusting any of it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
