# Prospect audit pages

Builds one unlisted page per prospect that shows the specific work we would do
for that business. It is a sample of the $100 founding audit with their name on
it, sent 1:1 in cold outreach and never linked publicly.

Each page ships with the GitHub Pages site and serves at
`https://buoydesk.com/audit/<slug>/`.

## Setup

```bash
cd prospect-pages
pip install -r requirements.txt
playwright install chromium
```

If Chromium is already on the machine, point at it instead of downloading a
second copy:

```bash
export BUOY_CHROMIUM_PATH=/path/to/chromium
```

You can also set `capture.executable_path` in `config.json`. Behind a proxy,
set `capture.proxy` or the usual `HTTPS_PROXY` variable.

## Build one page

```bash
python generate.py --input examples/prospect.json --capture
```

That screenshots the prospect's site, renders the page, and writes it to
`dist/audit/<slug>/index.html`. Drop `--capture` to re-render from screenshots
already on disk, which is what you want while editing findings copy.

## Build a batch

```bash
python batch.py --input prospects.json
```

Reads a JSON list of prospects, builds every page, and writes
`dist/audit/pages.csv` mapping each business to its page URL. That CSV is the
sheet you work from when sending the emails.

Useful flags:

- `--skip-capture` reuses screenshots on disk and only re-renders the HTML.
- `--only "Harbor Line Auto Body"` rebuilds one prospect, repeatable.
- `--clean` wipes each page directory before rebuilding it.

One bad record does not stop the batch. Failures are listed at the end and the
exit status is non-zero.

## Draft the findings automatically

Writing findings by hand is the slow part. `research.py` visits each prospect's
site and drafts them from what the page actually shows:

```bash
python research.py --input prospects.json --in-place --report
```

It reuses the same browser visit as the screenshots, so it costs almost nothing
on top of a capture you were running anyway. Then build the pages as usual:

```bash
python batch.py --input prospects.json --skip-capture
```

Each draft is routed to the service that fixes it, and the strongest one becomes
`top_service`. Findings are capped at six per page by default so the page stays
readable. Raise it with `--max-findings`.

### What it checks

| Signal | Routes to |
| --- | --- |
| Site does not load, 4xx, offsite redirect, bad certificate, no https | Get Found |
| No mobile layout, page overflows at phone width | Get Found |
| Phone number is text with no `tel:` link, or no number at all | Get Found |
| No form, no email, no phone, no booking anywhere | After Hours |
| A form but nothing that books a time | After Hours |
| No hours, no business markup, thin page, no meta description | Get Found |
| Footer copyright is two or more years old | Regulars |
| No reviews on the site | Five Stars |
| Slow load, scripts throwing on load | Get Found |
| Photos with no alt text | Get Found |
| No link to Google, Facebook, Yelp, Instagram, or LinkedIn | Get Found |

### Observed against inferred

Every draft is tagged. `observed` means we measured it: the tag was absent, the
status was 404, the copyright said 2019. `inferred` means we guessed from a
pattern, for example that a quote form means nobody chases quiet estimates.

The inferred ones are usually the most valuable and they are the ones that will
embarrass you if they are wrong. `research.py` counts them at the end and writes
the evidence for every draft into a `_drafted` block on the record. Read those
before the page goes out. Use `--observed-only` to drop them.

Nothing here replaces looking at the site. A page that says we looked at your
business has to be right, so treat the drafts as a first pass that saves you the
mechanical checks, not as the audit.

### Notes on accuracy

- Failed resource loads are counted separately from scripts that actually threw,
  so a blocked font on your end never becomes a finding about their site.
- The sideways-scroll check only fires on sites that claim to be responsive.
  A site with no mobile layout gets the clearer finding instead.
- If a rule fires on a site you know is fine, that is a bug worth fixing in
  `RULES` in [research.py](research.py) rather than editing around.

## Publish

```bash
python publish.py --dry-run
python publish.py
git add audit && git commit && git push
```

`publish.py` copies `index.html` and the shots from `dist/audit/` into the
`audit/` directory at the site root, which is what GitHub Pages serves.
`capture.json` and `pages.csv` stay behind on purpose: the first holds our own
notes, and the second lists every prospect in the batch. Neither belongs on a
public host.

`--prune` removes published pages whose build directory is gone, which is how
you take a page down.

## Prospect fields

```json
{
  "business_name": "Harbor Line Auto Body",
  "url": "https://example.com",
  "phone": "(760) 555-0142",
  "category": "Auto body and collision repair",
  "city": "Oceanside, CA",
  "top_service": "Quote Rescue",
  "findings": [
    {
      "title": "Estimates go out and nothing follows them",
      "detail": "Two or three sentences about what we saw and what it costs.",
      "service": "Quote Rescue"
    }
  ]
}
```

`business_name` is the only required field. Everything else degrades: a page
with no phone simply does not show one.

`service` on a finding and `top_service` should name one of the ten services in
`config.json`, which is where the kicker and the payoff paragraph come from.
Both accept a name that is not in the catalog, in which case set
`top_service_payoff` on the prospect to supply the paragraph yourself.

Optional fields: `intro` replaces the default opening paragraph,
`top_service_payoff` overrides the catalog paragraph, and `slug` pins the URL.

## Slugs

Slugs are `business-name-<8 random hex>`, for example
`harbor-line-auto-body-0312b7cb`. The hex is what keeps a page unguessable, so
do not shorten it and do not use a slug you have published before.

The first build assigns a slug and saves it back into the prospect file so the
URL stays stable on every rebuild. Pass `--no-write-slugs` to batch.py if you
do not want that, but then a rebuild produces a new URL and the link already in
someone's inbox goes dead.

## View tracking

Off by default. To turn it on, fill in the endpoint in `config.json`:

```json
"view_tracking": {
  "enabled": true,
  "endpoint": "https://px.buoydesk.com/v.gif",
  "slug_param": "slug",
  "extra_params": { "campaign": "cold-q3" }
}
```

That renders a 1x1 image at the bottom of the page pointing at
`https://px.buoydesk.com/v.gif?slug=<slug>&campaign=cold-q3`. It is a plain
image with no JavaScript, so it works with scripts blocked.

Serve the endpoint with `Cache-Control: no-store`, otherwise a second visit
comes from the browser cache and you never hear about it. Pages send
`referrer-policy: no-referrer`, so the slug in the query string is the only
thing identifying the page.

## Broken and hijacked sites

Those are the prospects worth the most to us, so the capture never gives up
quietly. It tries the URL as given, then again trusting a bad certificate, then
over plain http. Whatever happens is written to `dist/audit/<slug>/capture.json`
and turned into page copy:

- Domain does not resolve, connection refused, or timeout: the page shows a
  panel explaining that the site did not load, with the error quoted.
- Expired or invalid certificate: the screenshot still gets taken, and the page
  notes that browsers warn visitors away first.
- Redirect to another domain: flagged, with the domain it lands on named.
- HTTP 4xx or 5xx: the error page is screenshotted as-is and the status called
  out.
- No mobile layout, slow load, or script errors: listed as short technical
  notes under the screenshots.

A site problem never raises. It becomes a finding.

## Keeping pages private

Pages carry `noindex, nofollow, noarchive`, the site's
[robots.txt](../robots.txt) disallows `/audit/`, and nothing on the site links
to them. The unguessable slug is what actually keeps a page private, so treat
the URL the way you would treat a password and send it to one recipient.

Every page carries a line telling the recipient they can have it taken down the
same day. Honor that with `publish.py --prune`.
