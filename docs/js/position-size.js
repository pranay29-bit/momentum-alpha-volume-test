import { db, auth, login, logout, onAuthStateChanged } from "./firebase.js";

import {
  collection,
  addDoc,
  doc,
  getDoc,
  setDoc,
  serverTimestamp
} from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

const loginBtn = document.getElementById("loginBtn");
const addBtn = document.getElementById("addBtn");
const addStatus = document.getElementById("addStatus");
const settingsStatus = document.getElementById("settingsStatus");

const portfolioSizeInput = document.getElementById("portfolioSize");
const riskTypeSelect = document.getElementById("riskType");
const riskValueInput = document.getElementById("riskValue");
const symbolInput = document.getElementById("symbol");
const dateBoughtInput = document.getElementById("dateBought");
const entryInput = document.getElementById("entry");
const stopInput = document.getElementById("stop");

// Default Date Bought to today, but the user can change it freely.
dateBoughtInput.value = new Date().toISOString().slice(0, 10);

const previewBox = document.getElementById("previewBox");
const previewRiskAmount = document.getElementById("previewRiskAmount");
const previewRiskPerShare = document.getElementById("previewRiskPerShare");
const previewRiskPct = document.getElementById("previewRiskPct");
const previewQty = document.getElementById("previewQty");
const previewCapital = document.getElementById("previewCapital");

let settingsSaveTimer = null;

loginBtn.onclick = async () => {
  if (auth.currentUser) {
    await logout();
  } else {
    try {
      await login();
    } catch (err) {
      console.error(err);
      alert("Login failed. Please try again.");
    }
  }
};

onAuthStateChanged(auth, async (user) => {
  if (user) {
    loginBtn.textContent = `Logout (${user.displayName || user.email})`;
    await loadSettings(user.uid);
  } else {
    loginBtn.textContent = "Login with Google";
  }
});

// ── Persistent settings: portfolio size & risk type/value stay fixed
// until you explicitly change them — saved to Firestore so they also
// show up on the Position Tracker page and persist across sessions. ─────
async function loadSettings(uid) {
  try {
    const snap = await getDoc(doc(db, "users", uid));
    if (snap.exists()) {
      const data = snap.data();
      if (data.portfolioSize) portfolioSizeInput.value = data.portfolioSize;
      if (data.riskType) riskTypeSelect.value = data.riskType;
      if (data.riskValue) riskValueInput.value = data.riskValue;
      settingsStatus.textContent = "Loaded your saved portfolio settings.";
      calculate();
    }
  } catch (err) {
    console.error(err);
  }
}

function saveSettingsDebounced() {
  if (!auth.currentUser) return;
  clearTimeout(settingsSaveTimer);
  settingsStatus.textContent = "Saving…";
  settingsSaveTimer = setTimeout(async () => {
    try {
      await setDoc(doc(db, "users", auth.currentUser.uid), {
        portfolioSize: Number(portfolioSizeInput.value) || 0,
        riskType: riskTypeSelect.value,
        riskValue: Number(riskValueInput.value) || 0,
        updatedAt: serverTimestamp()
      }, { merge: true });
      settingsStatus.textContent = "Saved — this stays fixed until you change it again.";
    } catch (err) {
      console.error(err);
      settingsStatus.textContent = "Could not save settings.";
    }
  }, 600); // debounce so we don't write on every keystroke
}

[portfolioSizeInput, riskTypeSelect, riskValueInput].forEach((el) => {
  el.addEventListener("input", saveSettingsDebounced);
});

// ── Live calculation, recomputed on every keystroke ──────────────────────
function calculate() {
  const portfolio = Number(portfolioSizeInput.value);
  const riskType = riskTypeSelect.value; // "percent" | "absolute"
  const riskValue = Number(riskValueInput.value);
  const entry = Number(entryInput.value);
  const stop = Number(stopInput.value);

  if (!(portfolio > 0) || !(riskValue > 0) || !(entry > stop)) {
    previewBox.style.display = "none";
    return null;
  }

  const riskAmount = riskType === "percent"
    ? (portfolio * riskValue) / 100
    : riskValue;

  const riskPerShare = entry - stop;
  const riskPct = (riskPerShare / entry) * 100; // Entry-SL distance, in %
  const qty = Math.floor(riskAmount / riskPerShare);
  const capitalRequired = qty * entry;

  previewBox.style.display = "flex";
  previewRiskAmount.textContent = formatINR(riskAmount);
  previewRiskPerShare.textContent = riskPerShare.toFixed(2);
  previewRiskPct.textContent = riskPct.toFixed(2) + "%";
  previewQty.textContent = qty;
  previewCapital.textContent = formatINR(capitalRequired);

  return { riskAmount, riskPerShare, riskPct, qty, capitalRequired };
}

[portfolioSizeInput, riskTypeSelect, riskValueInput, entryInput, stopInput]
  .forEach((el) => el.addEventListener("input", calculate));

addBtn.onclick = async () => {
  if (!auth.currentUser) {
    alert("Login first");
    return;
  }

  const symbol = symbolInput.value.trim();
  if (!symbol) {
    alert("Enter a symbol");
    return;
  }
  const dateBought = dateBoughtInput.value;
  if (!dateBought) {
    alert("Enter the date you bought this position");
    return;
  }

  const result = calculate();
  if (!result) {
    alert("Enter a valid portfolio size, risk value, entry and stop loss (entry must be above stop).");
    return;
  }
  if (result.qty <= 0) {
    alert("Calculated quantity is 0 — your risk value may be too small for this stop distance.");
    return;
  }

  addBtn.disabled = true;
  addBtn.textContent = "Adding…";
  addStatus.textContent = "";

  try {
    const positionsRef = collection(db, "users", auth.currentUser.uid, "positions");

    await addDoc(positionsRef, {
      symbol,
      dateBought,
      entry: Number(entryInput.value),
      stop: Number(stopInput.value),
      qty: result.qty,
      riskPerShare: result.riskPerShare,
      riskAmount: result.riskAmount,
      riskPct: result.riskPct,
      currentPrice: Number(entryInput.value),
      createdAt: serverTimestamp()
    });

    addStatus.textContent = `Added ${symbol} · Qty ${result.qty}. View it on the Position Tracker page.`;
    symbolInput.value = "";
    entryInput.value = "";
    stopInput.value = "";
    dateBoughtInput.value = new Date().toISOString().slice(0, 10);
    previewBox.style.display = "none";
  } catch (err) {
    console.error(err);
    addStatus.textContent = "Could not add position. Please try again.";
  } finally {
    addBtn.disabled = false;
    addBtn.textContent = "+ Add Position";
  }
};

function formatINR(n) {
  return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
