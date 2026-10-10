import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  signInWithPopup,
  signOut,
  sendEmailVerification,
  reload,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";

const config = window.REVIEW_CONFIG;
export const firebaseApp = initializeApp(config.firebase);
const auth = getAuth(firebaseApp);
const googleProvider = new GoogleAuthProvider();

function verificationActionSettings() {
  const origin = window.location.origin;
  return {
    url: `${origin}/login.html`,
    handleCodeInApp: false,
  };
}

export function watchAuth(callback) {
  return onAuthStateChanged(auth, callback);
}

export function emailIsVerified(user) {
  return Boolean(user && user.emailVerified);
}

export async function signInWithEmail(email, password) {
  return signInWithEmailAndPassword(auth, email.trim(), password);
}

export async function createAccountWithEmail(email, password) {
  return createUserWithEmailAndPassword(auth, email.trim(), password);
}

export async function sendVerificationEmail(user = auth.currentUser) {
  if (!user) {
    throw new Error("Sign-in is required.");
  }
  await sendEmailVerification(user, verificationActionSettings());
}

export async function reloadCurrentUser() {
  if (!auth.currentUser) {
    return null;
  }
  await reload(auth.currentUser);
  return auth.currentUser;
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
  if (!user.emailVerified) {
    throw new Error("Verify your email before using the review.");
  }
  return user.getIdToken(forceRefresh);
}
