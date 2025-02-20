// Update interval in milliseconds
const UPDATE_INTERVAL = 5000;

// Store active evaluations
let activeEvaluations = new Map();

// Initialize current time display
function updateCurrentTime() {
  const now = new Date();
  document.getElementById("currentTime").textContent = now.toLocaleString();
}

// Show notification toast
function showToast(message, type = "info") {
  const toastContainer = document.querySelector(".toast-container");
  const toastElement = document.createElement("div");
  toastElement.classList.add("toast", `bg-${type}`, "text-white");
  toastElement.innerHTML = `
        <div class="toast-body">
            ${message}
            <button type="button" class="btn-close btn-close-white float-end" data-bs-dismiss="toast"></button>
        </div>
    `;
  toastContainer.appendChild(toastElement);
  const toast = new bootstrap.Toast(toastElement, { delay: 5000 });
  toast.show();
  toastElement.addEventListener("hidden.bs.toast", () => toastElement.remove());
}

// Format duration in seconds to human readable format
function formatDuration(seconds) {
  if (!seconds) return "N/A";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.round(seconds % 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m ${remainingSeconds}s`;
  }
  return `${minutes}m ${remainingSeconds}s`;
}

// Theme handling
function initTheme() {
  const themeSwitch = document.getElementById("themeSwitch");
  const currentTheme = localStorage.getItem("theme") || "light";
  document.documentElement.setAttribute("data-theme", currentTheme);
  updateThemeIcon(currentTheme === "dark");

  themeSwitch.addEventListener("click", function () {
    const isDark =
      document.documentElement.getAttribute("data-theme") === "light";
    themeSwitch.style.pointerEvents = "none"; // Prevent double-clicks during animation

    setTimeout(() => {
      const theme = isDark ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("theme", theme);
      updateThemeIcon(isDark);
      themeSwitch.style.pointerEvents = "auto";
    }, 50);
  });
}

function updateThemeIcon(isDark) {
  const icon = document.querySelector("#themeSwitch i");
  // Add a transition class before changing the icon
  icon.style.opacity = "0";
  setTimeout(() => {
    icon.className = isDark ? "bi bi-moon-stars-fill" : "bi bi-sun-fill";
    icon.style.opacity = "1";
  }, 150);
}

// Update active evaluations with optimized DOM updates
async function updateActiveEvaluations() {
  try {
    const workersResponse = await fetch("/workers/status");
    const workersData = await workersResponse.json();
    const activeQuizIds = workersData.queue_info.queued
      .map((job) => job.quiz_id)
      .filter((id) => id !== null);

    const container = document.getElementById("activeEvaluations");
    const emptyState = document.getElementById("emptyEvaluationState");

    if (activeQuizIds.length === 0) {
      if (!emptyState) {
        container.innerHTML = `
                    <div id="emptyEvaluationState" class="empty-state text-center">
                        <div class="empty-state-icon mb-3">🌬️</div>
                        <h5>No Quizzes are being evaluated</h5>
                    </div>`;
      }
      return;
    }

    // Remove empty state if it exists
    if (emptyState) {
      emptyState.remove();
    }

    // Fetch and update evaluations
    const evaluationPromises = activeQuizIds.map((quizId) =>
      fetch(`/evaluate/status/${quizId}`).then((r) => r.json())
    );

    const evaluations = await Promise.all(evaluationPromises);

    // Create a document fragment for better performance
    const fragment = document.createDocumentFragment();

    evaluations.forEach((eval) => {
      const progress = Math.round(
        (eval.evaluated_responses / eval.total_responses) * 100
      );
      const existingCard = container.querySelector(
        `[data-quiz-id="${eval.quiz_id}"]`
      );

      if (existingCard) {
        // Update existing card
        const progressBar = existingCard.querySelector(".progress-bar");
        progressBar.style.width = `${progress}%`;
        progressBar.setAttribute("aria-valuenow", progress);
        progressBar.textContent = `${progress}%`;

        existingCard.querySelector(".status-badge").className = `badge bg-${
          eval.status === "evaluating" ? "primary" : "success"
        } status-badge`;
        existingCard.querySelector(".status-badge").textContent = eval.status;

        existingCard.querySelector(
          ".response-count"
        ).textContent = `${eval.evaluated_responses} / ${eval.total_responses} responses evaluated`;
      } else {
        // Create new card
        const card = document.createElement("div");
        card.className = "evaluation-card fade-in";
        card.dataset.quizId = eval.quiz_id;
        card.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="mb-0">Quiz ID: ${eval.quiz_id}</h6>
                        <span class="badge bg-${
                          eval.status === "evaluating" ? "primary" : "success"
                        } status-badge">
                            ${eval.status}
                        </span>
                    </div>
                    <div class="progress mb-2">
                        <div class="progress-bar" role="progressbar" style="width: ${progress}%" 
                             aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100">
                            ${progress}%
                        </div>
                    </div>
                    <small class="text-muted response-count">
                        ${eval.evaluated_responses} / ${
          eval.total_responses
        } responses evaluated
                    </small>
                `;
        fragment.appendChild(card);
      }
    });

    // Remove cards for completed evaluations
    Array.from(container.children).forEach((card) => {
      const quizId = card.dataset.quizId;
      if (!evaluations.some((eval) => eval.quiz_id === quizId)) {
        card.classList.add("fade-out");
        setTimeout(() => card.remove(), 300);
      }
    });

    // Append new cards
    container.appendChild(fragment);
  } catch (error) {
    console.error("Error updating evaluations:", error);
    showToast("Failed to update evaluations", "danger");
  }
}

// Update worker status
async function updateWorkerStatus() {
  try {
    const response = await fetch("/workers/status");
    const data = await response.json();

    const workerList = document.getElementById("workerList");
    workerList.innerHTML = "";

    document.getElementById(
      "workerCount"
    ).textContent = `${data.active_workers} Active`;

    updateWorkerList(data.workers);
    updateQueueInfo(data.queue_info);
  } catch (error) {
    console.error("Error updating worker status:", error);
    showToast("Failed to update worker status", "danger");
  }
}

// Update queue information
function updateQueueInfo(queueInfo) {
  updateQueueTable("queuedJobsList", queueInfo.queued, renderQueuedRow);
  updateQueueTable("failedJobsList", queueInfo.failed, renderFailedRow);
  updateQueueTable(
    "completedJobsList",
    queueInfo.completed,
    renderCompletedRow
  );
}

function updateQueueTable(tableId, data, renderRow) {
  const tbody = document.getElementById(tableId);
  const currentRows = new Set(
    Array.from(tbody.children).map((row) => row.dataset.jobId)
  );
  const newRows = new Set(data.map((job) => job.job_id));

  // Remove rows that no longer exist
  Array.from(tbody.children).forEach((row) => {
    if (!newRows.has(row.dataset.jobId)) {
      row.classList.add("fade-out");
      setTimeout(() => row.remove(), 300);
    }
  });

  // Update existing rows and add new ones
  data.forEach((job) => {
    const existingRow = tbody.querySelector(`[data-job-id="${job.job_id}"]`);
    const rowHtml = renderRow(job);

    if (existingRow) {
      // Only update if content has changed
      if (existingRow.innerHTML !== rowHtml) {
        existingRow.innerHTML = rowHtml;
      }
    } else {
      const tr = document.createElement("tr");
      tr.dataset.jobId = job.job_id;
      tr.className = "fade-in";
      tr.innerHTML = rowHtml;
      tbody.appendChild(tr);
    }
  });
}

function renderQueuedRow(job) {
  return `
        <td>${job.job_id}</td>
        <td>${job.quiz_id}</td>
        <td>${new Date(job.enqueued_at).toLocaleString()}</td>
        <td><span class="badge bg-${
          job.status === "queued" ? "secondary" : "primary"
        }">${job.status}</span></td>
        <td>${job.worker_pid || "N/A"}</td>
        <td>
            <button class="btn btn-warning btn-sm" onclick="stopJob('${
              job.quiz_id
            }')">
                Stop
            </button>
        </td>
    `;
}

function renderFailedRow(job) {
  return `
        <td>${job.job_id}</td>
        <td>${job.quiz_id}</td>
        <td>${
          job.failed_at ? new Date(job.failed_at).toLocaleString() : "N/A"
        }</td>
        <td>${job.error_message}</td>
    `;
}

function renderCompletedRow(job) {
  return `
        <td>${job.job_id}</td>
        <td>${job.quiz_id}</td>
        <td>${
          job.completed_at ? new Date(job.completed_at).toLocaleString() : "N/A"
        }</td>
        <td>${formatDuration(job.duration)}</td>
    `;
}

// Kill worker function
async function killWorker(pid) {
  try {
    const response = await fetch(`/workers/kill/${pid}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spawn_replacement: true }),
    });

    if (!response.ok) throw new Error("Failed to kill worker");

    const result = await response.json();
    showToast(`Worker ${pid} terminated successfully`, "success");
    if (result.replacement_worker) {
      showToast(
        `New worker spawned with PID: ${result.replacement_worker.pid}`,
        "info"
      );
    }

    // Update worker status immediately
    updateWorkerStatus();
  } catch (error) {
    console.error("Error killing worker:", error);
    showToast(`Failed to kill worker ${pid}`, "danger");
  }
}

// Stop job function
async function stopJob(quizId) {
  try {
    const response = await fetch(`/jobs/stop/${quizId}`, {
      method: "POST",
    });

    if (!response.ok) throw new Error("Failed to stop job");

    showToast(`Successfully stopped job for quiz ${quizId}`, "success");
    // Update status immediately
    updateWorkerStatus();
    updateActiveEvaluations();
  } catch (error) {
    console.error("Error stopping job:", error);
    showToast(`Failed to stop job for quiz ${quizId}`, "danger");
  }
}

// LLM Testing Functions
async function handleProviderUpdate(e) {
  e.preventDefault();
  try {
    const provider = document.getElementById("provider").value;
    const modelName = document.getElementById("modelName").value;
    const apiKey = document.getElementById("apiKey").value;

    const response = await fetch("/set-provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: provider,
        provider_model_name: modelName,
        provider_api_key: apiKey,
        service: "macro",
      }),
    });

    const result = await response.json();
    showToast(result.message, response.ok ? "success" : "danger");
    displayTestResults(result);
  } catch (error) {
    showToast("Failed to update provider settings", "danger");
    console.error("Error updating provider:", error);
  }
}

async function handleScoreTest(e) {
  e.preventDefault();
  try {
    const response = await fetch("/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: document.getElementById("scoreQuestion").value,
        student_ans: document.getElementById("studentAnswer").value,
        expected_ans: document.getElementById("expectedAnswer").value,
        total_score: parseInt(document.getElementById("totalScore").value),
      }),
    });

    const result = await response.json();
    displayTestResults(result);
    showToast("Scoring test completed", response.ok ? "success" : "danger");
  } catch (error) {
    showToast("Failed to test scoring", "danger");
    console.error("Error testing score:", error);
  }
}

async function handleGuidelinesTest(e) {
  e.preventDefault();
  try {
    const response = await fetch("/generate-guidelines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: document.getElementById("guidelinesQuestion").value,
        expected_ans: document.getElementById("guidelinesExpectedAnswer").value,
        total_score: 10,
      }),
    });

    const result = await response.json();
    displayTestResults(result);
    showToast("Guidelines generated", response.ok ? "success" : "danger");
  } catch (error) {
    showToast("Failed to generate guidelines", "danger");
    console.error("Error generating guidelines:", error);
  }
}

async function handleEnhanceTest(e) {
  e.preventDefault();
  try {
    const response = await fetch("/enhance-qa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: document.getElementById("enhanceQuestion").value,
        expected_ans: document.getElementById("enhanceExpectedAnswer").value,
      }),
    });

    const result = await response.json();
    displayTestResults(result);
    showToast("Q&A enhancement completed", response.ok ? "success" : "danger");
  } catch (error) {
    showToast("Failed to enhance Q&A", "danger");
    console.error("Error enhancing Q&A:", error);
  }
}

function displayTestResults(results) {
  const resultsElement = document.getElementById("testResults");
  resultsElement.textContent = JSON.stringify(results, null, 2);
}

// Worker Status handling with modal
let currentWorkerPid = null;
const killWorkerModal = new bootstrap.Modal(
  document.getElementById("killWorkerModal")
);

function updateWorkerList(workers) {
  const workerList = document.getElementById("workerList");
  const fragment = document.createDocumentFragment();

  workers.forEach((worker) => {
    const isEvaluating = worker.current_job !== null;
    const statusClass = isEvaluating
      ? "evaluating"
      : worker.status === "running"
      ? "idle"
      : "stopped";
    const statusText = isEvaluating
      ? "Evaluating"
      : worker.status === "running"
      ? "Idle"
      : "Stopped";

    const existingWorker = workerList.querySelector(
      `[data-pid="${worker.pid}"]`
    );
    const workerContent = generateWorkerContent(
      worker,
      isEvaluating,
      statusText
    );

    if (existingWorker) {
      // Update existing worker element if status or job info changed
      if (existingWorker.innerHTML !== workerContent) {
        existingWorker.innerHTML = workerContent;
        existingWorker.className = `worker-item ${statusClass}`;
      }
    } else {
      // Create new worker element
      const workerElement = document.createElement("div");
      workerElement.className = `worker-item ${statusClass} fade-in`;
      workerElement.dataset.pid = worker.pid;
      workerElement.innerHTML = workerContent;
      fragment.appendChild(workerElement);
    }
  });

  // Remove workers that no longer exist
  Array.from(workerList.children).forEach((workerElement) => {
    const pid = workerElement.dataset.pid;
    if (!workers.some((w) => w.pid.toString() === pid)) {
      workerElement.classList.add("fade-out");
      setTimeout(() => workerElement.remove(), 300);
    }
  });

  workerList.appendChild(fragment);
}

function generateWorkerContent(worker, isEvaluating, statusText) {
  const cpuPercent = worker.current.cpu_percent.toFixed(1);
  const memoryPercent = worker.current.memory_percent.toFixed(1);
  const uptime = formatDuration(worker.stats.uptime_seconds);

  let jobInfo = "";
  if (isEvaluating) {
    const duration = formatDuration(worker.current_job.duration);
    const startTime = new Date(worker.current_job.started_at).toLocaleString();
    jobInfo = `
            <div class="mt-2 pt-2 border-top">
                <small class="text-muted d-block">Quiz ID: ${worker.current_job.quiz_id}</small>
                <small class="text-muted d-block">Started: ${startTime}</small>
                <small class="text-muted d-block">Running for: ${duration}</small>
            </div>
        `;
  }

  return `
        <div class="d-flex justify-content-between align-items-start">
            <div>
                <h6 class="mb-1">Worker PID: ${worker.pid}</h6>
                <small class="text-muted d-block">Status: ${statusText}</small>
                <small class="text-muted d-block">CPU: ${cpuPercent}% | Memory: ${memoryPercent}%</small>
                <small class="text-muted d-block">Uptime: ${uptime}</small>
                ${jobInfo}
            </div>
            <button class="btn ${
              isEvaluating ? "btn-warning" : "btn-danger"
            } btn-icon" 
                    onclick="showKillWorkerModal(${
                      worker.pid
                    }, ${isEvaluating})">
                <i class="bi bi-x-circle"></i>
            </button>
        </div>
    `;
}

function showKillWorkerModal(pid, hasActiveJob) {
  currentWorkerPid = pid;
  document.getElementById("workerPidDisplay").textContent = pid;

  // Update radio options
  const radioContainer = document.querySelector(".modal-body .mb-3");
  radioContainer.innerHTML = `
        ${
          hasActiveJob
            ? `
            <div class="form-check mb-3">
                <input class="form-check-input" type="radio" name="killOption" id="killJobOnly" value="job" checked>
                <label class="form-check-label" for="killJobOnly">
                    <span class="text-warning">Stop Current Job Only</span>
                    <small class="d-block text-muted mt-1">This will only stop the current evaluation job and free the worker for other tasks.</small>
                </label>
            </div>
        `
            : ""
        }
        <div class="form-check">
            <input class="form-check-input" type="radio" name="killOption" id="killWorker" value="worker" ${
              !hasActiveJob ? "checked" : ""
            }>
            <label class="form-check-label" for="killWorker">
                <span class="text-danger">Terminate Worker Process</span>
                <small class="d-block text-muted mt-1">⚠️ This will forcefully kill the worker process and any job it's running. This action cannot be undone.</small>
            </label>
        </div>
    `;

  // Get spawn replacement checkbox
  const spawnReplacementCheck = document.getElementById("spawnReplacement");
  const spawnReplacementContainer =
    spawnReplacementCheck.closest(".form-check");

  // Add radio change handler
  const radioButtons = document.querySelectorAll('input[name="killOption"]');
  radioButtons.forEach((radio) => {
    radio.addEventListener("change", function () {
      const isWorkerKill = this.value === "worker";
      spawnReplacementCheck.disabled = !isWorkerKill;
      spawnReplacementContainer.classList.toggle("disabled", !isWorkerKill);
      if (!isWorkerKill) {
        spawnReplacementCheck.checked = false;
      }
    });
  });

  // Initial state
  const initialRadio = document.querySelector(
    'input[name="killOption"]:checked'
  );
  spawnReplacementCheck.disabled = initialRadio.value !== "worker";
  spawnReplacementContainer.classList.toggle(
    "disabled",
    initialRadio.value !== "worker"
  );
  if (initialRadio.value !== "worker") {
    spawnReplacementCheck.checked = false;
  }

  // Update modal title and button based on action
  document.querySelector("#killWorkerModal .modal-title").textContent =
    hasActiveJob ? "Worker Action Required" : "Confirm Worker Termination";
  document.getElementById("confirmKillWorker").textContent = hasActiveJob
    ? "Proceed"
    : "Terminate Worker";

  killWorkerModal.show();
}

// Initialize the dashboard
function initDashboard() {
  // Initialize theme
  initTheme();

  // Update current time every second
  setInterval(updateCurrentTime, 1000);
  updateCurrentTime();

  // Initial updates
  updateActiveEvaluations();
  updateWorkerStatus();

  // Set up periodic updates
  setInterval(() => {
    updateActiveEvaluations();
    updateWorkerStatus();
  }, UPDATE_INTERVAL);

  // Set up LLM testing form handlers
  document
    .getElementById("providerForm")
    .addEventListener("submit", handleProviderUpdate);
  document
    .getElementById("scoreForm")
    .addEventListener("submit", handleScoreTest);
  document
    .getElementById("guidelinesForm")
    .addEventListener("submit", handleGuidelinesTest);
  document
    .getElementById("enhanceForm")
    .addEventListener("submit", handleEnhanceTest);

  // Add kill worker modal confirmation handler
  document
    .getElementById("confirmKillWorker")
    .addEventListener("click", handleWorkerKill);
}

// Start the dashboard when the page loads
document.addEventListener("DOMContentLoaded", initDashboard);
