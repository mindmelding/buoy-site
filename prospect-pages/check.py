"""Acceptance validator for generated audit pages and the source tree.

Checks:
  1. No em dash (U+2014) in any generated dist/audit/**/index.html (FAIL).
  2. Every relative src/href in those pages resolves to a file on disk (FAIL).
  3. Visible bare URLs (text like >http...< with no anchor) are flagged (WARN).
  4. No em dash (U+2014) anywhere in the prospect-pages/ source tree
     (py, j2, md, json) (FAIL).

Exits nonzero on any FAIL.

Usage:
    python check.py
"""
import pathlib
import re
import sys

from common import chdir_to_script_dir

# Built from a code point so this source file never contains a literal em dash.
EM_DASH = chr(0x2014)

# Relative link attributes we resolve on disk.
LINK_RE = re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
# A URL sitting as visible text between tags. We first strip anchor elements so
# a URL that is the text of a proper <a href> link is not flagged.
ANCHOR_RE = re.compile(r'<a\b[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)
BARE_URL_RE = re.compile(r'>\s*(https?://[^<\s]+)\s*<')

SKIP_SCHEMES = ("http://", "https://", "//", "mailto:", "tel:", "#", "data:")


def is_relative_asset(link):
    stripped = link.strip()
    if not stripped:
        return False
    return not stripped.lower().startswith(SKIP_SCHEMES)


def check_generated_pages():
    """Return (failures, warnings) for generated index.html files."""
    failures = []
    warnings = []
    pages = sorted(pathlib.Path("dist/audit").glob("**/index.html")) if pathlib.Path("dist/audit").exists() else []
    if not pages:
        warnings.append("No generated pages found under dist/audit (nothing to validate).")
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                failures.append(f"EM DASH in {page}:{i}")
        # Local asset resolution.
        for link in LINK_RE.findall(text):
            if is_relative_asset(link):
                target = link.split("?", 1)[0].split("#", 1)[0]
                resolved = (page.parent / target).resolve()
                if not resolved.exists():
                    failures.append(f"MISSING asset {link} referenced by {page}")
        # Bare visible URLs (best effort warning). Strip proper anchor elements
        # first so a URL that is the visible text of an <a href> link is allowed.
        without_anchors = ANCHOR_RE.sub("", text)
        for m in BARE_URL_RE.finditer(without_anchors):
            warnings.append(f"Possible bare URL text {m.group(1)!r} in {page}")
    return failures, warnings


def check_source_tree():
    """Return failures for em dashes anywhere in the source tree."""
    failures = []
    root = pathlib.Path(".")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {"dist", "__pycache__", ".venv"} for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".j2", ".md", ".json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                failures.append(f"EM DASH in source {path}:{i}")
    return failures


def main():
    chdir_to_script_dir(__file__)
    page_failures, page_warnings = check_generated_pages()
    source_failures = check_source_tree()

    failures = page_failures + source_failures
    warnings = page_warnings

    for w in warnings:
        print(f"WARN: {w}")
    for f in failures:
        print(f"FAIL: {f}")

    if failures:
        print(f"\ncheck.py: FAIL ({len(failures)} problem(s), {len(warnings)} warning(s))")
        return 1
    print(f"\ncheck.py: PASS (0 problems, {len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
