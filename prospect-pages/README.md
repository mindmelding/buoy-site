# Prospect audit preview pages

This directory builds personalized "audit preview" pages for Buoy prospects. Each
page is a private, unlisted, one-to-one sample of the $100 founding audit for a
single business: a screenshot of their current website, a short list of findings,
and one clear next step (book the call). Pages are marked `noindex, nofollow`,
are not linked from the main site, and live at unguessable URLs like
`https://buoydesk.com/audit/<business-slug>-<random>/`.

## What is here

- `config.json` | shared settings (Calendly link, brand colors, capture sizes, ping).
- `common.py` | shared helpers (config loading, slugify, stable slug generation, paths).
- `capture.py` | Playwright screenshot tool (desktop + mobile), with graceful handling of broken sites.
- `generate.py` | render one prospect into `dist/audit/<slug>/index.html`.
- `batch.py` | run capture + generate over a list of prospects and write a CSV.
- `check.py` | acceptance validator (no em dashes, all local links resolve).
- `publish.py` | copy finished pages to the repo root so GitHub Pages serves them.
- `templates/audit.html.j2` | the self-contained page template (all CSS inline).
- `samples/` | a healthy example, a broken-site example, and a batch array.

## Setup

Install the Python dependencies:

```
pip install -r requirements.txt
```

The Chromium binary is PRE-INSTALLED at `/opt/pw-browsers` in this environment, so
do NOT run `playwright install`. `capture.py` launches Chromium directly via
`executable_path`, read from `capture.chromium_executable` in `config.json`. If that
path does not exist, Playwright falls back to its own default browser.

Screenshots need a real network path to the prospect's site. Broken, parked, or
unreachable sites are still captured as a branded diagnostic page (see below), so a
capture run always produces real PNGs.

## Usage

Capture screenshots for one prospect:

```
python capture.py --input samples/healthy.json
python capture.py --url example.com --slug seabreeze-demo
```

Generate one page (captures first if screenshots are missing):

```
python generate.py --input samples/healthy.json
python generate.py --input samples/broken.json --no-capture
```

Generate a whole batch and write `dist/audit/prospects.csv`:

```
python batch.py --input samples/prospects.example.json
```

Validate the output and the source tree:

```
python check.py
```

Publish finished pages to the repo root (see the deploy model below):

```
python publish.py --dry-run
python publish.py
```

## Config fields

- `calendly_url` | the booking link used by every CTA button.
- `site_base_url` | canonical domain, used to build the public `/audit/<slug>/` URL.
- `contact_email` | address shown in the private-preview footer.
- `location` | shown in the footer row.
- `brand` | the Buoy color values injected as CSS variables.
- `capture` | screenshot sizes, timeout, `full_page`, and `chromium_executable`.
- `pageview_ping` | optional 1x1 beacon. Disabled by default, so nothing renders.

## Graceful handling of broken sites

The most valuable prospects often have a site that is down, parked, or hijacked.
`capture.py` never crashes on these:

- A navigation timeout is retried once with a lighter wait condition, and whatever
  rendered is still screenshotted (status `partial`).
- A hard failure (DNS error, refused connection) is caught. The page is filled with a
  small branded diagnostic screen in Buoy colors that states, in plain language, that
  the site could not be reached, shows the URL as a clickable link, and gives the
  error reason. That screen is screenshotted (status `unreachable`).
- `dist/audit/<slug>/shots/capture.json` records `url`, `final_url`, `http_status`,
  `status`, `error`, and timestamps. The generated page shows a short honest note when
  the status is not `ok`.

## Deploy model

The live site is served by GitHub Pages from the REPO ROOT (custom domain
`buoydesk.com`, see the `CNAME` file at the repo root). A page is only live once its
folder sits at `<repo_root>/audit/<slug>/`. `publish.py` copies each
`dist/audit/<slug>/` folder (its `index.html` plus `shots/`) into `../audit/<slug>/`
at the repo root, skipping the CSV and resolved-list files.

## Privacy tradeoff

Pages under `/audit/` are unlisted, not indexed, and not linked from the site, but they
are NOT access controlled. Once published they are publicly reachable by anyone who has
the exact unguessable URL, and they are committed to the repository, so the HTML and
screenshots live in git history. Only publish a prospect you intend to host, share the
link privately, and never add `/audit/` to `sitemap.xml`.

## Strict writing rules

All copy in this project follows Buoy's writing rules:

- No em dashes anywhere. Use commas, colons, periods, or `|` instead.
- No bare URLs in text a person reads. Every visible URL is an `<a href>` link, or a
  `mailto:` or `tel:` link.
- Plain, direct language. No hype and no marketing filler.

Run `python check.py` to enforce the first two rules across generated pages and the
source tree.
