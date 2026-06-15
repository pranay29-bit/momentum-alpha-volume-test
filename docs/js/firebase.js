import { initializeApp }
from "https://www.gstatic.com/firebasejs/11.9.0/firebase-app.js";

import {
getFirestore
}
from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

import {
getAuth,
GoogleAuthProvider,
signInWithPopup
}
from "https://www.gstatic.com/firebasejs/11.9.0/firebase-auth.js";

const firebaseConfig = {
apiKey: "YOUR_API_KEY",
authDomain: "YOUR_PROJECT.firebaseapp.com",
projectId: "YOUR_PROJECT",
storageBucket: "YOUR_PROJECT.appspot.com",
messagingSenderId: "XXXX",
appId: "XXXX"
};

export const app =
initializeApp(firebaseConfig);

export const db =
getFirestore(app);

export const auth =
getAuth(app);

export async function login(){

const provider =
new GoogleAuthProvider();

await signInWithPopup(
auth,
provider
);

}
