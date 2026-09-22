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
  const reviewVendors = /birdeye|podium|grade\.us|reviewsio|trustpilot|elfsight|sociablekit|yotpo|nicejob/i;
  const bookingWords = /\b(book (now|online|an appointment)|schedule (an? )?(appointment|service|estimate)|request (an? )?(estimate|quote|appointment)|get (an? )?(quote|estimate)|make an appointment|online booking)\b/i;

  const jsonld = [];
  all('script[type="application/ld+json"]').forEach((node) => {
    try { jsonld.push(JSON.parse(node.textContent || "")); } catch (err) { /* malformed is itself a signal */ }
  });
  const schemaTypes = [];
  const walk = (node) => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) return node.forEach(walk);
    if (node["@type"]) [].concat(node["@type"]).forEach((t) => schemaTypes.push(String(t)));
    Object.values(node).forEach(walk);
  };
  walk(jsonld);

  const years = (text.match(/\b(19|20)\d{2}\b/g) || []).map(Number).filter((y) => y >= 1990 && y <= 2100);
  const copyrightBlock = (text.match(/(?:©|\(c\)|copyright)[^\n]{0,60}/gi) || []).join(" ");
  const copyrightYears = (copyrightBlock.match(/\b(19|20)\d{2}\b/g) || []).map(Number);

  const linkText = all("a, button").map((el) => (el.innerText || el.value || "").trim()).filter(Boolean);
  const iframeSrc = attr("iframe", "src");
  const scriptSrc = attr("script", "src");
  const sources = iframeSrc.concat(scriptSrc).join(" ");

  const dayWords = /\b(mon|tue|wed|thu|fri|sat|sun)(day|s)?\b/i;
  const timeWords = /\b\d{1,2}(:\d{2})?\s*(am|pm)\b/i;

  const viewport = document.querySelector('meta[name="viewport"]');
  const images = all("img");

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
    input_count: all("input, textarea, select").length,
    booking_links: linkText.filter((t) => bookingWords.test(t)).length,
    booking_embed: bookingVendors.test(sources) || bookingVendors.test(html.slice(0, 200000)),
    chat_widget: chatVendors.test(sources),
    review_embed: reviewVendors.test(sources),
    maps_embed: /google\.com\/maps|maps\.google|mapbox|openstreetmap/i.test(sources),

    schema_types: Array.from(new Set(schemaTypes)),
    jsonld_blocks: jsonld.length,

    copyright_year: copyrightYears.length ? Math.max.apply(null, copyrightYears) : null,
    latest_year_in_text: years.length ? Math.max.apply(null, years) : null,

    hours_listed: dayWords.test(text) && timeWords.test(text),
    mentions_reviews: /\b(review|testimonial|what our customers say)\b/i.test(text),
    mentions_emergency: /\b(24\/?7|emergency|after hours|24 hour)\b/i.test(text),

    social: {
      facebook: /facebook\.com/i.test(html),
      instagram: /instagram\.com/i.test(html),
      yelp: /yelp\.com/i.test(html),
      google_business: /g\.page|business\.google|maps\.app\.goo\.gl/i.test(html),
      linkedin: /linkedin\.com/i.test(html)
    },

    image_count: images.length,
    images_without_alt: images.filter((img) => !(img.getAttribute("alt") || "").trim()).length,

    scroll_width: document.documentElement ? document.documentElement.scrollWidth : 0,
    inner_width: window.innerWidth
  };
}
