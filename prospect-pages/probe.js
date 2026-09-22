// Collected inside the already-loaded page during capture, so a research pass
// costs almost nothing on top of the screenshots. Everything here is something
// the page actually shows or declares. Nothing is inferred.
() => {
  const text = (document.body ? document.body.innerText : "") || "";
  const html = document.documentElement ? document.documentElement.outerHTML : "";
  const all = (sel) => Array.from(document.querySelectorAll(sel));
  const attr = (sel, name) => all(sel).map((el) => el.getAttribute(name) || "").filter(Boolean);

  const bookingVendors = /calendly|acuityscheduling|squareup|setmore|schedulicity|housecallpro|jobber|servicetitan|mindbody|vagaro|booksy|square\.site|appointlet|youcanbook|simplybook|tally\.so|typeform|hubspot|getjobber/i;
  const chatVendors = /intercom|drift|tawk|crisp|livechat|zendesk|podium|birdeye|tidio|hubspot-messages/i;
  const reviewVendors = /birdeye|podium|grade\.us|reviewsio|trustpilot|elfsight|sociablekit|yotpo|nicejob|trustindex|reviewbadges|embedsocial|review-widget|reviewsonmywebsite|trustmary|broadly|gatherup/i;
  const bookingWords = /\b(book (now|online|an appointment)|schedule (an? )?(appointment|service|estimate)|request (an? )?(estimate|quote|appointment)|get (an? )?(quote|estimate)|make an appointment|online booking)\b/i;

  const viewport = document.querySelector('meta[name="viewport"]');
  const images = all("img");

  const jsonld = [];
  all('script[type="application/ld+json"]').forEach((node) => {
    try { jsonld.push(JSON.parse(node.textContent || "")); } catch (err) { /* malformed is itself a signal */ }
  });
  const schemaTypes = [];
  let schemaHours = !!document.querySelector('[itemprop="openingHours"], [itemprop="openingHoursSpecification"]');
  const walk = (node) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) return node.forEach(walk);
    if (node["@type"]) [].concat(node["@type"]).forEach((t) => schemaTypes.push(String(t)));
    if (node.openingHours || node.openingHoursSpecification) schemaHours = true;
    Object.values(node).forEach(walk);
  };
  walk(jsonld);

  const years = (text.match(/\b(19|20)\d{2}\b/g) || []).map(Number).filter((y) => y >= 1990 && y <= 2100);
  const copyrightBlock = (text.match(/(?:©|\(c\)|copyright)[^\n]{0,60}/gi) || []).join(" ");
  const copyrightYears = (copyrightBlock.match(/\b(19|20)\d{2}\b/g) || []).map(Number);

  // Text a visitor can reach, including collapsed footers and accordions,
  // without the CSS and scripts that textContent would drag in.
  const fullText = (() => {
    if (!document.body) return "";
    const copy = document.body.cloneNode(true);
    copy.querySelectorAll("script, style, noscript, template").forEach((n) => n.remove());
    return (copy.textContent || "").replace(/\s+/g, " ");
  })();
  const hrefs = all("a[href]").map((a) => a.getAttribute("href") || "");

  const linkText = all("a, button").map((el) => (el.innerText || el.value || "").trim()).filter(Boolean);
  const iframeSrc = attr("iframe", "src");
  const scriptSrc = attr("script", "src");
  const sources = iframeSrc.concat(scriptSrc).join(" ");

  // Tuesday, Wednesday, Thursday, and Saturday all need their own stems, and
  // real footers say "M-F 8am-5pm" as often as they spell the days out.
  const dayWords = /\b(mon|tues?|wed(nes)?|thu(rs?)?|fri|sat(ur)?|sun)(day)?s?\b|\bm\s*[-–]\s*f\b/i;
  const timeWords = /\b\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)|\b\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\b/i;
  const allDay = /\b(open )?24\s*\/\s*7\b|\bopen 24 hours\b/i;

  // A form counts as a way to reach the business when it asks for more than a
  // search box or a newsletter address does.
  const isContactForm = (form) => {
    if (form.matches('[role="search"]') || form.querySelector('input[type="search"]')) return false;
    if (form.querySelector("textarea")) return true;
    const fields = form.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input:not([type]), select');
    return fields.length >= 3;
  };
  const formVendors = /jotform|wufoo|formstack|docs\.google\.com\/forms|hsforms|typeform|cognitoforms|123formbuilder|form\.jotform|formsite/i;

  // Content photos only. alt="" is the correct markup for a decorative image,
  // and lazy-load placeholders and icons are not the work a shop sells on.
  const contentImages = images.filter((img) => {
    const box = img.getBoundingClientRect();
    return box.width >= 100 && box.height >= 60;
  });

  return {
    word_count: text.trim().split(/\s+/).filter(Boolean).length,
    has_viewport: !!viewport,
    viewport_content: viewport ? viewport.getAttribute("content") || "" : "",
    title_length: (document.title || "").trim().length,
    has_meta_description: !!document.querySelector('meta[name="description"]'),
    h1_count: all("h1").length,

    tel_links: all('a[href^="tel:"]').length,
    mailto_links: all('a[href^="mailto:"]').length,
    phone_in_text: /\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b/.test(text),

    form_count: all("form").length,
    contact_form_count: all("form").filter(isContactForm).length + iframeSrc.filter((s) => formVendors.test(s)).length,
    contact_link: hrefs.some((h) => /contact|request|appointment|estimate/i.test(h)) ||
      linkText.some((t) => /^contact( us)?$|get in touch/i.test(t)),
    quote_language: /\b(estimates?|quotes?)\b/i.test(text),
    input_count: all("input, textarea, select").length,
    booking_links: linkText.filter((t) => bookingWords.test(t)).length,
    booking_embed: bookingVendors.test(sources) || bookingVendors.test(html.slice(0, 200000)),
    chat_widget: chatVendors.test(sources),
    review_embed: reviewVendors.test(sources),
    maps_embed: /google\.com\/maps|maps\.google|mapbox|openstreetmap/i.test(sources),

    schema_types: Array.from(new Set(schemaTypes)),
    schema_hours: schemaHours,
    jsonld_blocks: jsonld.length,

    copyright_year: copyrightYears.length ? Math.max.apply(null, copyrightYears) : null,
    latest_year_in_text: years.length ? Math.max.apply(null, years) : null,

    hours_listed: (dayWords.test(fullText) && timeWords.test(fullText)) || allDay.test(fullText),
    // Collapsed menus hide the "Reviews" link from innerText on desktop, and a
    // link to a reviews page is the site pointing at its reviews.
    mentions_reviews: /\b(reviews?|testimonials?|what our (customers|clients|patients) (say|are saying)|google rating)\b/i.test(fullText) ||
      hrefs.some((h) => /reviews?|testimonials?/i.test(h)),
    mentions_emergency: /\b(24\/?7|emergency|after hours|24 hour)\b/i.test(text),

    // Links a visitor can follow. The raw html mentions facebook.com in every
    // tracking pixel and yelp.com in review markup, which is not a link.
    social: {
      facebook: hrefs.some((h) => /(^|\/\/|\.)(facebook\.com|fb\.com|fb\.me)\//i.test(h) && !/facebook\.com\/(tr|sharer|dialog)/i.test(h)),
      instagram: hrefs.some((h) => /instagram\.com\//i.test(h)),
      yelp: hrefs.some((h) => /yelp\.(com|to)\//i.test(h) && !/yelp\.com\/(writeareview|search)/i.test(h) || /yelp\.com\/writeareview\/biz/i.test(h)),
      google_business: hrefs.some((h) => /g\.page\/|business\.google|maps\.app\.goo\.gl|goo\.gl\/maps|google\.com\/maps|maps\.google\.|search\.google\.com\/local|g\.co\/kgs/i.test(h)),
      linkedin: hrefs.some((h) => /linkedin\.com\//i.test(h)),
      nextdoor: hrefs.some((h) => /nextdoor\.com\//i.test(h))
    },

    image_count: contentImages.length,
    images_without_alt: contentImages.filter((img) => !img.hasAttribute("alt")).length,

    scroll_width: document.documentElement ? document.documentElement.scrollWidth : 0,
    inner_width: window.innerWidth,

    // Bot-protection interstitials look like a loaded page but are not the
    // prospect's site. Auditing one would produce findings about Cloudflare.
    // A captcha on a contact form is not a challenge page. Real small-business
    // sites load reCAPTCHA, hCaptcha, and Turnstile on every page with a form,
    // so a vendor script or a sitekey only counts on a nearly empty page.
    // Interstitials seen in the wild ran 8 to 30 words.
    challenge: (() => {
      const title = (document.title || "").toLowerCase();
      const words = text.trim().split(/\s+/).filter(Boolean).length;
      const short = words < 120;
      const tiny = words < 60;
      const titleHit = /just a moment|one moment, please|attention required|access denied|checking your browser|security check|verifying you are human|are you human|ddos protection|please wait|human verification|robot challenge|bot verification/.test(title);
      const pathHit = /\/\.well-known\/sgcaptcha|\/cdn-cgi\/challenge-platform|__cf_chl/i.test(location.href);
      const pageMarkup = !!document.querySelector("#challenge-form, #challenge-running, #challenge-stage, #sgcaptcha, #challenge-body-text");
      const vendorHit = tiny && /challenges\.cloudflare\.com|hcaptcha\.com|recaptcha|turnstile|perimeterx|datadome|incapsula|imperva|akamai bot|sgcaptcha|imunify/i.test(html);
      const widgetHit = tiny && !!document.querySelector(".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey]");
      const wordingHit = short &&
        /cloudflare|captcha|ray id|enable javascript and cookies|verify you are a human|bot detection|request is being verified|checking (your|if the site connection is) (browser|secure)|robot challenge/i.test(text);
      const hits = [];
      if (titleHit) hits.push("title");
      if (pathHit) hits.push("challenge url");
      if (pageMarkup) hits.push("challenge markup");
      if (vendorHit) hits.push("near-empty page with captcha vendor");
      if (widgetHit) hits.push("near-empty page with captcha widget");
      if (wordingHit) hits.push("short page with bot-check wording");
      return { detected: hits.length > 0, hits: hits, title: document.title || "", words: words };
    })()
  };
}
