import { db, auth, login, logout, onAuthStateChanged } from "./firebase.js";

import {
  collection,
  doc,
  addDoc,
  getDoc,
  deleteDoc,
  updateDoc,
  query,
  orderBy,
  onSnapshot,
  serverTimestamp
} from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

let positions = [];
let bookedPositions = [];
let portfolioSize = 0;
let unsubOpen = null;
let unsubBooked = null;
let activeTab = "open"; // "open" | "booked"

const loginBtn = document.getElementById("loginBtn");
const settingsDisplay = document.getElementById("settingsDisplay");
const tabOpenBtn = document.getElementById("tabOpenBtn");
const tabBookedBtn = document.getElementById("tabBookedBtn");
const openPanel = document.getElementById("openPanel");
const bookedPanel = document.getElementById("bookedPanel");

const bookModalOverlay = document.getElementById("bookModalOverlay");
const bookModalSymbol = document.getElementById("bookModalSymbol");
const bookExitPrice = document.getElementById("bookExitPrice");
const bookDateSold = document.getElementById("bookDateSold");
const bookModalCancel = document.getElementById("bookModalCancel");
const bookModalConfirm = document.getElementById("bookModalConfirm");
let pendingBookPosition = null;

tabOpenBtn.onclick = () => switchTab("open");
tabBookedBtn.onclick = () => switchTab("booked");

function switchTab(tab) {
  activeTab = tab;
  tabOpenBtn.classList.toggle("active", tab === "open");
  tabBookedBtn.classList.toggle("active", tab === "booked");
  openPanel.style.display = tab === "open" ? "" : "none";
  bookedPanel.style.display = tab === "booked" ? "" : "none";
}

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
  if (unsubOpen) { unsubOpen(); unsubOpen = null; }
  if (unsubBooked) { unsubBooked(); unsubBooked = null; }

  if (user) {
    loginBtn.textContent = `Logout (${user.displayName || user.email})`;
    await loadSettings(user.uid);
    subscribeToPositions(user.uid);
    subscribeToBooked(user.uid);
  } else {
    loginBtn.textContent = "Login with Google";
    positions = [];
    bookedPositions = [];
    portfolioSize = 0;
    settingsDisplay.textContent = "Login to see your saved portfolio size & risk settings.";
    renderAll();
    renderBooked();
  }
});

async function loadSettings(uid) {
  try {
    const snap = await getDoc(doc(db, "users", uid));
    if (snap.exists()) {
      const data = snap.data();
      portfolioSize = Number(data.portfolioSize) || 0;
      const riskLabel = data.riskType === "percent"
        ? `${data.riskValue}% of portfolio`
        : `₹${Number(data.riskValue).toLocaleString("en-IN")} fixed`;
      settingsDisplay.textContent =
        `Portfolio Size: ₹${portfolioSize.toLocaleString("en-IN")} · Risk per trade: ${riskLabel} ` +
        `— set on the Position Size Calculator page.`;
    } else {
      settingsDisplay.textContent = "No saved settings yet — set your portfolio size & risk on the Position Size Calculator page.";
    }
  } catch (err) {
    console.error(err);
  }
}

function subscribeToPositions(uid) {
  const tbody = document.getElementById("positionsTable");
  tbody.innerHTML = `<tr><td colspan="12" style="text-align:center;color:var(--subtle)">Loading…</td></tr>`;

  const positionsRef = collection(db, "users", uid, "positions");
  const positionsQuery = query(positionsRef, orderBy("createdAt", "desc"));

  unsubOpen = onSnapshot(
    positionsQuery,
    (snap) => {
      positions = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
      renderAll();
    },
    (err) => {
      console.error(err);
      tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--subtle)">Could not load positions.</td></tr>`;
    }
  );
}

function subscribeToBooked(uid) {
  const tbody = document.getElementById("bookedTable");
  tbody.innerHTML = `<tr><td colspan="13" style="text-align:center;color:var(--subtle)">Loading…</td></tr>`;

  const bookedRef = collection(db, "users", uid, "bookedPositions");
  const bookedQuery = query(bookedRef, orderBy("dateSold", "desc"));

  unsubBooked = onSnapshot(
    bookedQuery,
    (snap) => {
      bookedPositions = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
      renderBooked();
    },
    (err) => {
      console.error(err);
      tbody.innerHTML = `<tr><td colspan="13" style="text-align:center;color:var(--subtle)">Could not load booked trades.</td></tr>`;
    }
  );
}

function renderAll() {
  const tbody = document.getElementById("positionsTable");
  tbody.innerHTML = "";

  if (positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="12"><div class="empty-state"><span class="icon">📭</span>No open positions yet — add one from the Position Size Calculator.</div></td></tr>`;
  } else {
    positions.forEach(renderRow);
  }
  updateSummary();
}

function metrics(entry, riskPerShare, qty, currentPrice) {
  const pnlPct = ((currentPrice - entry) / entry) * 100;
  const rMultiple = riskPerShare > 0 ? (currentPrice - entry) / riskPerShare : 0;
  const impactAbs = (currentPrice - entry) * qty;
  const impactPct = portfolioSize > 0 ? (impactAbs / portfolioSize) * 100 : 0;
  return { pnlPct, rMultiple, impactAbs, impactPct };
}

function positionMetrics(p) {
  const currentPrice = Number(p.currentPrice ?? p.entry);
  const entry = Number(p.entry);
  const riskPerShare = Number(p.riskPerShare);
  const qty = Number(p.qty);
  return { currentPrice, ...metrics(entry, riskPerShare, qty, currentPrice) };
}

function pnlClass(value) {
  if (value > 0.001) return "pnl-pos";
  if (value < -0.001) return "pnl-neg";
  return "pnl-flat";
}

function formatINR(n) {
  const sign = n < 0 ? "-" : "";
  return sign + "₹" + Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatDate(ts) {
  if (!ts) return "—";
  const d = typeof ts.toDate === "function" ? ts.toDate() : new Date(ts);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function renderRow(p) {
  const tbody = document.getElementById("positionsTable");
  const tr = document.createElement("tr");
  tr.dataset.id = p.id;

  const { currentPrice, pnlPct, rMultiple, impactAbs, impactPct } = positionMetrics(p);
  const riskPctDisplay = typeof p.riskPct === "number" ? p.riskPct.toFixed(2) + "%" : "—";

  tr.innerHTML = `
    <td>${escapeHtml(p.symbol)}</td>
    <td>${formatDate(p.dateBought)}</td>
    <td>
      ${p.entry}
      <input type="number" class="price-input entry-input" placeholder="override" data-id="${p.id}"/>
    </td>
    <td>${p.stop}</td>
    <td>${riskPctDisplay}</td>
    <td>
      ${p.qty}
      <input type="number" class="price-input qty-input" placeholder="override" data-id="${p.id}"/>
    </td>
    <td>
      ${currentPrice.toFixed(2)}
      <input type="number" class="price-input current-price-input" placeholder="override" data-id="${p.id}"/>
    </td>
    <td class="${pnlClass(pnlPct)}">${pnlPct.toFixed(2)}%</td>
    <td class="${pnlClass(rMultiple)}">${rMultiple.toFixed(2)}R</td>
    <td class="${pnlClass(impactAbs)}">${formatINR(impactAbs)} (${impactPct.toFixed(2)}%)</td>
    <td><button data-id="${p.id}" class="bookBtn" title="Book this position (move to Booked Positions)">✅</button></td>
    <td><button data-id="${p.id}" class="deleteBtn" title="Delete without booking">❌</button></td>
  `;
  tbody.appendChild(tr);

  const entryInput = tr.querySelector(".entry-input");
  entryInput.addEventListener("change", (e) =>
  updateEntry(p.id, e.target.value)
  );

  const qtyInput = tr.querySelector(".qty-input");
  qtyInput.addEventListener("change", (e) =>
  updateQty(p.id, e.target.value)
  );

  const currentPriceInput = tr.querySelector(".current-price-input");
  currentPriceInput.addEventListener("change", (e) =>
  updateCurrentPrice(p.id, e.target.value)
  );
  const delBtn = tr.querySelector(".deleteBtn");
  delBtn.onclick = () => deletePosition(p.id, tr);
  const bookBtn = tr.querySelector(".bookBtn");
  bookBtn.onclick = () => promptBookPosition(p);
}

async function updateEntry(id, value) {
  const entry = Number(value);

  if (!(entry > 0) || !Number.isFinite(entry) || !auth.currentUser) {
    alert("Please enter a valid entry price.");
    return;
  }

  try {
    await updateDoc(doc(db, "users", auth.currentUser.uid, "positions", id), { entry });
  } catch (err) {
    console.error(err);
    alert("Could not update entry price.");
  }
}

async function updateCurrentPrice(id, value) {
  const price = Number(value);
  if (!(price > 0) || !auth.currentUser) return;

  try {
    await updateDoc(doc(db, "users", auth.currentUser.uid, "positions", id), { currentPrice: price });
  } catch (err) {
    console.error(err);
    alert("Could not update price. Please try again.");
  }
}

async function updateQty(id, value) {
  const qty = Number(value);
  if (!(qty > 0) || !Number.isFinite(qty) || !auth.currentUser) {
    alert("Please enter a valid quantity greater than 0.");
    return;
  }

  try {
    await updateDoc(doc(db, "users", auth.currentUser.uid, "positions", id), { qty });
  } catch (err) {
    console.error(err);
    alert("Could not update quantity. Please try again.");
  }
}

async function deletePosition(id, rowEl) {
  if (!auth.currentUser) return;
  rowEl.style.opacity = "0.4";
  try {
    await deleteDoc(doc(db, "users", auth.currentUser.uid, "positions", id));
  } catch (err) {
    console.error(err);
    rowEl.style.opacity = "1";
    alert("Could not delete position. Please try again.");
  }
}

function promptBookPosition(p) {
  pendingBookPosition = p;
  bookModalSymbol.textContent = p.symbol;
  bookExitPrice.value = p.currentPrice ?? p.entry;
  bookDateSold.value = new Date().toISOString().slice(0, 10);
  bookModalOverlay.style.display = "flex";
  bookExitPrice.focus();
}

function closeBookModal() {
  bookModalOverlay.style.display = "none";
  pendingBookPosition = null;
}

bookModalCancel.onclick = closeBookModal;
bookModalOverlay.addEventListener("click", (e) => {
  if (e.target === bookModalOverlay) closeBookModal();
});

bookModalConfirm.onclick = () => {
  if (!pendingBookPosition) return;

  const exitPrice = Number(bookExitPrice.value);
  if (!(exitPrice > 0)) {
    alert("Please enter a valid exit price greater than 0.");
    return;
  }

  const dateSold = bookDateSold.value;
  if (!dateSold) {
    alert("Please select the date you sold.");
    return;
  }

  const p = pendingBookPosition;
  closeBookModal();
  bookPosition(p, exitPrice, dateSold);
};

async function bookPosition(p, exitPrice, dateSold) {
  if (!auth.currentUser) return;
  const uid = auth.currentUser.uid;

  const entry = Number(p.entry);
  const riskPerShare = Number(p.riskPerShare);
  const qty = Number(p.qty);
  const { pnlPct, rMultiple, impactAbs, impactPct } = metrics(entry, riskPerShare, qty, exitPrice);

  const bookedDoc = {
    symbol: p.symbol,
    entry: p.entry,
    stop: p.stop,
    exitPrice,
    riskPct: p.riskPct ?? null,
    riskPerShare: p.riskPerShare ?? null,
    qty: p.qty,
    pnlPct,
    rMultiple,
    impactAbs,
    impactPct,
    portfolioSizeAtBooking: portfolioSize,
    dateBought: p.dateBought ?? null,   // entered manually on the Calculator page
    dateSold,                            // entered manually when booking, e.g. "2026-06-30"
    bookedAt: serverTimestamp(),         // internal metadata only, not shown
  };

  try {
    await addDoc(collection(db, "users", uid, "bookedPositions"), bookedDoc);
    await deleteDoc(doc(db, "users", uid, "positions", p.id));
    switchTab("booked");
  } catch (err) {
    console.error(err);
    alert("Could not book this position. Please try again.");
  }
}

function renderBooked() {
  const tbody = document.getElementById("bookedTable");
  tbody.innerHTML = "";

  if (bookedPositions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="13"><div class="empty-state"><span class="icon">📒</span>No booked trades yet — click ✅ on an open position to log it here once closed.</div></td></tr>`;
  } else {
    bookedPositions.forEach(renderBookedRow);
  }
  updateBookedSummary();
}

function holdingDays(p) {
  if (!p.dateBought || !p.dateSold) return "—";
  const bought = typeof p.dateBought.toDate === "function" ? p.dateBought.toDate() : new Date(p.dateBought);
  const sold = typeof p.dateSold.toDate === "function" ? p.dateSold.toDate() : new Date(p.dateSold);
  if (isNaN(bought.getTime()) || isNaN(sold.getTime())) return "—";
  const days = Math.max(0, Math.round((sold - bought) / 86400000));
  return `${days}d`;
}

function renderBookedRow(p) {
  const tbody = document.getElementById("bookedTable");
  const tr = document.createElement("tr");
  tr.dataset.id = p.id;

  const riskPctDisplay = typeof p.riskPct === "number" ? p.riskPct.toFixed(2) + "%" : "—";

  tr.innerHTML = `
    <td>${escapeHtml(p.symbol)}</td>
    <td>${formatDate(p.dateBought)}</td>
    <td>${formatDate(p.dateSold)}</td>
    <td>${holdingDays(p)}</td>
    <td>${p.entry}</td>
    <td>${p.stop}</td>
    <td>${p.exitPrice}</td>
    <td>${riskPctDisplay}</td>
    <td>${p.qty}</td>
    <td class="${pnlClass(p.pnlPct)}">${Number(p.pnlPct).toFixed(2)}%</td>
    <td class="${pnlClass(p.rMultiple)}">${Number(p.rMultiple).toFixed(2)}R</td>
    <td class="${pnlClass(p.impactAbs)}">${formatINR(p.impactAbs)} (${Number(p.impactPct).toFixed(2)}%)</td>
    <td><button data-id="${p.id}" class="deleteBtn" title="Delete this trade record">❌</button></td>
  `;
  tbody.appendChild(tr);

  const delBtn = tr.querySelector(".deleteBtn");
  delBtn.onclick = () => deleteBooked(p.id, tr);
}

async function deleteBooked(id, rowEl) {
  if (!auth.currentUser) return;
  if (!window.confirm("Delete this booked trade record permanently? This cannot be undone.")) return;
  rowEl.style.opacity = "0.4";
  try {
    await deleteDoc(doc(db, "users", auth.currentUser.uid, "bookedPositions", id));
  } catch (err) {
    console.error(err);
    rowEl.style.opacity = "1";
    alert("Could not delete trade record. Please try again.");
  }
}

function updateSummary() {
  document.getElementById("openCount").textContent = positions.length;

  if (positions.length === 0) {
    document.getElementById("avgR").textContent = "0R";
    document.getElementById("winLoss").textContent = "0 / 0";
    document.getElementById("totalImpact").textContent = "₹0";
    document.getElementById("totalImpactPct").textContent = "0%";
    return;
  }

  let totalR = 0;
  let winners = 0;
  let losers = 0;
  let totalImpactAbs = 0;

  positions.forEach((p) => {
    const { rMultiple, impactAbs } = positionMetrics(p);
    totalR += rMultiple;
    totalImpactAbs += impactAbs;
    if (rMultiple > 0.001) winners++;
    else if (rMultiple < -0.001) losers++;
  });

  const totalImpactPct = portfolioSize > 0 ? (totalImpactAbs / portfolioSize) * 100 : 0;

  document.getElementById("avgR").textContent = (totalR / positions.length).toFixed(2) + "R";
  document.getElementById("winLoss").textContent = `${winners} / ${losers}`;

  const totalImpactEl = document.getElementById("totalImpact");
  totalImpactEl.textContent = formatINR(totalImpactAbs);
  totalImpactEl.className = pnlClass(totalImpactAbs);

  const totalImpactPctEl = document.getElementById("totalImpactPct");
  totalImpactPctEl.textContent = totalImpactPct.toFixed(2) + "%";
  totalImpactPctEl.className = pnlClass(totalImpactPct);
}

function updateBookedSummary() {
  document.getElementById("bookedCount").textContent = bookedPositions.length;

  if (bookedPositions.length === 0) {
    document.getElementById("bookedAvgR").textContent = "0R";
    document.getElementById("bookedWinRate").textContent = "0%";
    document.getElementById("bookedTotalPnl").textContent = "₹0";
    document.getElementById("bookedTotalPnlPct").textContent = "0%";
    return;
  }

  let totalR = 0;
  let winners = 0;
  let totalImpactAbs = 0;
  let totalImpactPct = 0;

  bookedPositions.forEach((p) => {
    totalR += Number(p.rMultiple) || 0;
    totalImpactAbs += Number(p.impactAbs) || 0;
    totalImpactPct += Number(p.impactPct) || 0;
    if (Number(p.rMultiple) > 0.001) winners++;
  });

  const winRate = (winners / bookedPositions.length) * 100;

  document.getElementById("bookedAvgR").textContent = (totalR / bookedPositions.length).toFixed(2) + "R";
  document.getElementById("bookedWinRate").textContent = winRate.toFixed(0) + "%";

  const totalPnlEl = document.getElementById("bookedTotalPnl");
  totalPnlEl.textContent = formatINR(totalImpactAbs);
  totalPnlEl.className = pnlClass(totalImpactAbs);

  const totalPnlPctEl = document.getElementById("bookedTotalPnlPct");
  totalPnlPctEl.textContent = totalImpactPct.toFixed(2) + "%";
  totalPnlPctEl.className = pnlClass(totalImpactPct);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

switchTab("open");
