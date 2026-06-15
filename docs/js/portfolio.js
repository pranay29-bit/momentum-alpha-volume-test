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

const addBtn =
document.getElementById("addBtn");

addBtn.onclick =
async () => {

if(!auth.currentUser){

await login();

}

const portfolio =
Number(
document.getElementById(
"portfolioSize"
).value
);

const riskPct =
Number(
document.getElementById(
"riskPct"
).value
);

const entry =
Number(
document.getElementById(
"entry"
).value
);

const stop =
Number(
document.getElementById(
"stop"
).value
);

const symbol =
document.getElementById(
"symbol"
).value;

const riskAmount =
portfolio *
riskPct /
100;

const qty =
Math.floor(
riskAmount /
(entry-stop)
);

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
qty
}

);

loadPositions();

};
