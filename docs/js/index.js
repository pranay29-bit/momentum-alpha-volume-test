const { onSchedule } = require("firebase-functions/v2/scheduler");
const { onRequest } = require("firebase-functions/v2/https");
const admin = require("firebase-admin");
const logger = require("firebase-functions/logger");

admin.initializeApp();
const db = admin.firestore();

// ── Yahoo Finance crumb/cookie handshake ──────────────────────────────────
// Yahoo's chart API now requires a session cookie + crumb token, obtained
// from a separate handshake call, or it silently returns stale/wrong data.
// We cache the crumb+cookie in memory for the lifetime of the function
// instance (a few minutes to a few hours typically) instead of re-fetching
// it on every single price lookup.
let cachedCrumb = null;
let cachedCookie = null;
let crumbFetchedAt = 0;
const CRUMB_TTL_MS = 30 * 60 * 1000; // refresh handshake every 30 min

async function getCrumbAndCookie() {
  const isFresh = cachedCrumb && cachedCookie && (Date.now() - crumbFetchedAt < CRUMB_TTL_MS);
  if (isFresh) return { crumb: cachedCrumb, cookie: cachedCookie };

  // Step 1: hit Yahoo to get a session cookie
  const cookieRes = await fetch("https://fc.yahoo.com", {
    headers: { "User-Agent": "Mozilla/5.0" }
  });
  const setCookie = cookieRes.headers.get("set-cookie") || "";
  const cookie = setCookie.split(";")[0];

  // Step 2: use that cookie to fetch a crumb token
  const crumbRes = await fetch("https://query2.finance.yahoo.com/v1/test/getcrumb", {
    headers: {
      "User-Agent": "Mozilla/5.0",
      "Cookie": cookie
    }
  });
  const crumb = await crumbRes.text();

  if (!crumb || crumb.includes("<html")) {
    throw new Error("Failed to obtain Yahoo crumb token");
  }

  cachedCrumb = crumb;
  cachedCookie = cookie;
  crumbFetchedAt = Date.now();
  return { crumb, cookie };
}

async function fetchLivePrice(symbol) {
  const { crumb, cookie } = await getCrumbAndCookie();

  const url = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
              `?interval=1m&crumb=${encodeURIComponent(crumb)}`;

  const res = await fetch(url, {
    headers: {
      "User-Agent": "Mozilla/5.0",
      "Cookie": cookie
    }
  });

  if (!res.ok) {
    throw new Error(`Yahoo returned HTTP ${res.status} for ${symbol}`);
  }

  const data = await res.json();
  const price = data?.chart?.result?.[0]?.meta?.regularMarketPrice;

  if (typeof price !== "number" || price <= 0) {
    throw new Error(`No valid price in response for ${symbol}`);
  }

  return price;
}

// ── Core job: pull every open position's symbol, fetch once per unique
// symbol (not once per position — saves calls if multiple people hold the
// same stock), then write currentPrice back with the admin SDK (bypasses
// security rules entirely, since this runs trusted server-side). ─────────
async function updateAllPrices() {
  const snap = await db.collection("positions").get();

  if (snap.empty) {
    logger.info("No open positions — nothing to update.");
    return { updated: 0, failed: 0 };
  }

  // Group docs by symbol so we only call Yahoo once per unique symbol.
  const bySymbol = new Map();
  snap.forEach((doc) => {
    const symbol = doc.data().symbol;
    if (!bySymbol.has(symbol)) bySymbol.set(symbol, []);
    bySymbol.get(symbol).push(doc.id);
  });

  let updated = 0;
  let failed = 0;
  const batch = db.batch();

  for (const [symbol, docIds] of bySymbol.entries()) {
    try {
      const price = await fetchLivePrice(symbol);
      docIds.forEach((id) => {
        batch.update(db.collection("positions").doc(id), { currentPrice: price });
      });
      updated += docIds.length;
    } catch (err) {
      logger.warn(`Price fetch failed for ${symbol}: ${err.message}`);
      failed += docIds.length;
    }
  }

  await batch.commit();
  logger.info(`Price update done. updated=${updated} failed=${failed}`);
  return { updated, failed };
}

// ── Scheduled trigger: runs automatically every 5 minutes ────────────────
exports.updatePricesScheduled = onSchedule("every 5 minutes", async () => {
  await updateAllPrices();
});

// ── Manual HTTPS trigger: useful for testing on demand from a browser/curl
// without waiting for the schedule. Visit the deployed URL to trigger it.
exports.updatePricesNow = onRequest(async (req, res) => {
  try {
    const result = await updateAllPrices();
    res.status(200).json(result);
  } catch (err) {
    logger.error(err);
    res.status(500).json({ error: err.message });
  }
});
