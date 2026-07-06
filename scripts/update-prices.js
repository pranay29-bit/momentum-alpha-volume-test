// scripts/update-prices.js
//
// Standalone script (no Cloud Functions, no Blaze plan needed) that:
//   1. Authenticates to Firestore using a service account key.
//   2. Reads every doc in the "positions" collection.
//   3. Fetches a live price per unique symbol from Yahoo Finance,
//      handling the crumb/cookie handshake Yahoo now requires.
//   4. Writes currentPrice back to Firestore.
//
// Run manually with:  node scripts/update-prices.js
// Run on a schedule via the GitHub Actions workflow in
// .github/workflows/update-prices.yml

const admin = require("firebase-admin");

// The service account JSON is provided as a GitHub Actions secret and
// written to this env var as a string (see the workflow file). For local
// testing, you can instead point GOOGLE_APPLICATION_CREDENTIALS at a
// downloaded service-account.json file and skip this block.
if (!admin.apps.length) {
  if (process.env.FIREBASE_SERVICE_ACCOUNT) {
    const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT);
    admin.initializeApp({
      credential: admin.credential.cert(serviceAccount)
    });
  } else {
    // Falls back to GOOGLE_APPLICATION_CREDENTIALS env var pointing at a
    // local JSON key file, for testing on your own machine.
    admin.initializeApp();
  }
}

const db = admin.firestore();

// ── Yahoo Finance crumb/cookie handshake ──────────────────────────────────
let cachedCrumb = null;
let cachedCookie = null;

async function getCrumbAndCookie() {
  if (cachedCrumb && cachedCookie) return { crumb: cachedCrumb, cookie: cachedCookie };

  const cookieRes = await fetch("https://fc.yahoo.com", {
    headers: { "User-Agent": "Mozilla/5.0" }
  });
  const setCookie = cookieRes.headers.get("set-cookie") || "";
  const cookie = setCookie.split(";")[0];

  const crumbRes = await fetch("https://query2.finance.yahoo.com/v1/test/getcrumb", {
    headers: { "User-Agent": "Mozilla/5.0", "Cookie": cookie }
  });
  const crumb = await crumbRes.text();

  if (!crumb || crumb.includes("<html")) {
    throw new Error("Failed to obtain Yahoo crumb token");
  }

  cachedCrumb = crumb;
  cachedCookie = cookie;
  return { crumb, cookie };
}

async function fetchLivePrice(symbol) {
  const { crumb, cookie } = await getCrumbAndCookie();

  const url = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
              `?interval=1m&crumb=${encodeURIComponent(crumb)}`;

  const res = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0", "Cookie": cookie }
  });

  if (!res.ok) throw new Error(`Yahoo returned HTTP ${res.status} for ${symbol}`);

  const data = await res.json();
  const price = data?.chart?.result?.[0]?.meta?.regularMarketPrice;

  if (typeof price !== "number" || price <= 0) {
    throw new Error(`No valid price in response for ${symbol}`);
  }

  return price;
}

async function updateAllPrices() {
  // IMPORTANT: positions live under users/{uid}/positions, but the app
  // never explicitly creates a users/{uid} parent document — it only ever
  // writes into the subcollection. Firestore won't list a parent doc in a
  // plain collection("users").get() query unless that doc itself was
  // written at some point, so we use a collectionGroup query instead,
  // which finds every "positions" subcollection across all users
  // regardless of whether their parent doc exists.
  const positionsSnap = await db.collectionGroup("positions").get();

  if (positionsSnap.empty) {
    console.log("No open positions — nothing to update.");
    return;
  }

  const bySymbol = new Map(); // symbol -> [{uid, docId}]

  positionsSnap.forEach((posDoc) => {
    // Skip anything that isn't actually under users/{uid}/positions —
    // e.g. leftover docs in an old top-level "positions" collection from
    // a previous version of this app. Those have no grandparent, so
    // parent.parent is null instead of a uid.
    const uid = posDoc.ref.parent.parent?.id;
    if (!uid) {
      console.warn(`Skipping ${posDoc.ref.path} — not under users/{uid}/positions`);
      return;
    }

    const symbol = posDoc.data().symbol;
    if (!bySymbol.has(symbol)) bySymbol.set(symbol, []);
    bySymbol.get(symbol).push({ uid, docId: posDoc.id });
  });

  let updated = 0;
  let failed = 0;
  const batch = db.batch();

  for (const [symbol, refs] of bySymbol.entries()) {
    try {
      const price = await fetchLivePrice(symbol);
      refs.forEach(({ uid, docId }) => {
        const ref = db.collection("users").doc(uid).collection("positions").doc(docId);
        batch.update(ref, { currentPrice: price });
      });
      updated += refs.length;
      console.log(`✓ ${symbol}: ${price}`);
    } catch (err) {
      console.warn(`✗ ${symbol}: ${err.message}`);
      failed += refs.length;
    }
  }

  await batch.commit();
  console.log(`Done. updated=${updated} failed=${failed}`);
}

updateAllPrices()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("Fatal error:", err);
    process.exit(1);
  });
