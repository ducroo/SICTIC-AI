import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  initializeAppCheck,
  ReCaptchaEnterpriseProvider,
  getToken,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app-check.js";

const WORKING_MESSAGE = "We're working on your deck.";
const config = window.REVIEW_CONFIG;
const form = document.getElementById("review-form");
const fileInput = document.getElementById("deck");
const submit = document.getElementById("submit");
const errorEl = document.getElementById("error");
const workingPanel = document.getElementById("working");
const workingMessage = document.getElementById("working-message");
const elapsedEl = document.getElementById("elapsed");
const reportEl = document.getElementById("report");
const buttonLabel = submit.textContent;

let appCheck = null;
let busy = false;
let timer = null;

function showError(message) {
  errorEl.hidden = !message;
  errorEl.textContent = message || "";
}

function formatElapsed(seconds) {
  const whole = Math.max(0, seconds);
  const minutes = Math.floor(whole / 60);
  const remainder = whole % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function showWorking(message) {
  workingPanel.hidden = false;
  workingMessage.textContent = message;
}

function setSteps(steps) {
  (steps || []).forEach((step) => {
    const item = document.querySelector(`[data-step="${step.id}"]`);
    if (!item) {
      return;
    }
    item.classList.remove("done", "current", "waiting");
    item.classList.add(step.state);
  });
}

function tick(seconds) {
  elapsedEl.textContent = `Elapsed ${formatElapsed(seconds)}`;
}

function release() {
  clearInterval(timer);
  timer = null;
  busy = false;
  submit.disabled = false;
  submit.textContent = buttonLabel;
  fileInput.disabled = false;
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

async function pollStatus(jobId, headers) {
  const url = `${config.apiBaseUrl}/api/review/${jobId}`;
  while (true) {
    const response = await fetch(url, { headers });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "The review status could not be read.");
    }
    setSteps(payload.steps);
    if (typeof payload.elapsed_seconds === "number") {
      tick(payload.elapsed_seconds);
    }
    if (payload.error) {
      throw new Error(payload.error);
    }
    if (payload.done) {
      return payload;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

submit.addEventListener("click", () => {
  if (busy) {
    showWorking(WORKING_MESSAGE);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) {
    showWorking(WORKING_MESSAGE);
    return;
  }
  showError("");
  reportEl.innerHTML = "";
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    showError("Choose a PDF or PowerPoint pitch deck.");
    return;
  }

  busy = true;
  submit.disabled = true;
  submit.textContent = WORKING_MESSAGE;
  fileInput.disabled = true;
  showWorking(WORKING_MESSAGE);
  const startedAt = Date.now();
  tick(0);
  timer = setInterval(() => {
    tick(Math.floor((Date.now() - startedAt) / 1000));
  }, 1000);

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
    setSteps(started.steps);
    if (typeof started.elapsed_seconds === "number") {
      tick(started.elapsed_seconds);
    }
    const finished = await pollStatus(started.job_id || started.id, headers);
    if (finished.report_html) {
      reportEl.innerHTML = finished.report_html;
    }
    showWorking("The review is ready.");
  } catch (error) {
    const message = error.message || String(error);
    showError(message);
    showWorking(message);
  } finally {
    release();
  }
});
