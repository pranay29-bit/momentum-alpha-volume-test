import { db, auth, login, logout, onAuthStateChanged } from "./firebase.js";

import {
  collection,
  addDoc,
  serverTimestamp
} from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

const positionsRef = collection(db, "positions");

const loginBtn = document.getElementById("loginBtn");
const addBtn = document.getElementById("addBtn");
const addStatus = document.getElementById("addStatus");

const portfolioSizeInput = document.getElementById("portfolioSize");
const riskTypeSelect = document.getElementById("riskType");
const riskValueInput = document.getElementById("riskValue");
const symbolInput = document.getElementById("symbol");
const entryInput = document.getElementById("entry");
const stopInput = document.getElementById("stop");

const previewBox = document.getElementById("previewBox");
const previewRiskAmount = document.getElementById("previewRiskAmount");
const previewRiskPerShare = document.getElementById("previewRiskPerShare");
const previewQty = document.getElementById("previewQty");
const previewCapital = document.getElementById("previewCapital");

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

onAuthStateChanged(auth, (user) => {
  loginBtn.textContent = user
    ? `Logout (${user.displayName || user.email})`
    : "Login with Google";
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
  const qty = Math.floor(riskAmount / riskPerShare);
  const capitalRequired = qty * entry;

  previewBox.style.display = "flex";
  previewRiskAmount.textContent = formatINR(riskAmount);
  previewRiskPerShare.textContent = riskPerShare.toFixed(2);
  previewQty.textContent = qty;
  previewCapital.textContent = formatINR(capitalRequired);

  return { riskAmount, riskPerShare, qty, capitalRequired };
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
    await addDoc(positionsRef, {
      symbol,
      entry: Number(entryInput.value),
      stop: Number(stopInput.value),
      qty: result.qty,
      riskPerShare: result.riskPerShare,
      riskAmount: result.riskAmount,
      currentPrice: Number(entryInput.value), // starting point; updated later on the Position Tracker page
      ownerUid: auth.currentUser.uid,
      ownerName: auth.currentUser.displayName || auth.currentUser.email,
      createdAt: serverTimestamp()
    });

    addStatus.textContent = `Added ${symbol} · Qty ${result.qty}. View it on the Position Tracker page.`;
    symbolInput.value = "";
    entryInput.value = "";
    stopInput.value = "";
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
