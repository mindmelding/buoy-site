"""Turn capture signals into draft findings for a prospect page.

Every rule here fires on something the site actually declared or showed. Each
draft carries the evidence that produced it, so you can check a claim before it
goes out under your name.

Rules marked "inferred" are the ones worth the most and the ones most likely to
be wrong. They are drafts, not observations. Read them before sending.

Usage:
    python research.py --input prospects.json --out prospects.drafted.json
    python research.py --input prospects.json --in-place --report
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

import capture as capture_lib
import prospect as prospect_lib

OBSERVED = "observed"
INFERRED = "inferred"

DEAD_KINDS = {"dns", "refused", "unreachable", "timeout", "empty", "blocked", "unknown"}
LOCAL_SCHEMA = {
    "localbusiness", "autorepair", "autobodyshop", "dentist", "medicalbusiness",
    "homeandconstructionbusiness", "professionalservice", "store", "restaurant",
    "hairsalon", "healthandbeautybusiness", "plumber", "electrician", "roofingcontractor",
    "generalcontractor", "veterinarycare", "legalservice", "accountingservice",
}


class Rule:
    def __init__(self, rule_id: str, weight: int, service: str, confidence: str,
                 applies: Callable[[dict, dict], bool],
                 title: str, detail: str, evidence: Callable[[dict, dict], str]):
        self.id = rule_id
        self.weight = weight
        self.service = service
        self.confidence = confidence
        self.applies = applies
        self.title = title
        self.detail = detail
        self.evidence = evidence


def _count_phrase(count: int, noun: str, singular_verb: str, plural_verb: str) -> str:
    """Keep generated sentences grammatical when a count happens to be one."""
    if count == 1:
        return f"1 {noun} {singular_verb}"
    return f"{count} {noun}s {plural_verb}"


def _sig(cap: dict) -> dict:
    return cap.get("signals") or {}


def _has_local_schema(sig: dict) -> bool:
    return any(str(t).lower() in LOCAL_SCHEMA for t in sig.get("schema_types") or [])


def _reachable(cap: dict) -> bool:
    """True when we actually rendered the site, so DOM rules can be trusted.

    A bot-protection screen renders perfectly and belongs to Cloudflare, not to
    the prospect, so every DOM rule has to stay silent on one.
    """
    if cap.get("challenged"):
        return False
    return bool(cap.get("ok")) and bool(_sig(cap))


RULES: list[Rule] = [
    Rule("no_website", 100, "Get Found", OBSERVED,
         lambda cap, s: cap.get("error_kind") == "no_url",
         "There is no website to send customers to",
         "We could not find a website for {business_name}. Someone who looks you up finds a "
         "listing, a phone number, and nowhere to go to see your work or ask a question. "
         "Every other shop they compare you against has somewhere to go.",
         lambda cap, s: "no url on file and none found"),

    Rule("site_down", 99, "Get Found", OBSERVED,
         lambda cap, s: not cap.get("ok") and cap.get("error_kind") in DEAD_KINDS,
         "Your website does not load",
         "We tried to open your site the way a customer would and it did not come up. "
         "{capture_summary} Anyone who taps through from a search result gets a browser "
         "error, and most of them do not try again.",
         lambda cap, s: f"browser error: {cap.get('error', 'unknown')}"),

    Rule("http_error", 95, "Get Found", OBSERVED,
         lambda cap, s: (cap.get("status") or 0) >= 400,
         "Your site answers with an error page",
         "The server returns a {status} error instead of your site. Visitors land on an "
         "error page, and search engines drop a page that keeps answering this way.",
         lambda cap, s: f"HTTP {cap.get('status')} {cap.get('status_text', '')}".strip()),

    Rule("redirected", 93, "Get Found", OBSERVED,
         lambda cap, s: bool(cap.get("redirected_offsite")),
         "Your domain sends visitors somewhere else",
         "The address on your listings redirects to another domain. A customer checking "
         "that they are in the right place has no way to tell, and that is exactly what a "
         "hijacked domain looks like from the outside.",
         lambda cap, s: f"redirects to {cap.get('final_url', '')}"),

    Rule("tls_error", 90, "Get Found", OBSERVED,
         lambda cap, s: bool(cap.get("tls_error")),
         "Browsers warn visitors before your site opens",
         "The security certificate is not valid, so browsers show a full page warning "
         "before anyone sees your site. We had to click through it. Most people will not.",
         lambda cap, s: "page loaded only with certificate errors ignored"),

    Rule("no_https", 85, "Get Found", OBSERVED,
         lambda cap, s: bool(cap.get("scheme_downgraded")) and not cap.get("tls_error"),
         "Your site is marked not secure",
         "The site loads over plain http, so browsers put a not secure label in the address "
         "bar next to your name. It also counts against you in search results.",
         lambda cap, s: "https failed, page served over http"),

    Rule("no_viewport", 80, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and s.get("has_viewport") is False,
         "Your site is not built for phones",
         "The page has no mobile layout, so a phone shows the desktop version shrunk to fit "
         "and everything has to be pinched to read. Most of the people looking you up are "
         "on a phone.",
         lambda cap, s: "no meta viewport tag"),

    Rule("mobile_overflow", 78, "Get Found", OBSERVED,
         lambda cap, s: bool(s.get("mobile_overflows")) and bool(s.get("has_viewport")),
         "The page scrolls sideways on a phone",
         "At phone width the layout is wider than the screen, so it slides off to the side "
         "as you scroll. It reads as broken even when everything on the page works.",
         lambda cap, s: f"{s.get('mobile_scroll_width')}px of content at a "
                        f"{s.get('mobile_target_width')}px phone width"),

    Rule("phone_not_tappable", 75, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and s.get("phone_in_text") and not s.get("tel_links"),
         "Your phone number cannot be tapped",
         "The number is on the page as text rather than as a link a phone can dial. Someone "
         "standing next to a broken thing has to memorize it, leave your site, and type it "
         "in. Some of them do not bother.",
         lambda cap, s: "phone number in text, no tel: link on the page"),

    Rule("no_phone", 74, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and not s.get("phone_in_text") and not s.get("tel_links"),
         "There is no phone number on your site",
         "We could not find a number anywhere on the page. For a business people call "
         "before they buy, that is the one thing that has to be easy to find.",
         lambda cap, s: "no phone number found in text or links"),

    Rule("no_contact_route", 72, "After Hours", OBSERVED,
         lambda cap, s: _reachable(cap) and not s.get("form_count")
                        and not s.get("tel_links") and not s.get("mailto_links")
                        and not s.get("booking_embed"),
         "There is no way to contact you from the site",
         "No form, no email link, no phone link, no booking. A visitor who wants to reach "
         "you has to go back to a search result and start over.",
         lambda cap, s: "no form, mailto, tel link, or booking embed"),

    Rule("form_only", 68, "After Hours", OBSERVED,
         lambda cap, s: _reachable(cap) and s.get("form_count")
                        and not s.get("booking_links") and not s.get("booking_embed"),
         "Every request waits for someone to get back to it",
         "Your site takes messages through a form, and after that the customer waits. "
         "Nothing confirms a time and nothing gets booked. A request that comes in Friday "
         "night sits until Monday, and the people in a hurry call the next shop on the list.",
         lambda cap, s: f"{s.get('form_count')} form(s), no booking link or scheduler embed"),

    Rule("no_hours", 65, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and s.get("hours_listed") is False,
         "Your hours are not on the site",
         "We could not find opening hours anywhere. That is one of the first things somebody "
         "checks before driving over, and the first thing an assistant looks for when "
         "somebody asks whether you are open right now.",
         lambda cap, s: "no day and time pattern found in page text"),

    Rule("no_local_schema", 62, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and not _has_local_schema(s),
         "Search engines have nothing structured to read",
         "The page carries no business markup, so your name, address, hours, and phone are "
         "just words on a page. The tools that answer who does this near me read the markup "
         "first, and you are not in it.",
         lambda cap, s: f"schema types found: {', '.join(s.get('schema_types') or []) or 'none'}"),

    Rule("stale_copyright", 60, "Regulars", OBSERVED,
         lambda cap, s: bool(s.get("copyright_year"))
                        and s["copyright_year"] < date.today().year - 1,
         "The site has not been touched since {copyright_year}",
         "The footer still reads {copyright_year}. Somebody comparing three shops reads a "
         "stale date as a business that might not be running any more, and moves on without "
         "calling to check.",
         lambda cap, s: f"footer copyright year {s.get('copyright_year')}"),

    Rule("thin_content", 58, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and 0 < (s.get("word_count") or 0) < 250,
         "There is almost nothing on the page",
         "The whole site runs about {word_count} words. That is not enough for a customer to "
         "judge you on, and not enough for a search engine or an assistant to have any reason "
         "to put you ahead of anyone else.",
         lambda cap, s: f"{s.get('word_count')} words of visible text"),

    Rule("no_reviews", 55, "Five Stars", OBSERVED,
         lambda cap, s: _reachable(cap) and not s.get("mentions_reviews")
                        and not s.get("review_embed"),
         "Your reviews are not on your own site",
         "Nothing on the page points to your reviews. The best evidence you have that you do "
         "good work is sitting on someone else's website, where a visitor has to go looking "
         "for it.",
         lambda cap, s: "no review text or review widget on the page"),

    Rule("slow_load", 52, "Get Found", OBSERVED,
         lambda cap, s: (s.get("load_ms") or 0) > 4000,
         "The page takes {load_seconds} seconds to load",
         "On a phone connection that is long enough that a real share of visitors leave "
         "before they see anything. It counts against you in search rankings too.",
         lambda cap, s: f"{s.get('load_ms')}ms to interactive"),

    Rule("console_errors", 50, "Get Found", OBSERVED,
         lambda cap, s: (s.get("script_error_count") or 0) > 0,
         "Scripts on your site are failing",
         "{script_error_phrase} when the page loads. Something on the "
         "page is not doing what it was built to do, and when that something is a contact "
         "form the messages go nowhere without anyone noticing.",
         lambda cap, s: f"{s.get('script_error_count')} script errors thrown on load"),

    Rule("no_listings_link", 48, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and not any((s.get("social") or {}).values()),
         "Your site does not connect to your listings",
         "There is no link to your Google listing, your Facebook page, or your Yelp page. "
         "Those profiles and this site are not confirming each other, which is one of the "
         "signals used to decide you are a real and current business.",
         lambda cap, s: "no facebook, instagram, yelp, or google business link"),

    Rule("images_no_alt", 45, "Get Found", OBSERVED,
         lambda cap, s: (s.get("image_count") or 0) >= 5
                        and (s.get("images_without_alt") or 0) / max(1, s.get("image_count") or 1) > 0.5,
         "Your photos cannot be read by anything but a person",
         "{images_without_alt} of {image_count} images have no description attached. For a "
         "business that sells on how the work looks, your strongest evidence is invisible to "
         "search engines and to anyone using a screen reader.",
         lambda cap, s: f"{s.get('images_without_alt')} of {s.get('image_count')} images missing alt text"),

    Rule("no_meta_description", 40, "Get Found", OBSERVED,
         lambda cap, s: _reachable(cap) and s.get("has_meta_description") is False,
         "Search results show no description under your name",
         "The page has no description set, so a search engine writes its own from whatever "
         "text it finds first. The one line that decides whether somebody clicks is being "
         "picked for you.",
         lambda cap, s: "no meta description tag"),

    # Inferred. High value, and the ones you have to check before sending.
    Rule("quote_followup", 69, "Quote Rescue", INFERRED,
         lambda cap, s: _reachable(cap) and (s.get("form_count") or 0) > 0,
         "Estimates go out and nothing follows them",
         "Your site takes requests through a form. In most shops that means the quote goes "
         "out and whether anyone chases it depends on somebody remembering. The ones that "
         "go quiet are the cheapest work available to you, because the job is already priced.",
         lambda cap, s: "INFERRED from the presence of a request form, not observed"),

    Rule("after_hours_gap", 64, "After Hours", INFERRED,
         lambda cap, s: _reachable(cap) and s.get("hours_listed")
                        and not s.get("mentions_emergency") and not s.get("chat_widget"),
         "Nothing catches the calls that come in after you close",
         "Your hours are posted and there is no after hours path next to them. Calls that "
         "land in the evening reach a voicemail at best, and the customer is usually calling "
         "three places in the same ten minutes.",
         lambda cap, s: "INFERRED from posted hours with no emergency or chat option"),
]


def draft_findings(cap: dict, record: dict, *, max_findings: int = 6,
                   observed_only: bool = False) -> list[dict[str, Any]]:
    """Run every rule against one capture and return the findings that fired."""
    cap = cap or {}
    if cap.get("challenged"):
        # Nothing here is about the prospect. Say so rather than guess.
        return []
    signals = _sig(cap)
    load_ms = signals.get("load_ms") or cap.get("load_ms") or 0
    fields = {
        "business_name": record.get("business_name", "this business"),
        "capture_summary": cap.get("summary", ""),
        "status": cap.get("status"),
        "load_seconds": f"{load_ms / 1000:.1f}",
        "script_error_phrase": _count_phrase(
            signals.get("script_error_count") or 0, "script error", "fires", "fire"
        ),
        **{k: v for k, v in signals.items() if isinstance(v, (str, int, float))},
    }

    drafts = []
    for rule in RULES:
        if observed_only and rule.confidence != OBSERVED:
            continue
        try:
            fired = rule.applies(cap, signals)
        except Exception:  # noqa: BLE001 - a bad signal must not stop the pass
            fired = False
        if not fired:
            continue
        try:
            title = rule.title.format(**fields)
            detail = " ".join(rule.detail.format(**fields).split())
        except (KeyError, IndexError):
            continue
        drafts.append({
            "title": title,
            "detail": detail,
            "service": rule.service,
            "rule": rule.id,
            "confidence": rule.confidence,
            "evidence": rule.evidence(cap, signals),
            "_weight": rule.weight,
        })

    drafts.sort(key=lambda d: d["_weight"], reverse=True)
    for draft in drafts:
        draft.pop("_weight")
    return drafts[:max_findings]


def _top_service(drafts: list[dict]) -> str:
    """The service behind the strongest observed finding leads the page."""
    for draft in drafts:
        if draft["confidence"] == OBSERVED:
            return draft["service"]
    return drafts[0]["service"] if drafts else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Draft findings for prospects from what their sites actually show."
    )
    parser.add_argument("--input", required=True, help="prospect JSON file")
    parser.add_argument("--out", help="where to write the drafted file")
    parser.add_argument("--in-place", action="store_true", help="write back to --input")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--output", help="capture base directory, default dist/audit")
    parser.add_argument("--skip-capture", action="store_true",
                        help="reuse capture.json already on disk")
    parser.add_argument("--max-findings", type=int, default=6)
    parser.add_argument("--observed-only", action="store_true",
                        help="drop the inferred rules, leaving only what was measured")
    parser.add_argument("--replace", action="store_true",
                        help="overwrite findings a prospect already has")
    parser.add_argument("--report", action="store_true",
                        help="print the evidence behind every draft")
    args = parser.parse_args(argv)

    if not args.out and not args.in_place:
        parser.error("pass --out or --in-place")

    config = prospect_lib.load_config(args.config)
    records, shape = prospect_lib.load_prospects(args.input)

    inferred_total = 0
    for index, record in enumerate(records, start=1):
        name = str(record.get("business_name", f"record {index}")).strip()
        try:
            p = prospect_lib.normalize_prospect(record, config=config)
        except prospect_lib.ProspectError as exc:
            print(f"[{index}/{len(records)}] {name}: skipped, {exc}", file=sys.stderr)
            continue
        record.setdefault("slug", p["slug"])

        print(f"[{index}/{len(records)}] {name}")
        if args.skip_capture:
            cap = capture_lib.load_capture(p["slug"], args.output) or {}
            if not cap:
                print("  no capture on disk, run without --skip-capture")
        else:
            cap = capture_lib.capture_site(
                p["url"], p["slug"], config=config, output_base=args.output
            )

        drafts = draft_findings(
            cap, record,
            max_findings=args.max_findings,
            observed_only=args.observed_only,
        )
        if cap.get("challenged"):
            print(
                "  bot protection answered instead of the site "
                f"({', '.join(cap.get('challenge_hits') or [])}). "
                "Nothing drafted. Open this one in your own browser and write it by hand."
            )
            continue
        if not drafts:
            print("  nothing fired. This site is in decent shape, so write findings by hand.")
            continue

        existing = record.get("findings") or []
        if existing and not args.replace:
            print(f"  {len(existing)} finding(s) already written, leaving them alone")
        else:
            record["findings"] = [
                {k: v for k, v in d.items() if k in ("title", "detail", "service")}
                for d in drafts
            ]
            record["_drafted"] = [
                {"rule": d["rule"], "confidence": d["confidence"], "evidence": d["evidence"]}
                for d in drafts
            ]
            if not record.get("top_service"):
                record["top_service"] = _top_service(drafts)

        observed = sum(1 for d in drafts if d["confidence"] == OBSERVED)
        inferred = len(drafts) - observed
        inferred_total += inferred
        print(f"  {observed} observed, {inferred} inferred, top service {record.get('top_service')}")
        if args.report:
            for draft in drafts:
                mark = " " if draft["confidence"] == OBSERVED else "?"
                print(f"   {mark} {draft['title']}")
                print(f"     {draft['evidence']}")

    target = Path(args.out) if args.out else Path(args.input)
    prospect_lib.save_prospects(target, records, shape)
    print(f"\nwrote {target}")
    if inferred_total:
        print(
            f"{inferred_total} finding(s) are inferred rather than observed. They are marked "
            "in _drafted and they are the ones most likely to be wrong. Read them before "
            "these pages go out."
        )
    print("Every draft is a starting point. Check it against the site before you send it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
