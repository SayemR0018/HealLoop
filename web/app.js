const runButton = document.querySelector("#run");
const statusLine = document.querySelector("#status-line");
const scorecardEl = document.querySelector("#scorecard");
const errorEl = document.querySelector("#error");
const steps = Array.from(document.querySelectorAll(".steps li"));

const STEP_ORDER = ["fail", "fix", "green"];

function setStepState(name, state) {
  const node = steps.find((item) => item.dataset.step === name);
  if (!node) {
    return;
  }
  node.classList.remove("is-active", "is-done", "is-error");
  if (state) {
    node.classList.add(state);
  }
}

function resetSteps() {
  for (const name of STEP_ORDER) {
    setStepState(name, "");
  }
}

function showError(message) {
  errorEl.hidden = false;
  errorEl.textContent = message;
}

function clearError() {
  errorEl.hidden = true;
  errorEl.textContent = "";
}

function paintScorecard(data) {
  const history = Array.isArray(data.history) ? data.history : [];
  const sawFail = history.some((item) => item.status_before === "fail");
  const sawFix = history.some((item) => item.applied && item.fix_plan);
  const sawGreen = data.status === "green" && data.passed === true;

  setStepState("fail", sawFail ? "is-done" : "");
  setStepState("fix", sawFix ? "is-done" : "");
  setStepState("green", sawGreen ? "is-done" : data.status && data.status !== "green" ? "is-error" : "");

  const model = data.model ?? "mock";
  const iterations = data.iterations ?? 0;
  statusLine.textContent = `status ${data.status} · iterations ${iterations} · model ${model}`;
  scorecardEl.textContent = JSON.stringify(data, null, 2);
}

async function pause(ms) {
  await new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function runMockHeal() {
  runButton.disabled = true;
  clearError();
  resetSteps();
  statusLine.textContent = "Running mock heal…";
  scorecardEl.textContent = "Calling POST /api/heal";
  setStepState("fail", "is-active");

  const advance = window.setTimeout(() => {
    setStepState("fail", "is-done");
    setStepState("fix", "is-active");
  }, 450);

  try {
    const response = await fetch("/api/heal", {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const raw = await response.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      throw new Error(raw.trim() || `Request failed (${response.status})`);
    }
    if (!response.ok) {
      const message = data && data.error ? data.error : `Request failed (${response.status})`;
      throw new Error(message);
    }

    window.clearTimeout(advance);
    setStepState("fail", "is-active");
    await pause(180);
    setStepState("fail", "is-done");
    setStepState("fix", "is-active");
    await pause(180);
    paintScorecard(data);
  } catch (error) {
    window.clearTimeout(advance);
    resetSteps();
    setStepState("fail", "is-error");
    const message = error instanceof Error ? error.message : "Mock heal failed";
    statusLine.textContent = "Mock heal failed";
    scorecardEl.textContent = "Scorecard JSON appears here.";
    showError(message);
  } finally {
    runButton.disabled = false;
  }
}

runButton.addEventListener("click", () => {
  runMockHeal();
});
