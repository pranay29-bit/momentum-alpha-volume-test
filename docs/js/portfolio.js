import { db, auth, login, logout, onAuthStateChanged } from "./firebase.js";

import {
  collection,
  addDoc,
  deleteDoc,
  doc,
  query,
  orderBy,
  onSnapshot,
  serverTimestamp
} from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

// Everyone reads/writes the SAME collection now, instead of a private
// users/{uid}/positions subcollection. Each doc carries ownerUid/ownerName
// so we know who added it and who's allowed to delete it.
const positionsRef = collection(db, "positions");
const positionsQuery = query(positionsRef, orderBy("createdAt", "desc"));

let positions = [];
let unsubscribe = null;

const loginBtn = document.getElementById("loginBtn");
const logoutBtn = document.getElementById("logoutBtn");
const addBtn = document.getElementById("addBtn");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const loginStatus = document.getElementById("loginStatus");

loginBtn.onclick = async () => {
  const email = emailInput.value.trim();
  const password = passwordInput.value;

  if (!email || !password) {
    loginStatus.textContent = "Enter email and password.";
    return;
  }

  loginBtn.disabled = true;
  loginBtn.textContent = "Logging in…";
  loginStatus.textContent = "";

  try {
    await login(email, password);
    passwordInput.value = "";
  } catch (err) {
    console.error(err);
    loginStatus.textContent = "Login failed. Check your email/password.";
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = "Login";
  }
};

logoutBtn.onclick = async () => {
  await logout();
};

// onAuthStateChanged fires on login, on logout, and on page load if a
// session already exists — this replaces the old "subscribe only after
// clicking login" flow and avoids creating duplicate listeners.
onAuthStateChanged(auth, (user) => {
  if (unsubscribe) {
    unsubscribe();
    unsubscribe = null;
  }

  if (user) {
    loginBtn.style.display = "none";
    logoutBtn.style.display = "";
    emailInput.style.display = "none";
    passwordInput.style.display = "none";
    loginStatus.textContent = `Logged in as ${user.email}`;
    subscribeToPositions();
  } else {
    loginBtn.style.display = "";
    logoutBtn.style.display = "none";
    emailInput.style.display = "";
    passwordInput.style.display = "";
    loginStatus.textContent = "";
    positions = [];
    renderAll();
  }
});

function subscribeToPositions() {
  const tbody = document.getElementById("positionsTable");
  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--subtle)">Loading…</td></tr>`;

  // Live listener: any add/edit/delete by ANY logged-in user pushes an
  // update here automatically. No polling, no manual refresh needed.
  unsubscribe = onSnapshot(
    positionsQuery,
    (snap) => {
      positions = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
      renderAll();
    },
    (err) => {
      console.error(err);
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--subtle)">Could not load positions.</td></tr>`;
    }
  );
}

addBtn.onclick = addPosition;
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
  if (!(entry > stop)) {
    alert("Entry must be above stop");
    return;
  }
  if (!(portfolio > 0) || !(riskPct > 0)) {
    alert("Set a valid portfolio size and risk % first");
    return;
  }

  const riskAmount = (portfolio * riskPct) / 100;
  const riskPerShare = entry - stop;
  const qty = Math.floor(riskAmount / riskPerShare);

  addBtn.disabled = true;
  addBtn.textContent = "Adding…";

  try {
    const data = {
      symbol,
      entry,
      stop,
      qty,
      riskPerShare,
      ownerUid: auth.currentUser.uid,
      ownerName: auth.currentUser.email,
      createdAt: serverTimestamp()
    };
    // No optimistic local push needed anymore — the onSnapshot listener
    // above will receive this write back (including from the server) and
    // re-render automatically, for us AND everyone else watching.
    await addDoc(positionsRef, data);

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

function renderAll() {
  const tbody = document.getElementById("positionsTable");
  tbody.innerHTML = "";

  if (positions.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--subtle)">No open positions</td></tr>`;
  } else {
    positions.forEach(renderRow);
  }
  updateSummary();
}

function renderRow(p) {
  const tbody = document.getElementById("positionsTable");
  const tr = document.createElement("tr");
  tr.dataset.id = p.id;

  const canDelete = auth.currentUser && p.ownerUid === auth.currentUser.uid;

  tr.innerHTML = `
    <td>${escapeHtml(p.symbol)} <span style="color:var(--subtle);font-size:0.8em">(${escapeHtml(p.ownerName || "unknown")})</span></td>
    <td>${p.entry}</td>
    <td>${p.stop}</td>
    <td>${p.qty}</td>
    <td>${Number(p.riskPerShare).toFixed(2)}</td>
    <td>${canDelete ? `<button data-id="${p.id}" class="deleteBtn">❌</button>` : ""}</td>
  `;
  tbody.appendChild(tr);

  const delBtn = tr.querySelector(".deleteBtn");
  if (delBtn) delBtn.onclick = () => deletePosition(p.id, tr);
}

async function deletePosition(id, rowEl) {
  if (!auth.currentUser) return;

  rowEl.style.opacity = "0.4";

  try {
    // Firestore security rules (see firestore.rules) double-check that
    // only the owner can delete — this client check is just for UX.
    await deleteDoc(doc(db, "positions", id));
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

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}
