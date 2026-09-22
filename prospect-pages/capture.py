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
import base64
import functools
import hashlib
import json
import os
import re
import signal
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
    "stalled": (
        "The page stopped responding while we were reading it, so we could not "
        "finish checking what a customer sees."
    ),
    "our_network": (
        "Our connection to the site failed on our side, so we could not check "
        "what a customer sees."
    ),
    "challenged": (
        "A bot-protection screen answered instead of the site, so we could not see "
        "what a customer sees from here."
    ),
}


def _der_element(data: bytes, pos: int) -> tuple[int, int, int]:
    """Tag, start of content, and end of one DER element at pos."""
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    return tag, pos, pos + length


def _spki_from_der(cert: bytes) -> bytes:
    """The raw SubjectPublicKeyInfo of a DER certificate.

    Certificate is a SEQUENCE whose first element, tbsCertificate, holds an
    optional [0] version, then serial, signature, issuer, validity, subject,
    and subjectPublicKeyInfo, in that order.
    """
    _, body, _ = _der_element(cert, 0)
    _, pos, _ = _der_element(cert, body)
    tag, _, end = _der_element(cert, pos)
    if tag == 0xA0:
        pos = end
    for _ in range(5):
        pos = _der_element(cert, pos)[2]
    tag, _, end = _der_element(cert, pos)
    if tag != 0x30:
        raise ValueError("no SubjectPublicKeyInfo where one belongs")
    return cert[pos:end]


@functools.lru_cache(maxsize=8)
def spki_pins(pem_path: str) -> tuple[str, ...]:
    """Base64 SHA-256 of each certificate's public key in a PEM file.

    Chromium does not read the system trust store on every machine, so behind a
    proxy that re-signs TLS every site would fail as a bad certificate and get a
    finding it did not earn. Pinning the proxy's CA fixes that without turning
    off certificate checks for the sites themselves.
    """
    try:
        text = Path(pem_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"  trust_ca unreadable, ignoring it: {exc}", file=sys.stderr)
        return ()
    pins = []
    for block in re.findall(
        r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", text, re.DOTALL
    ):
        try:
            spki = _spki_from_der(base64.b64decode("".join(block.split())))
        except (ValueError, IndexError):
            continue
        pins.append(base64.b64encode(hashlib.sha256(spki).digest()).decode())
    return tuple(pins)


def _launch_options(settings: dict[str, Any]) -> dict[str, Any]:
    """Launch settings, with escape hatches for locked-down build machines.

    Set capture.executable_path in config.json, or BUOY_CHROMIUM_PATH in the
    environment, to use a Chromium that is already on the machine instead of
    the one the playwright package downloads. Proxies come from config or from
    the usual HTTPS_PROXY and HTTP_PROXY variables. Behind a proxy that
    re-signs TLS, point capture.trust_ca or BUOY_TRUST_CA at its CA file.
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
    trust_ca = (
        os.environ.get("BUOY_TRUST_CA") or str(settings.get("trust_ca", "")).strip()
    )
    if trust_ca:
        pins = spki_pins(trust_ca)
        if pins:
            options["args"].append("--ignore-certificate-errors-spki-list=" + ",".join(pins))
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
# is counted separately from a script that actually threw. The rest is browser
# chatter seen on real sites that breaks nothing a visitor would notice:
# autoplay refusals, permissions-policy notices on embeds, stylesheet MIME
# warnings, and frameworks logging their own internals through console.error.
RESOURCE_NOISE = re.compile(
    r"failed to load resource|net::ERR_|ERR_BLOCKED|net::ERR_CERT|"
    r"loading (chunk|css chunk)|preload|favicon|ERR_CONNECTION|"
    r"permissions policy|play\(\) failed|no supported sources|"
    r"refused to apply style|suspense rendered fallback|"
    r"request failed with status code 40[13]|third-party cookie|"
    r"content security policy|mixed content|"
    # A script or JSON request that got an HTML page back. That is their 404
    # page or our proxy's error page, and from here the two look the same.
    r"unexpected token '<'",
    re.IGNORECASE,
)


STACK_URL = re.compile(r"https?://[^\s)/:]+")


def _page_error(exc) -> dict[str, str]:
    """An uncaught exception and the host of the script that threw it."""
    message = (getattr(exc, "message", "") or str(exc))[:300]
    match = STACK_URL.search(getattr(exc, "stack", "") or "")
    return {"message": message, "origin": _host(match.group(0)) if match else ""}


def own_errors(errors: list[dict[str, str]], site_url: str) -> tuple[list[str], list[str]]:
    """Split uncaught exceptions into the site's own and everything else.

    The finding says scripts on the prospect's site are failing, so it only
    counts errors thrown by a script served from their own domain or its
    subdomains. A review widget from someone else's server is not their bug,
    and an error with no script URL in its stack, a bare syntax error for
    one, looks the same from here whether their file is broken or our
    connection cut it short.
    """
    site = _host(site_url)
    mine, others = [], []
    for error in errors:
        origin = error.get("origin", "")
        own = bool(site and origin) and (
            origin == site or origin.endswith("." + site) or site.endswith("." + origin)
        )
        (mine if own else others).append(error.get("message", ""))
    return script_errors(mine), script_errors(others)


def script_errors(messages: list[str]) -> list[str]:
    """Uncaught exceptions that came from code running, not from a fetch failing.

    Only exceptions that escaped to the page count. console.error is a logging
    call and vendor widgets use it for routine chatter.
    """
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
    # A challenge page that clears itself navigates while we read it. Wait for
    # the new document and read that instead of returning nothing.
    for attempt in range(3):
        try:
            signals = page.evaluate(script)
            break
        except Exception as exc:  # noqa: BLE001 - a hostile page must not stop capture
            message = str(exc).splitlines()[0]
            if "context was destroyed" in message and attempt < 2:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    page.wait_for_timeout(1000)
                except Exception:  # noqa: BLE001
                    pass
                continue
            print(f"  probe failed: {message}", file=sys.stderr)
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


# Measured to the load event from the capture machine. Real small-business
# homepages came in between 0.5 and 6.5 seconds on a fast line, so 5 seconds
# flags the heavy ones without flagging a normal page on a slow proxy.
SLOW_LOAD_MS = 5000

RETRY_STATUSES = {502, 503, 504}
# Statuses a proxy between us and the site answers with on its own behalf:
# gateway errors, 407 for its own auth, and 405 from relays that only tunnel
# https and refuse the plain-http fallback. A real origin or CDN names itself
# in a Server header. Without one, these say nothing about the prospect.
PROXY_STATUSES = RETRY_STATUSES | {405, 407}
DEFAULT_SITE_TIMEOUT_MS = 150000
# Failures on our end. Nothing about the prospect can be said from them.
OUR_SIDE_KINDS = {"our_network", "stalled"}
# https failures where trying plain http can tell us something.
HTTP_FALLBACK_KINDS = {"tls", "refused", "unreachable", "empty"}

NAV_LOAD_JS = """() => {
  const nav = performance.getEntriesByType("navigation")[0];
  if (!nav) return 0;
  return Math.round(nav.loadEventEnd || nav.domContentLoadedEventEnd || 0);
}"""


def _settle(page, settings: dict[str, Any], timeout: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=min(6000, timeout))
    except Exception:  # noqa: BLE001 - settling is best effort
        pass
    page.wait_for_timeout(int(settings.get("settle_ms", 1200)))


def _nav_load_ms(page) -> int:
    """Time to the load event as the browser measured it.

    Wall time around the visit includes our own settle and network-idle waits,
    which would put every site over the slow threshold.
    """
    try:
        return int(page.evaluate(NAV_LOAD_JS) or 0)
    except Exception:  # noqa: BLE001
        return 0


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
    page_errors: list[dict[str, str]] = []
    page.on("pageerror", lambda exc: page_errors.append(_page_error(exc))
            if len(page_errors) < 20 else None)

    # The last document the main frame loaded, so a page that reloads itself
    # past an interstitial reports the real page's status, not the wall's.
    documents: list[Any] = []
    page.on(
        "response",
        lambda resp: documents.append(resp)
        if resp.request.resource_type == "document" and resp.frame == page.main_frame
        else None,
    )

    # Scripts and stylesheets that never arrived. Without its CSS a page looks
    # broken in a screenshot. Without a library, the site's own code throws
    # "owlCarousel is not a function" and an unstarted carousel sprawls past
    # the phone width. Real sites did both on one run and neither on the next,
    # so when it happens here it is usually our connection.
    failed_assets: list[str] = []

    def _asset_failed(request, reason: str) -> None:
        # Only the site's files. Scripts probe chrome-extension:// urls to spot
        # installed extensions, and Chromium blocks those by design.
        if not request.url.startswith(("http://", "https://")):
            return
        if request.resource_type in ("stylesheet", "script") and len(failed_assets) < 20:
            failed_assets.append(f"{request.resource_type} {reason}: {request.url[:200]}")

    def _asset_request_failed(request) -> None:
        reason = request.failure or "failed"
        # Pages cancel lazy loads all the time, and Chromium blocks some
        # requests on its own. Neither is a missing file.
        if "ERR_ABORTED" not in reason and "ERR_BLOCKED_BY_CLIENT" not in reason:
            _asset_failed(request, reason)

    def _asset_status(resp) -> None:
        if resp.status >= 400:
            _asset_failed(resp.request, f"HTTP {resp.status}")

    page.on("requestfailed", _asset_request_failed)
    page.on("response", _asset_status)

    def reload() -> Any:
        """Load the page again, forgetting what the discarded load reported."""
        failed_assets.clear()
        console_errors.clear()
        page_errors.clear()
        documents.clear()
        return page.reload(wait_until="domcontentloaded", timeout=timeout)

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

    # The fallback when the browser keeps no timing for the page. Taken before
    # any of our own waiting, which is not the site's load time.
    goto_ms = int((time.monotonic() - started) * 1000)

    # Give scripts and fonts a moment, but never let a chatty page hold the run.
    _settle(page, settings, timeout)

    if failed_assets:
        # One retry. If the files still do not load, the capture says so, the
        # rules that need a whole page stay quiet, and the screenshot should
        # be checked before anyone sees it.
        try:
            response = reload() or response
            _settle(page, settings, timeout)
        except Exception:  # noqa: BLE001 - keep the first render
            pass

    # A gateway error is as often a hiccup between us and the host as it is the
    # site, and a finding that says the site is down had better be true twice.
    if response and response.status in RETRY_STATUSES:
        page.wait_for_timeout(3000)
        try:
            response = reload() or response
            _settle(page, settings, timeout)
        except Exception:  # noqa: BLE001 - keep the first answer
            pass

    # Imunify360, SiteGround, and Cloudflare screens often clear themselves
    # with a reload a few seconds in. Wait that out before calling it a wall.
    signals = probe_page(page)
    waited = 0
    challenge_wait = int(settings.get("challenge_wait_ms", 15000))
    while (signals.get("challenge") or {}).get("detected") and waited < challenge_wait:
        page.wait_for_timeout(1500)
        waited += 1500
        signals = probe_page(page)
    if waited and not (signals.get("challenge") or {}).get("detected"):
        _settle(page, settings, timeout)
        signals = probe_page(page)
    result["challenge_waited_ms"] = waited
    result["failed_assets"] = list(failed_assets)
    if documents:
        response = documents[-1]

    result["load_ms"] = _nav_load_ms(page) or goto_ms
    result["status"] = response.status if response else None
    result["status_text"] = response.status_text if response else ""
    try:
        result["server"] = (response.headers.get("server") or "") if response else ""
    except Exception:  # noqa: BLE001
        result["server"] = ""
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
    result["page_errors"] = page_errors
    if is_mobile and signals.get("scroll_width"):
        # Carousels and lazy sections are wide for a moment while they load, so
        # one reading of the page width can catch a layout nobody ever sees.
        # The page has to still be too wide two seconds later.
        page.wait_for_timeout(2000)
        try:
            again = int(page.evaluate("() => document.documentElement.scrollWidth") or 0)
        except Exception:  # noqa: BLE001
            again = 0
        if again:
            signals["scroll_width"] = min(signals["scroll_width"], again)
    result["signals"] = signals

    shot_path.parent.mkdir(parents=True, exist_ok=True)
    result["shot"] = _shoot(page, shot_path, settings)
    context.close()
    return result


def _new_record(slug: str, url: str) -> dict[str, Any]:
    return {
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


def _capture_child(url: str, slug: str, config: dict[str, Any],
                   output_base: str | Path | None) -> None:
    """Child process entry. Its own process group, so one kill takes Chromium too."""
    if hasattr(os, "setsid"):
        os.setsid()
    _capture_inline(url, slug, config, output_base)


def _kill_child(process) -> None:
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    process.kill()
    process.join(5)


def capture_site(
    url: str,
    slug: str,
    *,
    config: dict[str, Any] | None = None,
    output_base: str | Path | None = None,
) -> dict[str, Any]:
    """Capture one site and return the diagnosis, writing shots and capture.json.

    The browser work runs in a child process with a hard time limit. Some
    Playwright calls, reading the page among them, take no timeout, and a page
    that locks up its tab can hold them forever. One such site once stalled a
    whole batch for ten minutes. Past capture.site_timeout_ms the child and
    its Chromium are killed and the site is recorded as stalled. Set it to 0 to
    capture in this process with no limit.
    """
    config = config or prospect_lib.load_config()
    settings = config.get("capture", {})
    limit_ms = int(settings.get("site_timeout_ms", DEFAULT_SITE_TIMEOUT_MS))
    if limit_ms <= 0 or not prospect_lib.normalize_url(url):
        return _capture_inline(url, slug, config, output_base)

    import multiprocessing  # noqa: PLC0415

    out_dir = prospect_lib.output_dir_for(slug, output_base)
    out_dir.mkdir(parents=True, exist_ok=True)
    # A capture.json left from an earlier run must not pass for this one.
    (out_dir / CAPTURE_FILE).unlink(missing_ok=True)

    process = multiprocessing.get_context("spawn").Process(
        target=_capture_child, args=(url, slug, config, output_base), daemon=True
    )
    process.start()
    process.join(limit_ms / 1000)
    if process.is_alive():
        _kill_child(process)
        record = _new_record(slug, prospect_lib.normalize_url(url))
        record["error_kind"] = "stalled"
        record["summary"] = KIND_SUMMARY["stalled"]
        record["error"] = f"capture did not finish within {limit_ms // 1000}s and was stopped"
        _write(out_dir, record)
        print(f"  {record['error']}", file=sys.stderr)
        return record

    record = load_capture(slug, output_base)
    if record is None:
        record = _blank(
            _new_record(slug, prospect_lib.normalize_url(url)), "unknown",
            f"capture process exited with code {process.exitcode} and wrote nothing",
        )
        _write(out_dir, record)
    return record


def _capture_inline(
    url: str,
    slug: str,
    config: dict[str, Any] | None = None,
    output_base: str | Path | None = None,
) -> dict[str, Any]:
    """Capture in this process. capture_site wraps this in a time limit."""
    config = config or prospect_lib.load_config()
    settings = config.get("capture", {})
    out_dir = prospect_lib.output_dir_for(slug, output_base)
    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    url = prospect_lib.normalize_url(url)
    record = _new_record(slug, url)

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
            # http. Each fallback that works is itself a finding about the site,
            # so each one only runs after the failure it answers. A timeout that
            # happens to succeed on a second try is not a certificate problem.
            def visit(attempt_url: str, ignore_https: bool) -> dict[str, Any]:
                return _visit(
                    browser, attempt_url, desktop_view, USER_AGENT_DESKTOP,
                    False, settings, ignore_https, shots_dir / DESKTOP_FILE,
                )

            used_url = url
            desktop = visit(url, False)
            first_error = desktop
            if not desktop.get("shot") and desktop.get("error_kind") == "tls":
                desktop = visit(url, True)
                if desktop.get("shot"):
                    record["tls_error"] = True
            if (
                not desktop.get("shot")
                and url.startswith("https://")
                and first_error.get("error_kind") in HTTP_FALLBACK_KINDS
            ):
                plain = "http://" + url[len("https://"):]
                attempt = visit(plain, True)
                if attempt.get("shot"):
                    desktop = attempt
                    used_url = plain
                    record["scheme_downgraded"] = True
            if not desktop.get("shot"):
                # Report why https failed. The http retry's error says less.
                desktop = first_error

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
    record["page_errors"] = desktop.get("page_errors", [])
    record["failed_assets"] = desktop.get("failed_assets", [])
    record["mobile_failed_assets"] = mobile.get("failed_assets", [])
    # Scripts or styles that never arrived, on either visit. The render is not
    # the site as a customer sees it, so findings that read the render stay
    # quiet on it.
    record["incomplete_render"] = bool(record["failed_assets"] or record["mobile_failed_assets"])
    record["challenge_waited_ms"] = desktop.get("challenge_waited_ms", 0)
    record["desktop"] = f"shots/{DESKTOP_FILE}" if desktop.get("shot") else None
    record["mobile"] = f"shots/{MOBILE_FILE}" if mobile.get("shot") else None
    record["mobile_error"] = mobile.get("error", "")

    signals = dict(desktop.get("signals") or {})
    mobile_signals = mobile.get("signals") or {}
    scroll = mobile_signals.get("scroll_width") or 0
    inner = mobile_signals.get("inner_width") or 0
    # A page wider than the phone is the sideways-scroll complaint. Mobile
    # Chrome widens innerWidth to fit overflowing content, so compare against
    # the width we asked for, with room for a few stray pixels nobody sees.
    target = mobile_view["width"]
    signals["mobile_scroll_width"] = scroll
    signals["mobile_inner_width"] = inner
    signals["mobile_overflows"] = bool(scroll and scroll > target * 1.08)
    # Some sites only render a tap-to-call or booking button on phones, and
    # those are the findings about phones.
    for key in ("tel_links", "booking_links"):
        if (mobile_signals.get(key) or 0) > (signals.get(key) or 0):
            signals[key] = mobile_signals[key]
    # One slow fetch through our own connection is not a slow site. The finding
    # quotes the faster of the two loads we made.
    loads = [ms for ms in (record.get("load_ms"), mobile.get("load_ms")) if ms]
    signals["load_ms"] = min(loads) if loads else None
    all_errors = record.get("console_errors") or []
    real_errors, other_errors = own_errors(
        record.get("page_errors") or [], record["final_url"]
    )
    record["script_errors"] = real_errors
    record["other_script_errors"] = other_errors
    signals["console_error_count"] = len(all_errors)
    signals["script_error_count"] = len(real_errors)
    # The width we asked for, so a finding can quote a real phone width rather
    # than the layout viewport a browser invents for a non-responsive page.
    signals["mobile_target_width"] = mobile_view["width"]
    record["signals"] = signals

    record["redirected_offsite"] = bool(
        _host(record["final_url"]) and _host(record["final_url"]) != _host(url)
    )

    # A challenge screen renders fine and says nothing about the prospect. Flag
    # it so no rule downstream writes a finding about someone else's interstitial.
    challenge = (signals.get("challenge") or {}) if isinstance(signals, dict) else {}
    record["challenged"] = bool(challenge.get("detected"))
    if record["challenged"]:
        record["challenge_hits"] = challenge.get("hits") or []
        record["error_kind"] = "challenged"
        record["summary"] = KIND_SUMMARY["challenged"]
        record["error"] = (
            "bot protection detected by: " + ", ".join(record["challenge_hits"])
        )
        _write(out_dir, record)
        return record

    status = record["status"] or 0
    record["server"] = desktop.get("server", "")
    if status in PROXY_STATUSES and not record["server"]:
        # A bare error with no server header came from a proxy between us and
        # the site, and saying the prospect's site is down on it would be a lie.
        record["ok"] = False
        record["error_kind"] = "our_network"
        record["summary"] = KIND_SUMMARY["our_network"]
        record["error"] = f"HTTP {status} with no server header, likely our own proxy"
        _write(out_dir, record)
        return record
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
