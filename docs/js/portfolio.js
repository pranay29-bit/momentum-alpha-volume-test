import { db, auth, login } from "./firebase.js";

import {
  collection,
  addDoc,
  getDocs,
  deleteDoc,
  doc
} from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

// Local in-memory cache of the user's positions. We only hit Firestore for a
// full read once (right after login). After that, every add/delete updates
// this cache + the DOM directly, instead of re-querying the whole collection
// on every action — that round trip was what made the page feel slow.
let positions = [];
let positionsRef = null;

document.getElementById("loginBtn").onclick = async () => {
  await login();
  positionsRef = collection(db, "users", auth.currentUser.uid, "positions");
  await loadPositions();
};

document.getElementById("addBtn").onclick = addPosition;

document.getElementById("portfolioSize").addEventListener("input", updateSummary);
document.getElementById("riskPct").addEventListener("input", updateSummary);

async function addPosition() {
  if (!auth.currentUser) {
    alert("Login first");
    return;
  }

  const portfolio = Number(document.getElementById("portfolioSize").value);
  const riskPct = Number(document.getElementById("riskPct").value);
  const entry = Number(document.getElementById("entry").value);
  const stop = Number(document.getElementById("stop").value);
  const symbol = document.getElementById("symbol").value.trim();

  if (!symbol) {
    alert("Enter a symbol");
    return;
  }
  if (entry <= stop) {
    alert("Entry must be above stop");
    return;
  }

  const riskAmount = (portfolio * riskPct) / 100;
  const riskPerShare = entry - stop;
  const qty = Math.floor(riskAmount / riskPerShare);

  const addBtn = document.getElementById("addBtn");
  addBtn.disabled = true;
  addBtn.textContent = "Adding…";

  try {
    const data = { symbol, entry, stop, qty, riskPerShare, createdAt: Date.now() };
    const ref = await addDoc(positionsRef, data);

    // Optimistic update: append locally instead of re-fetching everything.
    positions.push({ id: ref.id, ...data });
    renderRow({ id: ref.id, ...data });
    updateSummary();

    document.getElementById("symbol").value = "";
    document.getElementById("entry").value = "";
    document.getElementById("stop").value = "";
  } catch (err) {
    console.error(err);
    alert("Could not add position. Please try again.");
  } finally {
    addBtn.disabled = false;
    addBtn.textContent = "+ Add Position";
  }
}

async function loadPositions() {
  if (!auth.currentUser) return;

  const tbody = document.getElementById("positionsTable");
  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--subtle)">Loading…</td></tr>`;

  const snap = await getDocs(positionsRef);

  positions = snap.docs.map(d => ({ id: d.id, ...d.data() }));

  tbody.innerHTML = "";
  positions.forEach(renderRow);
  updateSummary();
}

function renderRow(p) {
  const tbody = document.getElementById("positionsTable");
  const tr = document.createElement("tr");
  tr.dataset.id = p.id;
  tr.innerHTML = `
    <td>${p.symbol}</td>
    <td>${p.entry}</td>
    <td>${p.stop}</td>
    <td>${p.qty}</td>
    <td>${p.riskPerShare.toFixed(2)}</td>
    <td><button data-id="${p.id}" class="deleteBtn">❌</button></td>
  `;
  tbody.appendChild(tr);
  tr.querySelector(".deleteBtn").onclick = () => deletePosition(p.id, tr);
}

async function deletePosition(id, rowEl) {
  if (!auth.currentUser) return;

  rowEl.style.opacity = "0.4";

  try {
    await deleteDoc(doc(db, "users", auth.currentUser.uid, "positions", id));

    // Optimistic update: remove locally instead of re-fetching everything.
    positions = positions.filter(p => p.id !== id);
    rowEl.remove();
    updateSummary();
  } catch (err) {
    console.error(err);
    rowEl.style.opacity = "1";
    alert("Could not delete position. Please try again.");
  }
}

function updateSummary() {
  const portfolio = Number(document.getElementById("portfolioSize").value || 0);

  const totalRisk = positions.reduce((sum, p) => sum + p.qty * p.riskPerShare, 0);

  if (portfolio > 0) {
    const riskPct = (totalRisk / portfolio) * 100;
    document.getElementById("initialRisk").textContent = riskPct.toFixed(2) + "%";
    document.getElementById("heat").textContent = riskPct.toFixed(2) + "%";
  } else {
    document.getElementById("initialRisk").textContent = "0%";
    document.getElementById("heat").textContent = "0%";
  }
}
