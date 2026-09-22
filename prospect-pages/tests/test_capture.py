"""capture.py pieces that need no browser."""

from __future__ import annotations

import unittest

from tests.support import FIXTURES, capture


class SpkiPinTest(unittest.TestCase):
    def test_pins_match_published_values(self):
        # The published SPKI pins for Let's Encrypt's RSA and EC roots.
        pins = capture.spki_pins(str(FIXTURES / "isrg-roots.pem"))
        self.assertEqual(pins, (
            "C5+lpZ7tcVwmwQIMcRtPbsQtWLABXhQzejna0wHFr8M=",
            "diGVwiVYbubAI3RW4hB9xU8e/CH2GnkuvVFZE8zmgzI=",
        ))

    def test_unreadable_file_pins_nothing(self):
        self.assertEqual(capture.spki_pins(str(FIXTURES / "missing.pem")), ())


class ScriptErrorTest(unittest.TestCase):
    def test_browser_chatter_is_not_a_script_error(self):
        # Every one of these came from a real site whose scripts worked.
        noise = [
            "Potential permissions policy violation: autoplay is not allowed in this document.",
            "play() failed because the user didn't interact with the document first.",
            "The element has no supported sources.",
            "Refused to apply style from 'https://example.com/a.css' because its MIME type",
            "suspense rendered fallback for - tpaWorker_6 - (TPAWorker)",
            "AxiosError: Request failed with status code 401",
            "Unexpected token '<'",
            "Failed to load resource: net::ERR_CONNECTION_RESET",
        ]
        self.assertEqual(capture.script_errors(noise), [])

    def test_a_real_exception_counts(self):
        message = "Cannot set properties of null (setting 'innerHTML')"
        self.assertEqual(capture.script_errors([message]), [message])

    def test_only_the_sites_own_scripts_count(self):
        errors = [
            {"message": "widget broke", "origin": "embeddable-app-widgets.s3.us-east-1.amazonaws.com"},
            {"message": "their page broke", "origin": "harborline.example"},
            {"message": "their cdn broke", "origin": "cdn.harborline.example"},
            {"message": "Invalid or unexpected token", "origin": ""},
        ]
        mine, others = capture.own_errors(errors, "https://www.harborline.example/")
        self.assertEqual(mine, ["their page broke", "their cdn broke"])
        self.assertEqual(others, ["widget broke", "Invalid or unexpected token"])


class ErrorKindTest(unittest.TestCase):
    def test_classify(self):
        cases = {
            "net::ERR_NAME_NOT_RESOLVED at https://x.example": "dns",
            "net::ERR_CERT_AUTHORITY_INVALID at https://x.example": "tls",
            "net::ERR_CONNECTION_REFUSED": "refused",
            "Timeout 30000ms exceeded.": "timeout",
            "something new": "unknown",
        }
        for message, kind in cases.items():
            with self.subTest(message=message):
                self.assertEqual(capture.classify_error(message), kind)

    def test_our_side_kinds_have_summaries(self):
        for kind in capture.OUR_SIDE_KINDS:
            self.assertIn(kind, capture.KIND_SUMMARY)


if __name__ == "__main__":
    unittest.main()
