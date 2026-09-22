"""probe.js against small pages built from what real sites actually did.

Every case here is a misfire found on a real North County business site. The
page is rebuilt from the shape of the markup, not copied from the site.
"""

from __future__ import annotations

import unittest

from tests.support import BrowserTestCase, capture

PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
FILLER = " ".join(["We fix cars and trucks for families across North County."] * 40)


class ProbeTest(BrowserTestCase):
    def probe(self, body: str, head: str = "", width: int = 1440) -> dict:
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        try:
            page.set_content(f"<!doctype html><html><head>{head}</head><body>{body}</body></html>")
            return capture.probe_page(page)
        finally:
            page.close()

    # Hours. "Tuesday" once failed to match because the stem was "tue" and
    # the regex then demanded a word boundary before "sday".
    def test_hours_spelled_out_midweek(self):
        for day in ("Tuesday", "Wednesday", "Thursday", "Saturday"):
            with self.subTest(day=day):
                signals = self.probe(f"<p>{day}: 8:00 AM to 5:00 PM</p>")
                self.assertTrue(signals["hours_listed"])

    def test_hours_abbreviated(self):
        self.assertTrue(self.probe("<footer>Hours: M-F 8am-5pm, Sat 8am-1pm</footer>")["hours_listed"])
        self.assertTrue(self.probe("<p>Mon - Fri 9:00 - 17:00</p>")["hours_listed"])

    def test_hours_in_a_collapsed_footer(self):
        body = '<div style="display:none">Hours: Monday - Friday 8am - 5pm</div>'
        self.assertTrue(self.probe(body)["hours_listed"])

    def test_open_around_the_clock(self):
        self.assertTrue(self.probe("<p>Open 24/7 for emergencies</p>")["hours_listed"])

    def test_no_hours(self):
        signals = self.probe("<p>Call us Monday about your estimate.</p>")
        self.assertFalse(signals["hours_listed"])
        self.assertFalse(signals["schema_hours"])

    def test_hours_in_markup_only(self):
        head = ('<script type="application/ld+json">{"@type": "AutoBodyShop", '
                '"openingHoursSpecification": [{"dayOfWeek": "Monday"}]}</script>')
        self.assertTrue(self.probe("<p>Body shop</p>", head)["schema_hours"])

    # Reviews. "\breview\b" never matched "Reviews".
    def test_reviews_plural(self):
        self.assertTrue(self.probe("<nav><a href='/'>Reviews</a></nav>")["mentions_reviews"])

    def test_reviews_link_in_collapsed_menu(self):
        body = '<nav style="display:none"><a href="/customer-reviews">Customer reviews</a></nav>'
        self.assertTrue(self.probe(body)["mentions_reviews"])

    def test_testimonials_page_link(self):
        self.assertTrue(self.probe('<a href="/testimonials/">What people say</a>')["mentions_reviews"])

    def test_no_reviews(self):
        self.assertFalse(self.probe("<p>We fix cars.</p>")["mentions_reviews"])

    # Challenge screens.
    def test_recaptcha_contact_form_is_not_a_challenge(self):
        body = (f"<p>{FILLER}</p><form><input name=n><input type=email><textarea></textarea>"
                '<div class="g-recaptcha" data-sitekey="x"></div></form>'
                '<script src="https://www.google.com/recaptcha/api.js"></script>')
        self.assertFalse(self.probe(body)["challenge"]["detected"])

    def test_imunify_interstitial(self):
        head = "<title>One moment, please...</title>"
        body = "<p>Please wait while your request is being verified...</p>"
        self.assertTrue(self.probe(body, head)["challenge"]["detected"])

    def test_siteground_captcha(self):
        head = "<title>Robot Challenge Screen</title>"
        self.assertTrue(self.probe("<p>Checking your browser</p>", head)["challenge"]["detected"])

    def test_cloudflare_origin_error_is_not_a_challenge(self):
        # A dead origin behind Cloudflare is a real finding, not a wall.
        head = "<title>example.com | 502: Bad gateway</title>"
        body = f'<div id="cf-wrapper"><div class="cf-error-details">{FILLER}</div></div>'
        self.assertFalse(self.probe(body, head)["challenge"]["detected"])

    # Images. alt="" is correct for decoration and icons are not the work.
    def test_alt_counting(self):
        body = (
            f'<img src="{PIXEL}" alt="" style="width:400px;height:300px">'
            f'<img src="{PIXEL}" style="width:400px;height:300px">'
            f'<img src="{PIXEL}" alt="A repaired bumper" style="width:400px;height:300px">'
            f'<img src="{PIXEL}" style="width:16px;height:16px">'
        )
        signals = self.probe(body)
        self.assertEqual(signals["image_count"], 3)
        self.assertEqual(signals["images_without_alt"], 1)

    # Social links come from links, not tracking pixels.
    def test_facebook_pixel_is_not_a_link(self):
        body = '<noscript><img src="https://www.facebook.com/tr?id=1&ev=PageView"></noscript>'
        self.assertFalse(self.probe(body)["social"]["facebook"])

    def test_facebook_page_link(self):
        self.assertTrue(self.probe('<a href="https://www.facebook.com/someshop/">FB</a>')["social"]["facebook"])

    def test_yelp_in_review_markup_is_not_a_link(self):
        head = '<script type="application/ld+json">{"@type":"Review","url":"https://www.yelp.com/biz/x"}</script>'
        self.assertFalse(self.probe("<p>Plumbing</p>", head)["social"]["yelp"])

    # Contact routes.
    def test_search_and_newsletter_forms_are_not_contact_forms(self):
        body = ('<form role="search"><input type="search"></form>'
                '<form><input type="email" placeholder="Newsletter"></form>')
        signals = self.probe(body)
        self.assertEqual(signals["form_count"], 2)
        self.assertEqual(signals["contact_form_count"], 0)

    def test_contact_form(self):
        body = "<form><input name=name><input type=email><textarea></textarea></form>"
        self.assertEqual(self.probe(body)["contact_form_count"], 1)

    def test_contact_page_link(self):
        self.assertTrue(self.probe('<a href="/contact-us/">Get in touch</a>')["contact_link"])

    def test_quote_language(self):
        self.assertTrue(self.probe("<p>Free estimates on all collision work.</p>")["quote_language"])
        self.assertFalse(self.probe("<p>Cuts, color, and blowouts.</p>")["quote_language"])


if __name__ == "__main__":
    unittest.main()
