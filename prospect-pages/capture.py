"""Playwright screenshot tool for Buoy prospect audit pages.

Takes a desktop and a mobile screenshot of a prospect's website and writes
them plus a capture.json metadata file into dist/audit/<slug>/shots/.

Broken, parked, hijacked, or unreachable sites are handled gracefully: a
navigation timeout is retried once, and a hard failure (DNS, refused
connection) produces a small branded diagnostic page that is screenshotted
instead, so every run yields real, meaningful PNGs.

Usage:
    python capture.py --input samples/healthy.json
    python capture.py --url example.com --slug my-slug
"""
import argparse
import datetime
import html
import json
import pathlib
import sys

from common import chdir_to_script_dir, load_config, dist_dir


def normalize_url(url):
    """Prepend https:// if the URL has no scheme."""
    url = (url or "").strip()
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url
    return url


def _diagnostic_html(url, reason, brand):
    """Return a small branded HTML page stating the site could not be reached."""
    ink = brand.get("ink", "#102f35")
    paper = brand.get("paper", "#fff8ec")
    orange = brand.get("orange", "#ff593d")
    safe_url = html.escape(url)
    safe_reason = html.escape(str(reason))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Site could not be reached</title>
<style>
  html,body{{margin:0;height:100%;font-family:"DM Mono",ui-monospace,monospace;background:{paper};color:{ink}}}
  .wrap{{box-sizing:border-box;min-height:100%;display:flex;flex-direction:column;justify-content:center;padding:48px;gap:18px}}
  .bar{{width:36px;height:3px;background:{orange}}}
  .eyebrow{{text-transform:uppercase;letter-spacing:.07em;font-size:13px}}
  h1{{font-size:28px;margin:0;line-height:1.2}}
  p{{font-size:16px;line-height:1.5;margin:0;max-width:60ch}}
  a{{color:{ink}}}
  .box{{border:2px solid {ink};box-shadow:4px 4px 0 {ink};padding:22px;background:#fff}}
</style>
</head>
<body>
  <div class="wrap">
    <div class="bar"></div>
    <div class="eyebrow">Buoy capture</div>
    <div class="box">
      <h1>This site could not be reached.</h1>
      <p>We tried to load <a href="{safe_url}">{safe_url}</a> and the connection did not complete.</p>
      <p>Reason: {safe_reason}</p>
      <p>For a customer trying to reach this business, that is the finding.</p>
    </div>
  </div>
</body>
</html>"""


def capture(url, slug, full_page=None, config=None):
    """Capture desktop and mobile screenshots for a URL. Returns capture metadata dict."""
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PWTimeoutError

    if config is None:
        config = load_config()
    cap_cfg = config.get("capture", {})
    if full_page is None:
        full_page = cap_cfg.get("full_page", False)
    timeout_ms = cap_cfg.get("timeout_ms", 30000)
    brand = config.get("brand", {})

    url = normalize_url(url)
    out_dir = dist_dir(slug) / "shots"
    out_dir.mkdir(parents=True, exist_ok=True)

    desktop_name = "desktop.png"
    mobile_name = "mobile.png"

    meta = {
        "url": url,
        "final_url": None,
        "http_status": None,
        "status": "ok",
        "error": None,
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "desktop": desktop_name,
        "mobile": mobile_name,
    }

    launch_kwargs = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    exe = cap_cfg.get("chromium_executable")
    if exe and pathlib.Path(exe).exists():
        launch_kwargs["executable_path"] = exe

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **launch_kwargs)
        try:
            for label, name, viewport, scale in (
                ("desktop", desktop_name,
                 {"width": cap_cfg.get("desktop_width", 1440), "height": cap_cfg.get("desktop_height", 900)}, 1),
                ("mobile", mobile_name,
                 {"width": cap_cfg.get("mobile_width", 390), "height": cap_cfg.get("mobile_height", 844)}, 2),
            ):
                # A screenshot tool should capture whatever the site serves,
                # even when its TLS certificate is expired, self-signed, or
                # otherwise invalid. That is itself a finding for the audit, so
                # ignore_https_errors defaults on rather than skipping the shot.
                context = browser.new_context(
                    viewport=viewport,
                    device_scale_factor=scale,
                    is_mobile=(label == "mobile"),
                    has_touch=(label == "mobile"),
                    ignore_https_errors=cap_cfg.get("ignore_https_errors", True),
                )
                page = context.new_page()
                reached = True
                try:
                    try:
                        response = page.goto(url, wait_until="load", timeout=timeout_ms)
                    except PWTimeoutError:
                        # Retry once with a lighter wait condition.
                        if meta["status"] == "ok":
                            meta["status"] = "partial"
                        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    if response is not None:
                        meta["http_status"] = response.status
                        if response.status >= 400 and meta["status"] == "ok":
                            meta["status"] = "partial"
                    meta["final_url"] = page.url
                except Exception as exc:  # noqa: BLE001 - DNS failure, refused, etc.
                    reached = False
                    meta["status"] = "unreachable"
                    meta["error"] = f"{type(exc).__name__}: {exc}".splitlines()[0]
                    # Cancel any pending navigation before injecting the diagnostic
                    # page, so set_content is not interrupted by the failed nav.
                    try:
                        page.goto("about:blank", wait_until="load", timeout=timeout_ms)
                    except Exception:  # noqa: BLE001
                        pass
                    page.set_content(_diagnostic_html(url, meta["error"], brand),
                                     wait_until="domcontentloaded")

                page.screenshot(path=str(out_dir / name), full_page=bool(full_page))
                context.close()
                _ = reached
        finally:
            browser.close()

    with open(dist_dir(slug) / "shots" / "capture.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.write("\n")

    print(f"[capture] {slug}: status={meta['status']} http={meta['http_status']} "
          f"url={meta['url']} -> {out_dir}/{desktop_name}, {mobile_name}")
    return meta


def main(argv=None):
    chdir_to_script_dir(__file__)
    parser = argparse.ArgumentParser(description="Capture desktop + mobile screenshots for a prospect site.")
    parser.add_argument("--input", help="Path to a prospect JSON file (with url and slug).")
    parser.add_argument("--url", help="URL to capture (used with --slug).")
    parser.add_argument("--slug", help="Slug for output directory (used with --url).")
    parser.add_argument("--full-page", action="store_true", help="Override config to capture the full page.")
    parser.add_argument("--config", default="config.json", help="Path to config.json.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    full_page = True if args.full_page else None

    if args.input:
        with open(args.input, "r", encoding="utf-8") as fh:
            prospect = json.load(fh)
        from common import ensure_slug
        url = prospect.get("url")
        slug = ensure_slug(prospect, args.input)
        if not url:
            print("[capture] ERROR: prospect JSON has no 'url' field.", file=sys.stderr)
            return 2
    elif args.url and args.slug:
        url = args.url
        slug = args.slug
    else:
        parser.error("Provide either --input <prospect.json> or both --url and --slug.")
        return 2

    try:
        capture(url, slug, full_page=full_page, config=config)
    except Exception as exc:  # noqa: BLE001 - truly unexpected errors only.
        print(f"[capture] UNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
