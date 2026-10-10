import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  initializeAppCheck,
  ReCaptchaEnterpriseProvider,
  getToken,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app-check.js";

const config = window.REVIEW_CONFIG;
const form = document.getElementById("review-form");
const fileInput = document.getElementById("deck");
const submit = document.getElementById("submit");
const errorEl = document.getElementById("error");
const statusEl = document.getElementById("status");
const reportEl = document.getElementById("report");

let appCheck = null;

function showError(message) {
  errorEl.hidden = !message;
  errorEl.textContent = message || "";
}

function showStatus(message) {
  statusEl.hidden = !message;
  statusEl.textContent = message || "";
}

async function ensureAppCheck() {
  if (appCheck) {
    return appCheck;
  }
  if (!config.recaptchaSiteKey) {
    throw new Error(
      "App Check is not configured yet. Add the reCAPTCHA site key in config.js after enabling App Check in the Firebase console.",
    );
  }
  const app = initializeApp(config.firebase);
  appCheck = initializeAppCheck(app, {
    provider: new ReCaptchaEnterpriseProvider(config.recaptchaSiteKey),
    isTokenAutoRefreshEnabled: true,
  });
  return appCheck;
}

async function appCheckHeader() {
  const instance = await ensureAppCheck();
  const { token } = await getToken(instance, false);
  return { "X-Firebase-AppCheck": token };
}

function formatSteps(payload) {
  const lines = (payload.steps || []).map((step) => {
    const mark = step.state === "done" ? "done" : step.state === "current" ? "now" : "wait";
    return `${mark}: ${step.label}`;
  });
  const elapsed = payload.elapsed_seconds;
  if (typeof elapsed === "number") {
    const minutes = Math.floor(elapsed / 60);
    const seconds = String(elapsed % 60).padStart(2, "0");
    lines.push(`Elapsed ${minutes}:${seconds}`);
  }
  if (payload.message) {
    lines.unshift(payload.message);
  }
  return lines.join("\n");
}

async function pollStatus(jobId, headers) {
  const url = `${config.apiBaseUrl}/api/review/${jobId}`;
  while (true) {
    const response = await fetch(url, { headers });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "The review status could not be read.");
    }
    showStatus(formatSteps(payload));
    if (payload.error) {
      throw new Error(payload.error);
    }
    if (payload.done) {
      return payload;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  reportEl.hidden = true;
  reportEl.innerHTML = "";
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    showError("Choose a PDF or PowerPoint pitch deck.");
    return;
  }
  submit.disabled = true;
  submit.textContent = "We're working on your deck.";
  try {
    const headers = await appCheckHeader();
    const body = new FormData();
    body.append("deck", file, file.name);
    const start = await fetch(`${config.apiBaseUrl}/api/review`, {
      method: "POST",
      headers,
      body,
    });
    const started = await start.json();
    if (!start.ok) {
      throw new Error(started.error || "The review could not be started.");
    }
    showStatus(formatSteps(started));
    const finished = await pollStatus(started.job_id || started.id, headers);
    if (finished.report_html) {
      reportEl.innerHTML = finished.report_html;
      reportEl.hidden = false;
    }
    showStatus("The review is ready.");
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    submit.disabled = false;
    submit.textContent = "Review this deck";
  }
});
