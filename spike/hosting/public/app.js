import {
  initializeAppCheck,
  ReCaptchaEnterpriseProvider,
  getToken,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app-check.js";
import {
  firebaseApp,
  watchAuth,
  signOutUser,
  currentIdToken,
} from "./auth-session.js";

const WORKING_MESSAGE = "We're working on your deck.";
const ACTIVE_JOB_KEY = "sictic.review.activeJob";
const config = window.REVIEW_CONFIG;
const form = document.getElementById("review-form");
const fileInput = document.getElementById("deck");
const submit = document.getElementById("submit");
const errorEl = document.getElementById("error");
const workingPanel = document.getElementById("working");
const workingMessage = document.getElementById("working-message");
const elapsedEl = document.getElementById("elapsed");
const reportEl = document.getElementById("report");
const sessionEl = document.getElementById("session");
const sessionEmail = document.getElementById("session-email");
const signOutButton = document.getElementById("sign-out");
const appMain = document.getElementById("app-main");
const authLoading = document.getElementById("auth-loading");
const buttonLabel = submit.textContent;

let appCheck = null;
let busy = false;
let timer = null;
let readyUser = null;
let resumeStarted = false;

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

function saveActiveJob(jobId) {
  sessionStorage.setItem(
    ACTIVE_JOB_KEY,
    JSON.stringify({ jobId, savedAt: Date.now() }),
  );
}

function clearActiveJob() {
  sessionStorage.removeItem(ACTIVE_JOB_KEY);
}

function loadActiveJobId() {
  try {
    const raw = sessionStorage.getItem(ACTIVE_JOB_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    return typeof parsed.jobId === "string" && parsed.jobId ? parsed.jobId : null;
  } catch (_error) {
    return null;
  }
}

function beginBusy(message = WORKING_MESSAGE) {
  busy = true;
  submit.disabled = true;
  submit.textContent = WORKING_MESSAGE;
  fileInput.disabled = true;
  showWorking(message);
  const startedAt = Date.now();
  tick(0);
  clearInterval(timer);
  timer = setInterval(() => {
    tick(Math.floor((Date.now() - startedAt) / 1000));
  }, 1000);
}

function ensureAppCheck() {
  if (appCheck) {
    return appCheck;
  }
  if (!config.recaptchaSiteKey) {
    throw new Error(
      "App Check is not configured yet. Add the reCAPTCHA site key in config.js after enabling App Check in the Firebase console.",
    );
  }
  appCheck = initializeAppCheck(firebaseApp, {
    provider: new ReCaptchaEnterpriseProvider(config.recaptchaSiteKey),
    isTokenAutoRefreshEnabled: true,
  });
  return appCheck;
}

async function apiHeaders() {
  const instance = ensureAppCheck();
  const [{ token: appCheckToken }, idToken] = await Promise.all([
    getToken(instance, false),
    currentIdToken(false),
  ]);
  return {
    "X-Firebase-AppCheck": appCheckToken,
    Authorization: `Bearer ${idToken}`,
  };
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

function deckLabelFromReport(reportHtml, fallback = "your deck") {
  const match = String(reportHtml || "").match(/data-deck="([^"]+)"/);
  if (match && match[1]) {
    return match[1];
  }
  const heading = String(reportHtml || "").match(/<h2>\s*Review of\s+([^<]+)<\/h2>/i);
  if (heading && heading[1]) {
    return heading[1].trim();
  }
  return fallback;
}

function reportBodyHtml(reportHtml) {
  const wrapped = String(reportHtml || "");
  const match = wrapped.match(/<section[^>]*class="report"[^>]*>([\s\S]*)<\/section>/i);
  let inner = match ? match[1] : wrapped;
  inner = inner.replace(/<h2>\s*Review of\s+[^<]+<\/h2>/i, "");
  return inner.trim();
}

function presentReport(reportHtml, deckName) {
  const label = deckLabelFromReport(reportHtml, deckName || "your deck");
  const body = reportBodyHtml(reportHtml);
  const safeName = label.replace(/[^\w.\-]+/g, "_").replace(/^_+|_+$/g, "") || "pitch-deck";
  reportEl.innerHTML = `
    <div class="report-shell">
      <div class="report-actions">
        <button type="button" class="secondary" id="print-report">Print</button>
        <button type="button" id="download-report">Download PDF</button>
      </div>
      <article id="report-print" class="report-document" data-download-name="${safeName}">
        <header class="report-masthead">
          <img class="report-logo" src="/static/sictic-logo.svg" alt="SICTIC">
          <div>
            <p class="report-kicker">SICTIC pitch deck review</p>
            <h2>Review of ${label}</h2>
          </div>
        </header>
        <div class="report-body">${body}</div>
        <p class="report-footnote">This is an automated document check against SICTIC Investor Day criteria. It is not a jury decision and does not submit an application.</p>
      </article>
    </div>
  `;
  const downloadButton = document.getElementById("download-report");
  const printButton = document.getElementById("print-report");
  if (downloadButton) {
    downloadButton.addEventListener("click", () => downloadReportPdf());
  }
  if (printButton) {
    printButton.addEventListener("click", () => window.print());
  }
}

async function downloadReportPdf() {
  const source = document.getElementById("report-print");
  if (!source) {
    return;
  }
  if (typeof html2pdf === "undefined") {
    window.print();
    return;
  }
  const downloadButton = document.getElementById("download-report");
  const baseName = source.dataset.downloadName || "pitch-deck-review";
  if (downloadButton) {
    downloadButton.disabled = true;
    downloadButton.textContent = "Preparing PDF…";
  }
  try {
    await html2pdf()
      .set({
        margin: [12, 12, 14, 12],
        filename: `${baseName}-sictic-review.pdf`,
        image: { type: "jpeg", quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true, logging: false },
        jsPDF: { unit: "mm", format: "a4", orientation: "portrait" },
        pagebreak: { mode: ["css", "legacy"] },
      })
      .from(source)
      .save();
  } catch (_error) {
    window.print();
  } finally {
    if (downloadButton) {
      downloadButton.disabled = false;
      downloadButton.textContent = "Download PDF";
    }
  }
}

async function followJob(jobId) {
  beginBusy(WORKING_MESSAGE);
  try {
    const headers = await apiHeaders();
    const finished = await pollStatus(jobId, headers);
    if (finished.report_html) {
      presentReport(finished.report_html, finished.deck_filename);
    }
    showWorking("The review is ready.");
  } catch (error) {
    const message = error.message || String(error);
    showError(message);
    showWorking(message);
    clearActiveJob();
  } finally {
    release();
  }
}

async function resumeActiveJobIfAny() {
  if (resumeStarted || busy) {
    return;
  }
  const jobId = loadActiveJobId();
  if (!jobId) {
    return;
  }
  resumeStarted = true;
  showError("");
  reportEl.innerHTML = "";
  await followJob(jobId);
}

watchAuth((user) => {
  if (!user) {
    window.location.replace("/login.html");
    return;
  }
  if (!user.emailVerified) {
    window.location.replace("/login.html");
    return;
  }
  readyUser = user;
  sessionEmail.textContent = user.email || user.uid;
  sessionEl.hidden = false;
  appMain.hidden = false;
  authLoading.hidden = true;
  resumeActiveJobIfAny();
});

signOutButton.addEventListener("click", async () => {
  clearActiveJob();
  await signOutUser();
  window.location.replace("/login.html");
});

submit.addEventListener("click", () => {
  if (busy) {
    showWorking(WORKING_MESSAGE);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!readyUser) {
    window.location.replace("/login.html");
    return;
  }
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

  beginBusy(WORKING_MESSAGE);

  try {
    const headers = await apiHeaders();
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
    const jobId = started.job_id || started.id;
    if (!jobId) {
      throw new Error("The review could not be started.");
    }
    saveActiveJob(jobId);
    setSteps(started.steps);
    if (typeof started.elapsed_seconds === "number") {
      tick(started.elapsed_seconds);
    }
    const finished = await pollStatus(jobId, headers);
    if (finished.report_html) {
      presentReport(finished.report_html, finished.deck_filename || file.name);
    }
    showWorking("The review is ready.");
  } catch (error) {
    const message = error.message || String(error);
    showError(message);
    showWorking(message);
    clearActiveJob();
  } finally {
    release();
  }
});
