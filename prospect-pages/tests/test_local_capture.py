"""Whole captures against pages served from this machine.

The hang page is the reason capture runs under a time limit: it loads, then an
infinite loop takes the main thread, and reading the page never returns.
"""

from __future__ import annotations

import functools
import os
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.support import PROXY_VARS, BrowserTestCase, capture

import prospect as prospect_lib
import research

HANG_PAGE = """<!doctype html><html><head><title>Hang</title>
<meta name="viewport" content="width=device-width"></head>
<body><h1>Loads, then locks up</h1>
<script>setTimeout(function () { while (true) {} }, 1500);</script></body></html>"""

OK_PAGE = """<!doctype html><html><head><title>Fine</title>
<meta name="viewport" content="width=device-width"></head>
<body><h1>Harbor Line Auto Body</h1><p>Call <a href="tel:7605550142">(760) 555-0142</a>.</p>
</body></html>"""

# A library that never arrives, and the site's own code that needed it.
MISSING_SCRIPT_PAGE = """<!doctype html><html><head><title>Half there</title>
<meta name="viewport" content="width=device-width"></head>
<body><h1>Harbor Line Auto Body</h1>
<script src="/vendor/carousel.js"></script>
<script>jQuery(".slides").owlCarousel();</script></body></html>"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


class LocalCaptureTest(BrowserTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()  # skips the class when there is no browser
        cls.root = tempfile.TemporaryDirectory()
        Path(cls.root.name, "hang.html").write_text(HANG_PAGE, encoding="utf-8")
        Path(cls.root.name, "ok.html").write_text(OK_PAGE, encoding="utf-8")
        Path(cls.root.name, "half.html").write_text(MISSING_SCRIPT_PAGE, encoding="utf-8")
        handler = functools.partial(QuietHandler, directory=cls.root.name)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.root.cleanup()
        super().tearDownClass()

    def capture(self, page: str, limit_ms: int) -> tuple[dict, float]:
        config = prospect_lib.load_config()
        config["capture"]["site_timeout_ms"] = limit_ms
        config["capture"]["proxy"] = ""
        out = tempfile.mkdtemp()
        # The child inherits this environment, and loopback must not go through
        # a proxy that cannot reach it.
        clean = {k: v for k, v in os.environ.items() if k not in PROXY_VARS}
        with mock.patch.dict(os.environ, clean, clear=True):
            started = time.monotonic()
            record = capture.capture_site(
                f"{self.base}/{page}", "watchdog-test-0000abcd", config=config, output_base=out
            )
        return record, time.monotonic() - started

    def test_hung_page_is_stopped_and_marked_stalled(self):
        record, elapsed = self.capture("hang.html", 15000)
        self.assertEqual(record["error_kind"], "stalled")
        self.assertFalse(record["ok"])
        self.assertLess(elapsed, 25)

    def test_normal_page_comes_back_whole_through_the_child(self):
        record, _ = self.capture("ok.html", 60000)
        self.assertTrue(record["ok"], record.get("error"))
        self.assertEqual(record["signals"]["tel_links"], 1)
        self.assertEqual(record["desktop"], "shots/desktop.png")
        self.assertFalse(record["incomplete_render"])

    def test_missing_library_marks_the_render_incomplete(self):
        record, _ = self.capture("half.html", 60000)
        self.assertTrue(record["ok"], record.get("error"))
        self.assertTrue(record["incomplete_render"])
        self.assertTrue(any("carousel.js" in a for a in record["failed_assets"]))
        # The error is real and on their domain, but it follows from a file
        # that never arrived, so no finding is drafted from it.
        self.assertEqual(record["signals"]["script_error_count"], 1)
        drafts = research.draft_findings(record, {"business_name": "Test"}, max_findings=100)
        self.assertNotIn("console_errors", {d["rule"] for d in drafts})


if __name__ == "__main__":
    unittest.main()
