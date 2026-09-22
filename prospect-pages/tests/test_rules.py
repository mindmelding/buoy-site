"""The findings rules against captures of real North County business sites.

Each fixture is a real capture with everything that identifies the business
removed: no name, url, page title, or error text, only the signals the rules
read. expected_rules is the exact set of rules that fire, checked by hand
against the live site. The verified block says what was checked, and for a rule that
once misfired on that site, why it is now expected to stay quiet.

When a rule change moves one of these sets, look at the site the label came
from before updating the fixture. That is the whole point of the fixture.
"""

from __future__ import annotations

import json
import unittest

from tests.support import FIXTURES

import research

SITES = sorted((FIXTURES / "sites").glob("*.json"))


class RealSiteRulesTest(unittest.TestCase):
    def test_fixtures_exist(self):
        self.assertGreaterEqual(len(SITES), 20)

    def test_each_site_fires_exactly_what_was_verified(self):
        for path in SITES:
            fixture = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(site=fixture["label"]):
                drafts = research.draft_findings(
                    fixture["capture"], {"business_name": "Test Business"}, max_findings=100
                )
                self.assertEqual(sorted(d["rule"] for d in drafts), fixture["expected_rules"])

    def test_every_rule_id_is_known(self):
        known = {rule.id for rule in research.RULES}
        for path in SITES:
            fixture = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(site=fixture["label"]):
                self.assertLessEqual(set(fixture["expected_rules"]), known)
                self.assertLessEqual(set(fixture.get("verified", {})), known)


class OurSideTest(unittest.TestCase):
    """Nothing about the prospect can be said when the failure was ours."""

    def test_no_findings(self):
        for kind in ("our_network", "stalled"):
            with self.subTest(kind=kind):
                cap = {"ok": False, "error_kind": kind, "status": 502, "signals": {}}
                self.assertEqual(research.draft_findings(cap, {"business_name": "X"}), [])

    def test_no_findings_behind_a_challenge(self):
        cap = {"ok": True, "challenged": True, "status": 200,
               "signals": {"word_count": 8, "has_viewport": False}}
        self.assertEqual(research.draft_findings(cap, {"business_name": "X"}), [])

    def test_blank_render_drafts_no_dom_findings(self):
        # A preloader that never lifted: the page is there and shows nothing.
        cap = {"ok": True, "status": 200, "signals": {
            "word_count": 0, "has_viewport": True, "tel_links": 0, "phone_in_text": False,
            "hours_listed": False, "schema_types": [], "mobile_overflows": True,
        }}
        self.assertEqual(research.draft_findings(cap, {"business_name": "X"}), [])

    def test_incomplete_render_holds_layout_and_script_findings(self):
        cap = {"ok": True, "status": 200, "incomplete_render": True, "signals": {
            "word_count": 500, "has_viewport": True, "mobile_overflows": True,
            "mobile_scroll_width": 530, "mobile_target_width": 390, "script_error_count": 2,
            "tel_links": 1, "phone_in_text": True, "hours_listed": True, "schema_hours": True,
            "schema_types": ["Dentist"], "mentions_reviews": True, "has_meta_description": True,
            "social": {"facebook": True}, "mentions_emergency": True,
        }}
        rules = {d["rule"] for d in research.draft_findings(cap, {"business_name": "X"})}
        self.assertNotIn("mobile_overflow", rules)
        self.assertNotIn("console_errors", rules)

    def test_failed_probe_drafts_no_dom_findings(self):
        # Capture adds load and mobile keys even when the probe failed.
        cap = {"ok": True, "status": 200, "signals": {"mobile_scroll_width": 390, "load_ms": 900}}
        self.assertEqual(research.draft_findings(cap, {"business_name": "X"}), [])


if __name__ == "__main__":
    unittest.main()
