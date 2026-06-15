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
apiKey: "AIzaSyAEiHgA339Dtry7r5mL2zo4bXU_N9cLyjA",
authDomain: "momentum-alpha-volume-test.firebaseapp.com",
projectId: "momentum-alpha-volume-test",
storageBucket: "momentum-alpha-volume-test.firebasestorage.app",
messagingSenderId: "391686611939",
appId: "1:391686611939:web:a5b1fac37c80a43d97f6d6",
measurementId: "G-MCHKXZRP0E"
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
