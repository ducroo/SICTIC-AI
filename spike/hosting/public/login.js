import {
  watchAuth,
  signInWithEmail,
  createAccountWithEmail,
  signInWithGoogle,
  sendVerificationEmail,
  emailIsVerified,
  signOutUser,
  reloadCurrentUser,
} from "./auth-session.js";

const form = document.getElementById("login-form");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const emailSubmit = document.getElementById("email-submit");
const createAccount = document.getElementById("create-account");
const googleButton = document.getElementById("google");
const resendButton = document.getElementById("resend-verification");
const errorEl = document.getElementById("error");
const noticeEl = document.getElementById("notice");

let pendingVerificationUser = null;

function showError(message) {
  errorEl.hidden = !message;
  errorEl.textContent = message || "";
}

function showNotice(message, ok = false) {
  noticeEl.hidden = !message;
  noticeEl.textContent = message || "";
  noticeEl.classList.toggle("ok", Boolean(ok && message));
}

function setBusy(busy) {
  emailSubmit.disabled = busy;
  createAccount.disabled = busy;
  googleButton.disabled = busy;
  resendButton.disabled = busy;
}

function setResendVisible(visible) {
  resendButton.hidden = !visible;
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
  if (code === "auth/too-many-requests") {
    return "Too many attempts. Wait a moment, then try again.";
  }
  return (error && error.message) || "Sign-in failed.";
}

const unverifiedMessage =
  "Check your inbox for the verification link before you continue. It may be in spam. After you verify, sign in again.";

async function requireVerifiedSession(user) {
  if (emailIsVerified(user)) {
    pendingVerificationUser = null;
    setResendVisible(false);
    window.location.replace("/");
    return;
  }
  pendingVerificationUser = user;
  setResendVisible(true);
  showNotice(unverifiedMessage);
  await signOutUser();
}

watchAuth(async (user) => {
  if (!user) {
    return;
  }
  // Google accounts are already verified. Email/password must confirm the address.
  if (emailIsVerified(user)) {
    window.location.replace("/");
    return;
  }
  pendingVerificationUser = user;
  setResendVisible(true);
  showNotice(unverifiedMessage);
  await signOutUser();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  showNotice("");
  setBusy(true);
  try {
    const credential = await signInWithEmail(emailInput.value, passwordInput.value);
    const user = await reloadCurrentUser() || credential.user;
    await requireVerifiedSession(user);
  } catch (error) {
    showError(authErrorMessage(error));
  } finally {
    setBusy(false);
  }
});

createAccount.addEventListener("click", async () => {
  showError("");
  showNotice("");
  setBusy(true);
  try {
    const credential = await createAccountWithEmail(emailInput.value, passwordInput.value);
    await sendVerificationEmail(credential.user);
    pendingVerificationUser = credential.user;
    setResendVisible(true);
    showNotice(
      "Account created. We sent a verification link to your email. Check spam if you do not see it, then sign in after verifying.",
      true,
    );
    await signOutUser();
  } catch (error) {
    showError(authErrorMessage(error));
  } finally {
    setBusy(false);
  }
});

resendButton.addEventListener("click", async () => {
  showError("");
  setBusy(true);
  try {
    let user = pendingVerificationUser;
    if (!user) {
      const credential = await signInWithEmail(emailInput.value, passwordInput.value);
      user = credential.user;
    }
    if (emailIsVerified(user)) {
      window.location.replace("/");
      return;
    }
    await sendVerificationEmail(user);
    pendingVerificationUser = user;
    setResendVisible(true);
    showNotice(
      "Verification email sent again. Check spam if it does not appear. Sign in after you verify.",
      true,
    );
    await signOutUser();
  } catch (error) {
    showError(authErrorMessage(error));
  } finally {
    setBusy(false);
  }
});

googleButton.addEventListener("click", async () => {
  showError("");
  showNotice("");
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
