import { initializeApp }
from "https://www.gstatic.com/firebasejs/11.9.0/firebase-app.js";

import {
  getFirestore
}
from "https://www.gstatic.com/firebasejs/11.9.0/firebase-firestore.js";

import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  onAuthStateChanged
}
from "https://www.gstatic.com/firebasejs/11.9.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyAvvNeoppjA5xIzjOiLkBI7-OlgSwQhXu8",
  authDomain: "momentum-alpha-volume-67cb8.firebaseapp.com",
  projectId: "momentum-alpha-volume-67cb8",
  storageBucket: "momentum-alpha-volume-67cb8.firebasestorage.app",
  messagingSenderId: "726943825444",
  appId: "1:726943825444:web:0a77e1668f161ec60822b1",
  measurementId: "G-27K7DB5WK8"
};

export const app = initializeApp(firebaseConfig);
export const db = getFirestore(app);
export const auth = getAuth(app);

export async function login() {
  const provider = new GoogleAuthProvider();
  await signInWithPopup(auth, provider);
}

export async function logout() {
  await signOut(auth);
}

export { onAuthStateChanged };
