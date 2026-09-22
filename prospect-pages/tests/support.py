"""Shared setup for the tests. Run them from prospect-pages:

    python -m unittest discover -s tests -t .

Tests that need Chromium skip themselves when it cannot start. Point
BUOY_CHROMIUM_PATH at a local build to run them without a playwright download.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

import capture  # noqa: E402

PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


def local_launch_options() -> dict:
    """Launch options for pages served from this machine.

    Playwright sends loopback through a configured proxy whatever the bypass
    list says, so local tests launch without one.
    """
    saved = {name: os.environ.pop(name) for name in PROXY_VARS if name in os.environ}
    try:
        options = capture._launch_options({})
    finally:
        os.environ.update(saved)
    options.pop("proxy", None)
    return options


class BrowserTestCase(unittest.TestCase):
    """One Chromium for the whole class, or a skip if there is none."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("playwright is not installed")
        cls._playwright = sync_playwright().start()
        try:
            cls.browser = cls._playwright.chromium.launch(**local_launch_options())
        except Exception as exc:  # noqa: BLE001 - no browser means skip, not fail
            cls._playwright.stop()
            raise unittest.SkipTest(f"chromium could not start: {exc}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls._playwright.stop()
