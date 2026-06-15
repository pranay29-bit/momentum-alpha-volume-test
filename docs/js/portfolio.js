import {
db,
auth,
login
}
from "./firebase.js";

import {
collection,
addDoc,
getDocs,
deleteDoc,
doc
}
from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

document.getElementById("loginBtn")
.onclick = async () => {

await login();

loadPositions();

};

document.getElementById("addBtn")
.onclick = addPosition;

async function addPosition(){

if(!auth.currentUser){

alert("Login first");

return;

}

const portfolio =
Number(document.getElementById("portfolioSize").value);

const riskPct =
Number(document.getElementById("riskPct").value);

const entry =
Number(document.getElementById("entry").value);

const stop =
Number(document.getElementById("stop").value);

const symbol =
document.getElementById("symbol").value.trim();

if(entry <= stop){

alert("Entry must be above stop");

return;

}

const riskAmount =
portfolio * riskPct / 100;

const riskPerShare =
entry - stop;

const qty =
Math.floor(riskAmount / riskPerShare);

await addDoc(

collection(
db,
"users",
auth.currentUser.uid,
"positions"
),

{
symbol,
entry,
stop,
qty,
riskPerShare,
createdAt: Date.now()
}

);

loadPositions();

}

async function loadPositions(){

if(!auth.currentUser) return;

const tbody =
document.getElementById(
"positionsTable"
);

tbody.innerHTML = "";

const snap =
await getDocs(

collection(
db,
"users",
auth.currentUser.uid,
"positions"
)

);

let totalRisk = 0;

snap.forEach(d => {

const p = d.data();

totalRisk +=
p.qty * p.riskPerShare;

const tr =
document.createElement("tr");

tr.innerHTML = `
<td>${p.symbol}</td>
<td>${p.entry}</td>
<td>${p.stop}</td>
<td>${p.qty}</td>
<td>${p.riskPerShare.toFixed(2)}</td>
<td>
<button
data-id="${d.id}"
class="deleteBtn">
❌
</button>
</td>
`;

tbody.appendChild(tr);

});

const portfolio =
Number(
document.getElementById(
"portfolioSize"
).value || 0
);

if(portfolio > 0){

const riskPct =
(totalRisk / portfolio) * 100;

document.getElementById(
"initialRisk"
).textContent =
riskPct.toFixed(2) + "%";

}

attachDeleteEvents();

}

function attachDeleteEvents(){

document
.querySelectorAll(".deleteBtn")
.forEach(btn => {

btn.onclick =
async () => {

await deleteDoc(

doc(
db,
"users",
auth.currentUser.uid,
"positions",
btn.dataset.id
)

);

loadPositions();

};

});

}
