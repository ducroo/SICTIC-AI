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
const DATAROOM_WORKING_MESSAGE = "We're working on your data room.";
const ACTIVE_JOB_KEY = "sictic.review.activeJob";
const config = window.REVIEW_CONFIG;
const form = document.getElementById("review-form");
const fileInput = document.getElementById("upload");
const fileLabel = document.getElementById("file-label");
const fileHint = document.getElementById("file-hint");
const modePitch = document.getElementById("mode-pitch");
const modeDataroom = document.getElementById("mode-dataroom");
const emailResultsInput = document.getElementById("email-results");
const emailResultsHint = document.getElementById("email-results-hint");
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
const reviewSteps = document.getElementById("review-steps");
const buttonLabel = submit.textContent;

const PITCH_ACCEPT =
  ".pdf,.ppt,.pptx,application/pdf,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation";
const DATAROOM_ACCEPT = ".zip,application/zip,application/x-zip-compressed";
const PITCH_STEPS = [
  "1. Receive the deck",
  "2. Extract the text",
  "3. Review the deck",
  "4. Prepare the report",
];
const DATAROOM_STEPS = [
  "1. Receive the archive",
  "2. Extract the documents",
  "3. Review the data room",
  "4. Prepare the report",
];

function selectedKind() {
  if (modeDataroom && modeDataroom.checked) {
    return "dataroom";
  }
  return "pitch_deck";
}

function workingMessageForKind(kind) {
  return kind === "dataroom" ? DATAROOM_WORKING_MESSAGE : WORKING_MESSAGE;
}

function syncModeUi() {
  const kind = selectedKind();
  const dataroom = kind === "dataroom";
  fileLabel.textContent = dataroom ? "Data room ZIP" : "Pitch deck";
  fileInput.name = dataroom ? "dataroom" : "deck";
  fileInput.accept = dataroom ? DATAROOM_ACCEPT : PITCH_ACCEPT;
  fileHint.textContent = dataroom
    ? "One ZIP of the dossier (up to 100 MB). Nested archives are skipped. A full room can take more than 30 minutes."
    : "PDF or PowerPoint. The review uses the text in the file. A long deck can take 15-20 minutes.";
  submit.textContent = dataroom ? "Review this data room" : "Review this deck";
  const steps = dataroom ? DATAROOM_STEPS : PITCH_STEPS;
  const stepIds = ["receive", "extract", "review", "report"];
  reviewSteps.innerHTML = steps
    .map((label, index) => `<li data-step="${stepIds[index]}">${label}</li>`)
    .join("");
  if (!busy) {
    workingMessage.textContent = workingMessageForKind(kind);
  }
}

let appCheck = null;
let busy = false;
let timer = null;
let readyUser = null;
let resumeStarted = false;
let activeJobId = null;

const modeFieldset = document.getElementById("review-mode");
function onModeInteraction() {
  // Radios can be toggled via label click; sync on change and click.
  syncModeUi();
}
if (modePitch) {
  modePitch.addEventListener("change", onModeInteraction);
  modePitch.addEventListener("click", onModeInteraction);
}
if (modeDataroom) {
  modeDataroom.addEventListener("change", onModeInteraction);
  modeDataroom.addEventListener("click", onModeInteraction);
}
if (modeFieldset) {
  modeFieldset.addEventListener("change", onModeInteraction);
  modeFieldset.querySelectorAll(".mode-option").forEach((option) => {
    option.addEventListener("click", () => {
      // Ensure the radio under this label is selected before syncing.
      const input = option.querySelector('input[type="radio"]');
      if (input && !input.checked) {
        input.checked = true;
      }
      syncModeUi();
    });
  });
}
syncModeUi();

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
  fileInput.disabled = false;
  if (modePitch) modePitch.disabled = false;
  if (modeDataroom) modeDataroom.disabled = false;
  syncModeUi();
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
  submit.textContent = message;
  fileInput.disabled = true;
  if (modePitch) modePitch.disabled = true;
  if (modeDataroom) modeDataroom.disabled = true;
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

async function apiHeaders(forceRefresh = false) {
  const instance = ensureAppCheck();
  const [{ token: appCheckToken }, idToken] = await Promise.all([
    getToken(instance, forceRefresh),
    currentIdToken(forceRefresh),
  ]);
  return {
    "X-Firebase-AppCheck": appCheckToken,
    Authorization: `Bearer ${idToken}`,
  };
}

function isAuthTokenError(message) {
  const text = String(message || "").toLowerCase();
  return (
    text.includes("app check") ||
    text.includes("sign-in token") ||
    text.includes("unauthorized") ||
    text.includes("401")
  );
}

async function readJsonResponse(response) {
  try {
    return await response.json();
  } catch (_error) {
    return {};
  }
}

async function pollStatus(jobId) {
  const url = `${config.apiBaseUrl}/api/review/${jobId}`;
  let forceRefreshNext = false;
  while (true) {
    // Refresh tokens every poll so long reviews outlive App Check / Auth TTL.
    const headers = await apiHeaders(forceRefreshNext);
    const forcedRefresh = forceRefreshNext;
    forceRefreshNext = false;
    const response = await fetch(url, { headers });
    const payload = await readJsonResponse(response);
    if (!response.ok) {
      const detail = payload.error || "The review status could not be read.";
      if (response.status === 401 && !forcedRefresh) {
        forceRefreshNext = true;
        continue;
      }
      throw new Error(detail);
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
  // Drop the internal model line from shared batch-audit markdown.
  inner = inner.replace(/<p>\s*<strong>\s*Model:\s*<\/strong>\s*[^<]*<\/p>/gi, "");
  inner = inner.replace(/<p>\s*\*\*Model:\*\*[^<]*<\/p>/gi, "");
  // Restore intentional line breaks that the markdown renderer escaped.
  inner = inner.replace(/&lt;br\s*\/?&gt;/gi, "<br>");
  return inner.trim();
}

function presentReport(reportHtml, deckName, jobId, reviewKind = "pitch_deck") {
  const label = deckLabelFromReport(reportHtml, deckName || "your upload");
  const body = reportBodyHtml(reportHtml);
  const safeName =
    label.replace(/[^\w.\-]+/g, "_").replace(/^_+|_+$/g, "") ||
    (reviewKind === "dataroom" ? "dataroom" : "pitch-deck");
  const kicker =
    reviewKind === "dataroom" ? "SICTIC data-room review" : "SICTIC pitch deck review";
  const footnote =
    reviewKind === "dataroom"
      ? "This is an automated document check against SICTIC’s published due diligence checklist topics. It is not an investment decision."
      : "This is an automated document check against SICTIC Investor Day criteria. It is not a jury decision and does not submit an application.";
  if (jobId) {
    activeJobId = jobId;
  }
  reportEl.innerHTML = `
    <div class="report-shell">
      <div class="report-actions">
        <button type="button" class="secondary" id="print-report">Print</button>
        <button type="button" id="download-report" ${jobId ? "" : "disabled"}>Download PDF</button>
      </div>
      <article id="report-print" class="report-document" data-download-name="${safeName}" data-job-id="${jobId || ""}" data-review-kind="${reviewKind}">
        <div class="report-masthead">
          <img class="report-logo" src="/static/sictic-logo.svg" alt="SICTIC" width="156" height="42">
          <div>
            <p class="report-kicker">${kicker}</p>
            <h2>Review of ${label}</h2>
          </div>
        </div>
        <div class="report-body">${body}</div>
        <p class="report-footnote">${footnote}</p>
      </article>
    </div>
  `;
  const printButton = document.getElementById("print-report");
  const downloadButton = document.getElementById("download-report");
  if (printButton) {
    printButton.addEventListener("click", () => window.print());
  }
  if (downloadButton && jobId) {
    downloadButton.addEventListener("click", () => downloadReportPdf(jobId, safeName, downloadButton));
  }
}

async function downloadReportPdf(jobId, baseName, button) {
  if (!jobId) {
    return;
  }
  const previous = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "Preparing PDF…";
  }
  try {
    let headers = await apiHeaders();
    let response = await fetch(`${config.apiBaseUrl}/api/review/${jobId}/pdf`, {
      headers,
    });
    if (response.status === 401) {
      headers = await apiHeaders(true);
      response = await fetch(`${config.apiBaseUrl}/api/review/${jobId}/pdf`, {
        headers,
      });
    }
    if (!response.ok) {
      let detail = "The PDF could not be downloaded.";
      try {
        const payload = await response.json();
        detail = payload.error || detail;
      } catch (_error) {
        // keep default
      }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${baseName}-sictic-review.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = previous || "Download PDF";
    }
  }
}

function updateEmailHint() {
  if (!emailResultsHint) {
    return;
  }
  const email = (readyUser && readyUser.email) || "your signed-in email";
  if (emailResultsInput && emailResultsInput.checked) {
    emailResultsHint.textContent =
      `We’ll email the PDF to ${email} when the review finishes. You can close this window.`;
  } else {
    emailResultsHint.textContent =
      "Leave this checked if you want the PDF emailed when the review finishes.";
  }
}

async function followJob(jobId) {
  beginBusy(workingMessageForKind(selectedKind()));
  try {
    const finished = await pollStatus(jobId);
    if (finished.report_html) {
      presentReport(
        finished.report_html,
        finished.deck_filename,
        jobId,
        finished.review_kind || "pitch_deck",
      );
    }
    if (finished.email_requested && finished.email_sent) {
      showWorking("The review is ready. We also emailed you the PDF.");
    } else if (finished.email_requested && finished.email_error) {
      showWorking("The review is ready, but emailing failed.");
      showError(finished.email_error);
    } else {
      showWorking("The review is ready.");
    }
    clearActiveJob();
  } catch (error) {
    const message = error.message || String(error);
    showError(message);
    showWorking(message);
    // Keep the job id so a refresh can resume after a transient auth failure.
    if (!isAuthTokenError(message)) {
      clearActiveJob();
    }
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
  updateEmailHint();
  resumeActiveJobIfAny();
});

if (emailResultsInput) {
  emailResultsInput.addEventListener("change", updateEmailHint);
}

signOutButton.addEventListener("click", async () => {
  clearActiveJob();
  await signOutUser();
  window.location.replace("/login.html");
});

submit.addEventListener("click", () => {
  if (busy) {
    showWorking(workingMessageForKind(selectedKind()));
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!readyUser) {
    window.location.replace("/login.html");
    return;
  }
  const kind = selectedKind();
  const working = workingMessageForKind(kind);
  if (busy) {
    showWorking(working);
    return;
  }
  showError("");
  reportEl.innerHTML = "";
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    showError(
      kind === "dataroom"
        ? "Choose a ZIP archive of the data room."
        : "Choose a PDF or PowerPoint pitch deck.",
    );
    return;
  }

  beginBusy(working);
  const emailResults = Boolean(emailResultsInput && emailResultsInput.checked);

  try {
    const headers = await apiHeaders();
    const body = new FormData();
    body.append("review_kind", kind);
    body.append(kind === "dataroom" ? "dataroom" : "deck", file, file.name);
    if (emailResults) {
      body.append("email_results", "1");
    }
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
    activeJobId = jobId;
    saveActiveJob(jobId);
    setSteps(started.steps);
    if (typeof started.elapsed_seconds === "number") {
      tick(started.elapsed_seconds);
    }
    if (emailResults) {
      const email = readyUser.email || "your email";
      showWorking(
        `Review started. We’ll email the PDF to ${email} when it’s ready — you can close this window.`,
      );
    }
    const finished = await pollStatus(jobId);
    if (finished.report_html) {
      presentReport(
        finished.report_html,
        finished.deck_filename || file.name,
        jobId,
        finished.review_kind || kind,
      );
    }
    if (finished.email_requested && finished.email_sent) {
      showWorking("The review is ready. We also emailed you the PDF.");
    } else if (finished.email_requested && finished.email_error) {
      showWorking("The review is ready, but emailing failed.");
      showError(finished.email_error);
    } else {
      showWorking("The review is ready.");
    }
    clearActiveJob();
  } catch (error) {
    const message = error.message || String(error);
    showError(message);
    showWorking(message);
    if (!isAuthTokenError(message)) {
      clearActiveJob();
    }
  } finally {
    release();
  }
});
