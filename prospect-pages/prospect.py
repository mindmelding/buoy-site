"""Shared helpers for the prospect audit-page generator.

Loads config.json, normalizes prospect records, and assigns the unguessable
slugs the pages are published under.
"""

from __future__ import annotations

import json
import re
import secrets
import unicodedata
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "config.json"
DEFAULT_OUTPUT_DIR = PACKAGE_DIR / "dist" / "audit"

SLUG_TOKEN_BYTES = 4  # 4 bytes renders as the 8 hex characters the slug ends with.
SLUG_NAME_MAX = 48
HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{8}$")

REQUIRED_FIELDS = ("business_name",)
KNOWN_FIELDS = (
    "business_name",
    "url",
    "phone",
    "category",
    "city",
    "findings",
    "top_service",
    "top_service_payoff",
    "slug",
    "intro",
    "notes",
    "_drafted",
)


class ProspectError(ValueError):
    """Raised when a prospect record cannot be turned into a page."""


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Read config.json and fill in the defaults the templates rely on."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ProspectError(f"config file not found: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)

    config.setdefault("calendly_url", "")
    config.setdefault("contact_email", "")
    config.setdefault("services", {})

    site = config.setdefault("site", {})
    site.setdefault("base_url", "https://buoydesk.com")
    site.setdefault("audit_path", "/audit")
    site.setdefault("company", "Buoy")
    site.setdefault("home_url", site["base_url"])
    site["base_url"] = site["base_url"].rstrip("/")
    site["audit_path"] = "/" + site["audit_path"].strip("/")

    brand = config.setdefault("brand", {})
    defaults = {
        "ink": "#102f35",
        "paper": "#fff8ec",
        "orange": "#ff593d",
        "yellow": "#ffd448",
        "aqua": "#a7e6da",
        "blue": "#b9dff1",
    }
    for key, fallback in defaults.items():
        value = str(brand.get(key, fallback)).strip()
        # The value lands inside a CSS custom property, so only accept hex.
        brand[key] = value if HEX_COLOR.match(value) else fallback

    tracking = config.setdefault("view_tracking", {})
    tracking.setdefault("enabled", False)
    tracking.setdefault("endpoint", "")
    tracking.setdefault("slug_param", "slug")
    tracking.setdefault("extra_params", {})
    if not str(tracking.get("endpoint", "")).strip():
        tracking["enabled"] = False

    capture = config.setdefault("capture", {})
    capture.setdefault("desktop_width", 1440)
    capture.setdefault("desktop_height", 900)
    capture.setdefault("mobile_width", 390)
    capture.setdefault("mobile_height", 844)
    capture.setdefault("timeout_ms", 30000)
    capture.setdefault("settle_ms", 1200)
    capture.setdefault("full_page", False)
    capture.setdefault("max_full_page_height", 4000)

    return config


def slugify_name(name: str) -> str:
    """Turn a business name into the readable half of a slug."""
    folded = unicodedata.normalize("NFKD", name)
    folded = folded.encode("ascii", "ignore").decode("ascii").lower()
    folded = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    folded = folded[:SLUG_NAME_MAX].strip("-")
    return folded or "prospect"


def new_slug(business_name: str) -> str:
    """Build business-name-<8 random hex>. The hex is what keeps it unguessable."""
    return f"{slugify_name(business_name)}-{secrets.token_hex(SLUG_TOKEN_BYTES)}"


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_RE.match(slug or ""))


def normalize_url(url: str | None) -> str:
    """Add a scheme when the prospect list stores a bare hostname.

    Only http and https survive. A prospect list is pasted together by hand,
    and anything else would end up as a live href on a page we email out.
    """
    url = (url or "").strip()
    if not url:
        return ""
    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", url)
    if scheme_match:
        if scheme_match.group(1).lower() not in ("http", "https"):
            return ""
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            return ""
        return url
    return "https://" + url


def display_url(url: str) -> str:
    """The hostname and path, without the scheme, for on-page link text."""
    stripped = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", (url or "").strip())
    return stripped.rstrip("/") or url


def tel_href(phone: str | None) -> str:
    """A tel: target built from the digits in the stored phone number."""
    digits = re.sub(r"[^0-9+]", "", phone or "")
    return f"tel:{digits}" if digits else ""


def page_url(config: dict[str, Any], slug: str) -> str:
    site = config["site"]
    return f"{site['base_url']}{site['audit_path']}/{slug}/"


def normalize_prospect(
    raw: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    assign_slug: bool = True,
) -> dict[str, Any]:
    """Validate one prospect record and fill in everything the template reads."""
    if not isinstance(raw, dict):
        raise ProspectError("each prospect must be a JSON object")

    prospect = dict(raw)
    for field in REQUIRED_FIELDS:
        if not str(prospect.get(field, "")).strip():
            raise ProspectError(f"prospect is missing a required field: {field}")

    prospect["business_name"] = str(prospect["business_name"]).strip()

    slug = str(prospect.get("slug", "")).strip()
    if slug:
        if not is_valid_slug(slug):
            raise ProspectError(
                f"slug {slug!r} for {prospect['business_name']} is not in the "
                "business-name-<8 hex> form"
            )
    elif assign_slug:
        slug = new_slug(prospect["business_name"])
    else:
        raise ProspectError(
            f"{prospect['business_name']} has no slug and slug assignment is off"
        )
    prospect["slug"] = slug

    prospect["url"] = normalize_url(prospect.get("url"))
    prospect["display_url"] = display_url(prospect["url"])
    prospect["phone"] = str(prospect.get("phone", "")).strip()
    prospect["tel_href"] = tel_href(prospect["phone"])
    prospect["category"] = str(prospect.get("category", "")).strip()
    prospect["city"] = str(prospect.get("city", "")).strip()
    prospect["intro"] = str(prospect.get("intro", "")).strip()
    prospect["top_service"] = str(prospect.get("top_service", "")).strip()

    services = (config or {}).get("services", {})
    findings = []
    for index, item in enumerate(prospect.get("findings") or [], start=1):
        if not isinstance(item, dict):
            raise ProspectError(
                f"finding {index} for {prospect['business_name']} must be an object"
            )
        title = str(item.get("title", "")).strip()
        if not title:
            raise ProspectError(
                f"finding {index} for {prospect['business_name']} is missing a title"
            )
        service = str(item.get("service", "")).strip()
        findings.append(
            {
                "number": f"{index:02d}",
                "anchor": f"finding-{index}",
                "title": title,
                "detail": str(item.get("detail", "")).strip(),
                "service": service,
                "kicker": services.get(service, {}).get("kicker", ""),
            }
        )
    prospect["findings"] = findings

    service_entry = services.get(prospect["top_service"], {})
    payoff = str(prospect.get("top_service_payoff", "")).strip()
    prospect["top_service_payoff"] = payoff or service_entry.get("payoff", "")
    prospect["top_service_kicker"] = service_entry.get("kicker", "")
    prospect["top_service_summary"] = service_entry.get("summary", "")

    if config:
        prospect["page_url"] = page_url(config, slug)

    unknown = [k for k in raw if k not in KNOWN_FIELDS]
    prospect["_unknown_fields"] = unknown
    return prospect


def load_prospects(path: str | Path) -> tuple[list[dict[str, Any]], str]:
    """Read one prospect object or a list of them.

    Returns the records plus the shape of the file, so batch.py can write
    assigned slugs back without reformatting the caller's structure.
    """
    source = Path(path)
    if not source.exists():
        raise ProspectError(f"prospect file not found: {source}")
    with source.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        return data, "list"
    if isinstance(data, dict) and isinstance(data.get("prospects"), list):
        return data["prospects"], "wrapped"
    if isinstance(data, dict):
        return [data], "single"
    raise ProspectError(f"{source} is not a prospect object or a list of them")


def save_prospects(path: str | Path, records: list[dict[str, Any]], shape: str) -> None:
    """Write records back in the shape they were read in."""
    target = Path(path)
    if shape == "single":
        payload: Any = records[0]
    elif shape == "wrapped":
        with target.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["prospects"] = records
    else:
        payload = records
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def output_dir_for(slug: str, base: str | Path | None = None) -> Path:
    return (Path(base) if base else DEFAULT_OUTPUT_DIR) / slug
