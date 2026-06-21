# Server-side live price updates — setup guide

This replaces all client-side price fetching with a Cloud Function that
runs on Google's servers every 5 minutes, fetches NSE prices from Yahoo
Finance (handling the crumb/cookie handshake properly), and writes them
straight into Firestore using admin privileges.

## Why this fixes the "incorrect prices" problem

Yahoo's chart API now requires a session cookie + crumb token from a
separate handshake call before it returns real data — without it, Yahoo
silently returns stale/wrong values instead of an error. Browser-based
fetches through a public CORS proxy can't carry that cookie/crumb
properly. Running the handshake + fetch server-side, where cookies behave
normally, fixes this at the root.

## One-time setup on your machine

1. **Install Node.js** (v20 LTS) if you don't have it: https://nodejs.org
2. **Install the Firebase CLI**:
   ```
   npm install -g firebase-tools
   ```
3. **Log in**:
   ```
   firebase login
   ```
4. **In your repo root**, place the files from this delivery at these paths:
   ```
   firebase.json                  (repo root — merge with any existing one)
   functions/index.js
   functions/package.json
   ```
   If you already have a `firebase.json` (e.g. for Hosting), just add the
   `"functions"` and `"firestore"` keys shown in the one provided here into
   your existing file rather than overwriting it.
5. **Set the default project** (only needed once):
   ```
   firebase use --add
   ```
   and pick `momentum-alpha-volume-test` when prompted.
6. **Install function dependencies**:
   ```
   cd functions
   npm install
   cd ..
   ```
7. **Deploy**:
   ```
   firebase deploy --only functions
   ```

That's it — `updatePricesScheduled` will now run automatically every 5
minutes, no matter who has the page open or not.

## Testing it on demand (without waiting 5 minutes)

The deploy output will print a URL for `updatePricesNow`, something like:
```
https://us-central1-momentum-alpha-volume-test.cloudfunctions.net/updatePricesNow
```
Open that URL in a browser (or `curl` it) to trigger the update
immediately and see a JSON result like `{"updated": 6, "failed": 0}`.

To debug a specific failure, check the function logs:
```
firebase functions:log
```
This will show exactly which symbol failed and why (e.g. wrong suffix,
delisted, Yahoo rate-limited).

## Cost note

Cloud Functions on the Spark (free) plan have a monthly quota; scheduled
functions need the **Blaze (pay-as-you-go)** plan to run at all, but at
this volume (one job every 5 min, a handful of HTTP calls) you'll stay
comfortably within the free tier of Blaze's usage allowances — you won't
be charged anything meaningful unless usage grows dramatically. Firebase
will prompt you to upgrade to Blaze when you try to deploy a scheduled
function if you haven't already.

## Files changed on the frontend

`js/position-tracker.js` no longer does any browser-side fetching — it
just listens to Firestore via `onSnapshot`, same as before, and displays
whatever price the Cloud Function (or a manual override) last wrote.
