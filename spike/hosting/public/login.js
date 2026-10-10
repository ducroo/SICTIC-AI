import {
  watchAuth,
  signInWithEmail,
  createAccountWithEmail,
  signInWithGoogle,
} from "./auth-session.js";

const form = document.getElementById("login-form");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const emailSubmit = document.getElementById("email-submit");
const createAccount = document.getElementById("create-account");
const googleButton = document.getElementById("google");
const errorEl = document.getElementById("error");

function showError(message) {
  errorEl.hidden = !message;
  errorEl.textContent = message || "";
}

function setBusy(busy) {
  emailSubmit.disabled = busy;
  createAccount.disabled = busy;
  googleButton.disabled = busy;
}

function authErrorMessage(error) {
  const code = error && error.code ? String(error.code) : "";
  if (code === "auth/invalid-credential" || code === "auth/wrong-password" || code === "auth/user-not-found") {
    return "Email or password is incorrect.";
  }
  if (code === "auth/email-already-in-use") {
    return "An account with this email already exists. Sign in instead.";
  }
  if (code === "auth/weak-password") {
    return "Choose a password with at least 6 characters.";
  }
  if (code === "auth/invalid-email") {
    return "Enter a valid email address.";
  }
  if (code === "auth/popup-closed-by-user") {
    return "Google sign-in was cancelled.";
  }
  return (error && error.message) || "Sign-in failed.";
}

watchAuth((user) => {
  if (user) {
    window.location.replace("/");
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  setBusy(true);
  try {
    await signInWithEmail(emailInput.value, passwordInput.value);
    window.location.replace("/");
  } catch (error) {
    showError(authErrorMessage(error));
  } finally {
    setBusy(false);
  }
});

createAccount.addEventListener("click", async () => {
  showError("");
  setBusy(true);
  try {
    await createAccountWithEmail(emailInput.value, passwordInput.value);
    window.location.replace("/");
  } catch (error) {
    showError(authErrorMessage(error));
  } finally {
    setBusy(false);
  }
});

googleButton.addEventListener("click", async () => {
  showError("");
  setBusy(true);
  try {
    await signInWithGoogle();
    window.location.replace("/");
  } catch (error) {
    showError(authErrorMessage(error));
  } finally {
    setBusy(false);
  }
});
