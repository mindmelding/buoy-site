"""Screenshot a prospect's website at desktop and mobile widths.

Broken, expired, parked, and hijacked sites are the prospects worth the most
to us, so every failure path here still produces a diagnosis. The capture
never raises for a site problem: it writes what happened to capture.json and
lets the template turn that into a finding.

Usage:
    python capture.py --url example.com --slug example-1a2b3c4d
    python capture.py --input examples/prospect.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import prospect as prospect_lib

PACKAGE_DIR = prospect_lib.PACKAGE_DIR

DESKTOP_FILE = "desktop.png"
MOBILE_FILE = "mobile.png"
CAPTURE_FILE = "capture.json"
PROBE_FILE = PACKAGE_DIR / "probe.js"

USER_AGENT_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
USER_AGENT_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)

# Chromium network error codes, grouped into things we can say plainly on a page.
ERROR_KINDS = [
    ("dns", r"ERR_NAME_NOT_RESOLVED|ERR_NAME_RESOLUTION_FAILED"),
    ("tls", r"ERR_CERT_|ERR_SSL_|ERR_BAD_SSL|SSL_ERROR"),
    ("refused", r"ERR_CONNECTION_REFUSED|ERR_CONNECTION_CLOSED|ERR_CONNECTION_RESET"),
    ("unreachable", r"ERR_ADDRESS_UNREACHABLE|ERR_CONNECTION_FAILED|ERR_NETWORK_CHANGED"),
    ("timeout", r"ERR_CONNECTION_TIMED_OUT|ERR_TIMED_OUT|Timeout .* exceeded"),
    ("empty", r"ERR_EMPTY_RESPONSE|ERR_INVALID_RESPONSE"),
    ("blocked", r"ERR_BLOCKED_BY|ERR_ACCESS_DENIED"),
]

# Plain-language summaries. These are read by a shop owner, not an engineer.
KIND_SUMMARY = {
    "no_url": "We have no website on file for this business.",
    "dns": "The domain does not resolve. A browser cannot find a server to load.",
    "tls": "The security certificate is not valid, so browsers warn visitors away before the page loads.",
    "refused": "The server refused the connection. Nothing is answering on the domain.",
    "unreachable": "The server could not be reached.",
    "timeout": "The page did not finish loading within the time a visitor would wait.",
    "empty": "The server answered with nothing at all.",
    "blocked": "The request was blocked before the page could load.",
    "unknown": "The page did not load.",
}


def _launch_options(settings: dict[str, Any]) -> dict[str, Any]:
    """Launch settings, with escape hatches for locked-down build machines.

    Set capture.executable_path in config.json, or BUOY_CHROMIUM_PATH in the
    environment, to use a Chromium that is already on the machine instead of
    the one the playwright package downloads. Proxies come from config or from
    the usual HTTPS_PROXY and HTTP_PROXY variables.
    """
    options: dict[str, Any] = {
        "headless": True,
        "args": ["--disable-dev-shm-usage", "--hide-scrollbars"],
    }
    executable = (
        os.environ.get("BUOY_CHROMIUM_PATH")
        or str(settings.get("executable_path", "")).strip()
    )
    if executable:
        options["executable_path"] = executable
    proxy = (
        str(settings.get("proxy", "")).strip()
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    )
    if proxy:
        bypass = (
            str(settings.get("proxy_bypass", "")).strip()
            or os.environ.get("NO_PROXY")
            or os.environ.get("no_proxy")
            or "localhost,127.0.0.1"
        )
        options["proxy"] = {"server": proxy, "bypass": bypass}
    return options


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def classify_error(message: str) -> str:
    for kind, pattern in ERROR_KINDS:
        if re.search(pattern, message, re.IGNORECASE):
            return kind
    return "unknown"


# A failed resource load is often our own network rather than their site, so it
# is counted separately from a script that actually threw.
RESOURCE_NOISE = re.compile(
    r"failed to load resource|net::ERR_|ERR_BLOCKED|net::ERR_CERT|"
    r"loading (chunk|css chunk)|preload|favicon|ERR_CONNECTION",
    re.IGNORECASE,
)


def script_errors(messages: list[str]) -> list[str]:
    """Console errors that came from code running, not from a fetch failing."""
    return [m for m in messages if not RESOURCE_NOISE.search(m)]


def clean_error(message: str) -> str:
    """Strip the tooling prefix and trailing url so the page can quote it."""
    message = re.sub(r"^[A-Za-z]+\.[A-Za-z_]+:\s*", "", message.strip())
    message = re.sub(r"\s+at\s+\S+$", "", message)
    return message.strip()


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _blank(record: dict[str, Any], kind: str, message: str) -> dict[str, Any]:
    record["ok"] = False
    record["error_kind"] = kind
    record["error"] = clean_error(message)
    record["summary"] = KIND_SUMMARY.get(kind, KIND_SUMMARY["unknown"])
    return record


def probe_page(page) -> dict[str, Any]:
    """Read the signals a findings pass needs, from the page already on screen.

    Returns an empty dict rather than raising. A site that breaks the probe is
    still a site we want the screenshot of.
    """
    try:
        script = PROBE_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"  probe script unavailable: {exc}", file=sys.stderr)
        return {}
    try:
        signals = page.evaluate(script)
    except Exception as exc:  # noqa: BLE001 - a hostile page must not stop capture
        print(f"  probe failed: {str(exc).splitlines()[0]}", file=sys.stderr)
        return {}
    return signals if isinstance(signals, dict) else {}


def _shoot(page, path: Path, settings: dict[str, Any]) -> bool:
    """Write one screenshot. A site that breaks mid-render must not stop the run."""
    try:
        if settings.get("full_page"):
            height = page.evaluate(
                "() => Math.max(document.body ? document.body.scrollHeight : 0,"
                " document.documentElement ? document.documentElement.scrollHeight : 0)"
            )
            cap = int(settings.get("max_full_page_height", 4000))
            width = page.viewport_size["width"]
            clip = {
                "x": 0,
                "y": 0,
                "width": width,
                "height": max(1, min(int(height or cap), cap)),
            }
            page.screenshot(path=str(path), clip=clip)
        else:
            page.screenshot(path=str(path))
        return True
    except Exception as exc:  # noqa: BLE001 - any render failure is still a result
        print(f"  screenshot failed for {path.name}: {exc}", file=sys.stderr)
        return False


def _visit(browser, url: str, viewport: dict[str, int], user_agent: str,
           is_mobile: bool, settings: dict[str, Any], ignore_https: bool,
           shot_path: Path) -> dict[str, Any]:
    """Load a page in a fresh context and screenshot whatever comes back."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    result: dict[str, Any] = {"shot": False}
    context = browser.new_context(
        viewport=viewport,
        device_scale_factor=2,
        is_mobile=is_mobile,
        has_touch=is_mobile,
        user_agent=user_agent,
        ignore_https_errors=ignore_https,
        accept_downloads=False,
        locale="en-US",
    )
    timeout = int(settings.get("timeout_ms", 30000))
    context.set_default_timeout(timeout)
    page = context.new_page()
    # Hijacked and parked domains love a modal. Dismiss anything that blocks render.
    page.on("dialog", lambda dialog: dialog.dismiss())
    console_errors: list[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text[:300])
        if msg.type == "error" and len(console_errors) < 20
        else None,
    )
    page.on("pageerror", lambda exc: console_errors.append(str(exc)[:300])
            if len(console_errors) < 20 else None)

    started = time.monotonic()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except PlaywrightTimeout as exc:
        context.close()
        result.update(error=str(exc).splitlines()[0], error_kind="timeout")
        return result
    except PlaywrightError as exc:
        context.close()
        message = str(exc).splitlines()[0]
        result.update(error=message, error_kind=classify_error(message))
        return result

    # Give scripts and fonts a moment, but never let a chatty page hold the run.
    try:
        page.wait_for_load_state("networkidle", timeout=min(6000, timeout))
    except Exception:  # noqa: BLE001 - settling is best effort
        pass
    page.wait_for_timeout(int(settings.get("settle_ms", 1200)))

    result["load_ms"] = int((time.monotonic() - started) * 1000)
    result["status"] = response.status if response else None
    result["status_text"] = response.status_text if response else ""
    result["final_url"] = page.url
    try:
        result["title"] = (page.title() or "").strip()[:200]
    except Exception:  # noqa: BLE001
        result["title"] = ""
    try:
        result["has_viewport_meta"] = bool(
            page.evaluate("() => !!document.querySelector('meta[name=\"viewport\"]')")
        )
    except Exception:  # noqa: BLE001
        result["has_viewport_meta"] = None
    result["console_errors"] = console_errors
    result["signals"] = probe_page(page)

    shot_path.parent.mkdir(parents=True, exist_ok=True)
    result["shot"] = _shoot(page, shot_path, settings)
    context.close()
    return result


def capture_site(
    url: str,
    slug: str,
    *,
    config: dict[str, Any] | None = None,
    output_base: str | Path | None = None,
) -> dict[str, Any]:
    """Capture one site and return the diagnosis, writing shots and capture.json."""
    config = config or prospect_lib.load_config()
    settings = config.get("capture", {})
    out_dir = prospect_lib.output_dir_for(slug, output_base)
    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    url = prospect_lib.normalize_url(url)
    record: dict[str, Any] = {
        "slug": slug,
        "requested_url": url,
        "captured_at": _now_iso(),
        "ok": False,
        "desktop": None,
        "mobile": None,
        "tls_error": False,
        "scheme_downgraded": False,
        "redirected_offsite": False,
        "error_kind": "",
        "error": "",
        "summary": "",
    }

    if not url:
        _write(out_dir, _blank(record, "no_url", "no website on file"))
        return record

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _write(
            out_dir,
            _blank(record, "unknown", "playwright is not installed in this environment"),
        )
        return record

    desktop_view = {
        "width": int(settings.get("desktop_width", 1440)),
        "height": int(settings.get("desktop_height", 900)),
    }
    mobile_view = {
        "width": int(settings.get("mobile_width", 390)),
        "height": int(settings.get("mobile_height", 844)),
    }

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(**_launch_options(settings))
        except Exception as exc:  # noqa: BLE001 - a missing browser is a setup problem
            _write(out_dir, _blank(record, "unknown", f"could not start chromium: {exc}"))
            return record
        try:
            # Attempt order: as given, then trusting a bad certificate, then plain
            # http. Each fallback that works is itself a finding about the site.
            attempts = [(url, False), (url, True)]
            if url.startswith("https://"):
                attempts.append(("http://" + url[len("https://"):], True))

            desktop: dict[str, Any] = {}
            used_url = url
            for attempt_url, ignore_https in attempts:
                desktop = _visit(
                    browser, attempt_url, desktop_view, USER_AGENT_DESKTOP,
                    False, settings, ignore_https, shots_dir / DESKTOP_FILE,
                )
                if desktop.get("shot"):
                    used_url = attempt_url
                    record["tls_error"] = ignore_https and attempt_url == url
                    record["scheme_downgraded"] = attempt_url != url
                    break

            if not desktop.get("shot"):
                message = desktop.get("error", "the page did not load")
                kind = desktop.get("error_kind") or classify_error(message)
                _write(out_dir, _blank(record, kind, message))
                return record

            mobile = _visit(
                browser, used_url, mobile_view, USER_AGENT_MOBILE,
                True, settings, True, shots_dir / MOBILE_FILE,
            )
        finally:
            browser.close()

    record["ok"] = True
    record["used_url"] = used_url
    record["final_url"] = desktop.get("final_url", used_url)
    record["status"] = desktop.get("status")
    record["status_text"] = desktop.get("status_text", "")
    record["title"] = desktop.get("title", "")
    record["load_ms"] = desktop.get("load_ms")
    record["has_viewport_meta"] = desktop.get("has_viewport_meta")
    record["console_errors"] = desktop.get("console_errors", [])
    record["desktop"] = f"shots/{DESKTOP_FILE}" if desktop.get("shot") else None
    record["mobile"] = f"shots/{MOBILE_FILE}" if mobile.get("shot") else None
    record["mobile_error"] = mobile.get("error", "")

    signals = dict(desktop.get("signals") or {})
    mobile_signals = mobile.get("signals") or {}
    scroll = mobile_signals.get("scroll_width") or 0
    inner = mobile_signals.get("inner_width") or 0
    # A page wider than the phone viewport is the sideways-scroll complaint.
    signals["mobile_scroll_width"] = scroll
    signals["mobile_inner_width"] = inner
    signals["mobile_overflows"] = bool(scroll and inner and scroll > inner + 4)
    signals["load_ms"] = record.get("load_ms")
    all_errors = record.get("console_errors") or []
    real_errors = script_errors(all_errors)
    record["script_errors"] = real_errors
    signals["console_error_count"] = len(all_errors)
    signals["script_error_count"] = len(real_errors)
    # The width we asked for, so a finding can quote a real phone width rather
    # than the layout viewport a browser invents for a non-responsive page.
    signals["mobile_target_width"] = mobile_view["width"]
    record["signals"] = signals

    record["redirected_offsite"] = bool(
        _host(record["final_url"]) and _host(record["final_url"]) != _host(url)
    )
    status = record["status"] or 0
    if status >= 400:
        record["error_kind"] = "http_error"
        record["summary"] = (
            f"The site answers with a {status} error, so visitors land on an error page."
        )
    elif record["redirected_offsite"]:
        record["error_kind"] = "redirected"
        record["summary"] = (
            f"The domain now redirects to {_host(record['final_url'])}, which is not "
            "the address on your listings."
        )
    elif record["tls_error"]:
        record["error_kind"] = "tls"
        record["summary"] = (
            "The page loads only after bypassing a certificate warning, which most "
            "visitors will not do."
        )
    elif record["scheme_downgraded"]:
        record["error_kind"] = "no_https"
        record["summary"] = (
            "The site loads over plain http, so browsers mark it as not secure."
        )

    _write(out_dir, record)
    return record


def _write(out_dir: Path, record: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / CAPTURE_FILE).open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_capture(slug: str, output_base: str | Path | None = None) -> dict[str, Any] | None:
    path = prospect_lib.output_dir_for(slug, output_base) / CAPTURE_FILE
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screenshot a prospect's website.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="the prospect's website")
    source.add_argument("--input", help="a prospect JSON file to read url and slug from")
    parser.add_argument("--slug", help="page slug, required when using --url")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--output", help="output base directory, default dist/audit")
    parser.add_argument("--full-page", action="store_true", help="capture past the fold")
    args = parser.parse_args(argv)

    config = prospect_lib.load_config(args.config)
    if args.full_page:
        config["capture"]["full_page"] = True

    if args.input:
        records, _ = prospect_lib.load_prospects(args.input)
        targets = [
            prospect_lib.normalize_prospect(record, config=config)
            for record in records
        ]
    else:
        if not args.slug:
            parser.error("--slug is required with --url")
        if not prospect_lib.is_valid_slug(args.slug):
            parser.error("--slug must be in the business-name-<8 hex> form")
        targets = [{"url": args.url, "slug": args.slug, "business_name": args.slug}]

    failures = 0
    for target in targets:
        print(f"capturing {target['business_name']} ({target['url'] or 'no url'})")
        record = capture_site(
            target["url"], target["slug"], config=config, output_base=args.output
        )
        if record["ok"]:
            note = record.get("summary") or "loaded"
            print(f"  ok, status {record.get('status')}: {note}")
        else:
            failures += 1
            print(f"  no screenshot: {record['summary']}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
