import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";

const config = window.REVIEW_CONFIG;
export const firebaseApp = initializeApp(config.firebase);
const auth = getAuth(firebaseApp);
const googleProvider = new GoogleAuthProvider();

export function watchAuth(callback) {
  return onAuthStateChanged(auth, callback);
}

export async function signInWithEmail(email, password) {
  return signInWithEmailAndPassword(auth, email.trim(), password);
}

export async function createAccountWithEmail(email, password) {
  return createUserWithEmailAndPassword(auth, email.trim(), password);
}

export async function signInWithGoogle() {
  return signInWithPopup(auth, googleProvider);
}

export async function signOutUser() {
  return signOut(auth);
}

export async function currentIdToken(forceRefresh = false) {
  const user = auth.currentUser;
  if (!user) {
    throw new Error("Sign-in is required.");
  }
  return user.getIdToken(forceRefresh);
}
