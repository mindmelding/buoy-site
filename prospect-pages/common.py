"""Shared helpers for the Buoy prospect audit-page tools.

All paths are treated as relative to the prospect-pages/ directory. The
scripts chdir into their own directory at startup so they behave the same
no matter where they are launched from.
"""
import json
import os
import pathlib
import re
import secrets
import unicodedata


def chdir_to_script_dir(script_file):
    """Move the working directory to the directory of the given script file.

    Call this at the top of a script with chdir_to_script_dir(__file__) so
    that relative paths like config.json and dist/audit resolve the same way
    regardless of where the script was invoked from.
    """
    here = pathlib.Path(script_file).resolve().parent
    os.chdir(here)
    return here


def load_config(path="config.json"):
    """Load and return the JSON config as a dict."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def slugify(name):
    """Return a lowercase ascii slug: spaces and punctuation become single hyphens."""
    if not name:
        return ""
    # Normalize accents to their ascii base characters.
    normalized = unicodedata.normalize("NFKD", str(name))
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_str = ascii_str.lower()
    # Replace any run of non-alphanumeric characters with a single hyphen.
    ascii_str = re.sub(r"[^a-z0-9]+", "-", ascii_str)
    # Trim leading and trailing hyphens.
    return ascii_str.strip("-")


def ensure_slug(prospect, source_path=None):
    """Return a stable slug for the prospect, generating and persisting one if needed.

    If the prospect already has a non-empty "slug", it is returned unchanged.
    Otherwise a slug of the form "<slugified-name>-<8 hex chars>" is generated,
    stored on the prospect dict, and (if source_path is given) written back to
    that JSON file so the slug stays stable across separate runs.
    """
    existing = prospect.get("slug")
    if existing:
        return existing
    base = slugify(prospect.get("business_name", "")) or "prospect"
    slug = f"{base}-{secrets.token_hex(4)}"
    prospect["slug"] = slug
    if source_path is not None:
        with open(source_path, "w", encoding="utf-8") as fh:
            json.dump(prospect, fh, indent=2)
            fh.write("\n")
    return slug


def dist_dir(slug):
    """Return the output directory Path for a given slug: dist/audit/<slug>."""
    return pathlib.Path("dist/audit") / slug
