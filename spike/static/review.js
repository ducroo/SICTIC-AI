const WORKING_MESSAGE = "We're working on your deck.";

function formatElapsed(seconds) {
  const whole = Math.max(0, seconds);
  const minutes = Math.floor(whole / 60);
  const remainder = whole % 60;
  return minutes + ":" + String(remainder).padStart(2, "0");
}

function showWorking(message) {
  const panel = document.getElementById("working");
  const text = document.getElementById("working-message");
  panel.hidden = false;
  text.textContent = message;
}

function setSteps(steps) {
  steps.forEach(function (step) {
    const item = document.querySelector('[data-step="' + step.id + '"]');
    if (!item) {
      return;
    }
    item.classList.remove("done", "current", "waiting");
    item.classList.add(step.state);
  });
}

document.addEventListener("DOMContentLoaded", function () {
  const form = document.querySelector("form.card");
  if (!form) {
    return;
  }
  const button = form.querySelector("button");
  const fileInput = form.querySelector("input[type=file]");
  const elapsed = document.getElementById("elapsed");
  const reportSlot = document.getElementById("report");
  const buttonLabel = button.textContent;
  let busy = false;
  let timer = null;

  function tick(seconds) {
    elapsed.textContent = "Elapsed " + formatElapsed(seconds);
  }

  function release() {
    clearInterval(timer);
    busy = false;
    button.disabled = false;
    button.textContent = buttonLabel;
    fileInput.disabled = false;
  }

  button.addEventListener("click", function () {
    if (busy) {
      showWorking(WORKING_MESSAGE);
    }
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (busy) {
      showWorking(WORKING_MESSAGE);
      return;
    }
    if (!fileInput.files || fileInput.files.length === 0) {
      return;
    }
    busy = true;
    button.disabled = true;
    button.textContent = WORKING_MESSAGE;
    showWorking(WORKING_MESSAGE);
    const started = Date.now();
    tick(0);
    timer = setInterval(function () {
      tick(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    const body = new FormData(form);
    fileInput.disabled = true;
    try {
      const start = await fetch("/review/start", { method: "POST", body: body });
      const startBody = await start.json();
      if (!start.ok) {
        throw new Error(startBody.error || "The review could not start.");
      }
      setSteps(startBody.steps);
      while (true) {
        const statusResponse = await fetch("/review/status/" + startBody.job_id);
        const status = await statusResponse.json();
        if (!statusResponse.ok) {
          throw new Error(status.error || "The review status could not be read.");
        }
        setSteps(status.steps);
        tick(status.elapsed_seconds);
        if (status.done) {
          if (status.error) {
            throw new Error(status.error);
          }
          reportSlot.innerHTML = status.report_html;
          showWorking("The review is ready.");
          break;
        }
        await new Promise(function (resolve) {
          setTimeout(resolve, 1500);
        });
      }
    } catch (error) {
      showWorking(error.message || "The review failed.");
    } finally {
      release();
    }
  });
});
