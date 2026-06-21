import { db, auth, login, logout, onAuthStateChanged } from "./firebase.js";

import {
  collection,
  doc,
  deleteDoc,
  updateDoc,
  query,
  orderBy,
  onSnapshot
} from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

const positionsRef = collection(db, "positions");
const positionsQuery = query(positionsRef, orderBy("createdAt", "desc"));

let positions = [];
let unsubscribe = null;

const loginBtn = document.getElementById("loginBtn");

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
  if (unsubscribe) {
    unsubscribe();
    unsubscribe = null;
  }

  if (user) {
    loginBtn.textContent = `Logout (${user.displayName || user.email})`;
    subscribeToPositions();
  } else {
    loginBtn.textContent = "Login with Google";
    positions = [];
    renderAll();
  }
});

function subscribeToPositions() {
  const tbody = document.getElementById("positionsTable");
  tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--subtle)">Loading…</td></tr>`;

  unsubscribe = onSnapshot(
    positionsQuery,
    (snap) => {
      positions = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
      renderAll();
    },
    (err) => {
      console.error(err);
      tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--subtle)">Could not load positions.</td></tr>`;
    }
  );
}

function renderAll() {
  const tbody = document.getElementById("positionsTable");
  tbody.innerHTML = "";

  if (positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--subtle)">No open positions</td></tr>`;
  } else {
    positions.forEach(renderRow);
  }
  updateSummary();
}

function metrics(p) {
  const currentPrice = Number(p.currentPrice ?? p.entry);
  const entry = Number(p.entry);
  const riskPerShare = Number(p.riskPerShare);

  const pnlPct = ((currentPrice - entry) / entry) * 100;
  const rMultiple = riskPerShare > 0 ? (currentPrice - entry) / riskPerShare : 0;

  return { currentPrice, pnlPct, rMultiple };
}

function pnlClass(value) {
  if (value > 0.001) return "pnl-pos";
  if (value < -0.001) return "pnl-neg";
  return "pnl-flat";
}

function renderRow(p) {
  const tbody = document.getElementById("positionsTable");
  const tr = document.createElement("tr");
  tr.dataset.id = p.id;

  const isOwner = auth.currentUser && p.ownerUid === auth.currentUser.uid;
  const { currentPrice, pnlPct, rMultiple } = metrics(p);

  tr.innerHTML = `
    <td>${escapeHtml(p.symbol)}</td>
    <td>${escapeHtml(p.ownerName || "unknown")}</td>
    <td>${p.entry}</td>
    <td>${p.stop}</td>
    <td>${p.qty}</td>
    <td>
      ${isOwner
        ? `<input type="number" class="price-input" value="${currentPrice}" data-id="${p.id}"/>`
        : currentPrice}
    </td>
    <td class="${pnlClass(pnlPct)}">${pnlPct.toFixed(2)}%</td>
    <td class="${pnlClass(rMultiple)}">${rMultiple.toFixed(2)}R</td>
    <td>${isOwner ? `<button data-id="${p.id}" class="deleteBtn">❌</button>` : ""}</td>
  `;
  tbody.appendChild(tr);

  if (isOwner) {
    const priceInput = tr.querySelector(".price-input");
    priceInput.addEventListener("change", () => updateCurrentPrice(p.id, priceInput.value));
    const delBtn = tr.querySelector(".deleteBtn");
    delBtn.onclick = () => deletePosition(p.id, tr);
  }
}

async function updateCurrentPrice(id, value) {
  const price = Number(value);
  if (!(price > 0)) return;

  try {
    // Listener re-renders this row (and the summary cards) for everyone
    // automatically once this write lands.
    await updateDoc(doc(db, "positions", id), { currentPrice: price });
  } catch (err) {
    console.error(err);
    alert("Could not update price. Please try again.");
  }
}

async function deletePosition(id, rowEl) {
  rowEl.style.opacity = "0.4";
  try {
    await deleteDoc(doc(db, "positions", id));
  } catch (err) {
    console.error(err);
    rowEl.style.opacity = "1";
    alert("Could not delete position. Please try again.");
  }
}

function updateSummary() {
  document.getElementById("openCount").textContent = positions.length;

  if (positions.length === 0) {
    document.getElementById("heat").textContent = "0%";
    document.getElementById("avgR").textContent = "0R";
    document.getElementById("winLoss").textContent = "0 / 0";
    return;
  }

  let totalRiskAmount = 0;
  let totalR = 0;
  let winners = 0;
  let losers = 0;

  positions.forEach((p) => {
    const { rMultiple } = metrics(p);
    totalRiskAmount += Number(p.riskAmount ?? p.qty * p.riskPerShare);
    totalR += rMultiple;
    if (rMultiple > 0.001) winners++;
    else if (rMultiple < -0.001) losers++;
  });

  // "Heat" here = sum of original risk amounts as committed capital-at-risk,
  // shown as a count rather than %, since we don't have each owner's
  // portfolio size on this shared page. Swap in a real % if you store
  // portfolio size per user.
  document.getElementById("heat").textContent = positions.length + " open";
  document.getElementById("avgR").textContent = (totalR / positions.length).toFixed(2) + "R";
  document.getElementById("winLoss").textContent = `${winners} / ${losers}`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}
