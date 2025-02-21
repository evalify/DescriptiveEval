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

    const container = document.getElementById("activeEvaluations");
    const emptyState = document.getElementById("emptyEvaluationState");

    // Check if there are any active evaluations by looking at workers with current_jobs
    const activeWorkers = workersData.workers.filter(
      (worker) => worker.current_job !== null
    );

    if (activeWorkers.length === 0) {
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

    // Create a document fragment for better performance
    const fragment = document.createDocumentFragment();

    // Get status for each active worker's quiz
    for (const worker of activeWorkers) {
      const quizId = worker.current_job.quiz_id;
      try {
        const statusResponse = await fetch(`/evaluate/status/${quizId}`);
        const statusData = await statusResponse.json();

        if (statusData.message === "No Evaluation is Running") {
          continue;
        }

        const progress = statusData.progress || 0;
        const existingCard = container.querySelector(
          `[data-quiz-id="${quizId}"]`
        );

        if (existingCard) {
          // Update existing card
          const progressBar = existingCard.querySelector(".progress-bar");
          progressBar.style.width = `${progress}%`;
          progressBar.setAttribute("aria-valuenow", progress);
          progressBar.textContent = `${progress}%`;

          existingCard.querySelector(".status-badge").className =
            "badge bg-primary status-badge";
          existingCard.querySelector(".status-badge").textContent =
            statusData.current_phase || "evaluating";

          existingCard.querySelector(
            ".response-count"
          ).textContent = `${Math.round(
            statusData.total * (statusData.progress / 100)
          )} / ${statusData.total} responses evaluated`;

          // Update timing info if available
          if (statusData.elapsed) {
            const timingInfo =
              existingCard.querySelector(".timing-info") ||
              document.createElement("small");
            timingInfo.className = "text-muted d-block timing-info mt-1";
            timingInfo.textContent = `Elapsed: ${formatDuration(
              statusData.elapsed
            )} | Remaining: ${formatDuration(statusData.remaining)}`;
            if (!existingCard.querySelector(".timing-info")) {
              existingCard
                .querySelector(".card-content")
                .appendChild(timingInfo);
            }
          }
        } else {
          // Create new card
          const card = document.createElement("div");
          card.className = "evaluation-card fade-in";
          card.dataset.quizId = quizId;
          card.innerHTML = `
            <div class="card-content">
              <div class="d-flex justify-content-between align-items-center mb-2">
                <h6 class="mb-0">Quiz ID: ${quizId}</h6>
                <span class="badge bg-primary status-badge">
                  ${statusData.current_phase || "evaluating"}
                </span>
              </div>
              <div class="progress mb-2">
                <div class="progress-bar" role="progressbar" style="width: ${progress}%" 
                     aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100">
                  ${progress}%
                </div>
              </div>
              <small class="text-muted d-block response-count">
                ${Math.round(
                  statusData.total * (statusData.progress / 100)
                )} / ${statusData.total} responses evaluated
              </small>
              ${
                statusData.elapsed
                  ? `
                <small class="text-muted d-block timing-info mt-1">
                  Elapsed: ${formatDuration(
                    statusData.elapsed
                  )} | Remaining: ${formatDuration(statusData.remaining)}
                </small>
              `
                  : ""
              }
            </div>
          `;
          fragment.appendChild(card);
        }
      } catch (error) {
        console.error(`Error fetching status for quiz ${quizId}:`, error);
      }
    }

    // Remove cards for completed evaluations
    Array.from(container.children).forEach((card) => {
      const quizId = card.dataset.quizId;
      if (
        !activeWorkers.some(
          (worker) =>
            worker.current_job && worker.current_job.quiz_id === quizId
        )
      ) {
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

    // Update worker count
    document.getElementById(
      "workerCount"
    ).textContent = `${data.active_workers} Active`;

    // Update worker list
    updateWorkerList(data.workers);

    // Update queue info
    updateQueueInfo(data.queue_info);

    // Update summary stats
    updateDashboardStats(data.jobs_summary);
  } catch (error) {
    console.error("Error updating worker status:", error);
    showToast("Failed to update worker status", "danger");
  }
}

// Update queue information
function updateQueueInfo(queueInfo) {
  // Update tabs with counts
  document.querySelector(
    '[href="#queuedJobs"]'
  ).innerHTML = `<i class="bi bi-hourglass-split"></i> Queued (${queueInfo.queued.length})`;
  document.querySelector(
    '[href="#failedJobs"]'
  ).innerHTML = `<i class="bi bi-x-circle"></i> Failed (${queueInfo.failed.length})`;
  document.querySelector(
    '[href="#completedJobs"]'
  ).innerHTML = `<i class="bi bi-check-circle"></i> Completed (${queueInfo.completed.length})`;

  // Update tables
  updateQueuedJobs(queueInfo.queued);
  updateFailedJobs(queueInfo.failed);
  updateCompletedJobs(queueInfo.completed);
}

function updateQueuedJobs(jobs) {
  const tbody = document.getElementById("queuedJobsList");
  tbody.innerHTML = jobs
    .map(
      (job) => `
    <tr data-job-id="${job.job_id}" class="fade-in">
      <td>${job.job_id}</td>
      <td>${job.quiz_id}</td>
      <td>${
        job.enqueued_at ? new Date(job.enqueued_at).toLocaleString() : "N/A"
      }</td>
      <td><span class="badge bg-secondary">queued</span></td>
      <td>${job.worker_pid || "N/A"}</td>
      <td>
        <button class="btn btn-warning btn-sm" onclick="stopJob('${
          job.quiz_id
        }')">
          <i class="bi bi-stop-circle"></i> Stop
        </button>
      </td>
    </tr>
  `
    )
    .join("");
}

function updateFailedJobs(jobs) {
  const tbody = document.getElementById("failedJobsList");
  tbody.innerHTML = jobs
    .map(
      (job) => `
    <tr data-job-id="${job.job_id}" class="fade-in">
      <td>${job.job_id}</td>
      <td>${job.quiz_id}</td>
      <td>${
        job.failed_at ? new Date(job.failed_at).toLocaleString() : "N/A"
      }</td>
      <td class="text-danger">${job.error_message || "Unknown error"}</td>
    </tr>
  `
    )
    .join("");
}

function updateCompletedJobs(jobs) {
  const tbody = document.getElementById("completedJobsList");
  tbody.innerHTML = jobs
    .map(
      (job) => `
    <tr data-job-id="${job.job_id}" class="fade-in">
      <td>${job.job_id}</td>
      <td>${job.quiz_id}</td>
      <td>${
        job.completed_at ? new Date(job.completed_at).toLocaleString() : "N/A"
      }</td>
      <td>${formatDuration(job.duration || 0)}</td>
    </tr>
  `
    )
    .join("");
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

function generateWorkerContent(worker, isEvaluating, statusText) {
  const cpuPercent = worker.current.cpu_percent.toFixed(1);
  const memoryPercent = worker.current.memory_percent.toFixed(1);
  const uptime = formatDuration(worker.stats.uptime_seconds);

  let jobInfo = "";
  if (worker.current_job) {
    const jobStartTime = worker.current_job.started_at
      ? new Date(worker.current_job.started_at).toLocaleString()
      : "N/A";
    const jobDuration = worker.current_job.duration
      ? formatDuration(worker.current_job.duration)
      : "N/A";
    jobInfo = `
      <div class="mt-2 pt-2 border-top">
        <small class="text-muted d-block">Job ID: ${
          worker.current_job.job_id || "N/A"
        }</small>
        <small class="text-muted d-block">Quiz ID: ${
          worker.current_job.quiz_id || "N/A"
        }</small>
        ${
          jobStartTime !== "N/A"
            ? `<small class="text-muted d-block">Started: ${jobStartTime}</small>`
            : ""
        }
        ${
          jobDuration !== "N/A"
            ? `<small class="text-muted d-block">Running for: ${jobDuration}</small>`
            : ""
        }
      </div>
    `;
  }

  return `
    <div class="d-flex justify-content-between align-items-start">
      <div>
        <h6 class="mb-1">Worker #${worker.worker_id} (PID: ${worker.pid})</h6>
        <small class="text-muted d-block">Status: ${worker.status}</small>
        <small class="text-muted d-block">CPU: ${cpuPercent}% | Memory: ${memoryPercent}%</small>
        <small class="text-muted d-block">Uptime: ${uptime}</small>
        <small class="text-muted d-block">Jobs Completed: ${
          worker.stats.jobs_completed
        }</small>
        ${jobInfo}
      </div>
      <button class="btn ${
        worker.current_job ? "btn-warning" : "btn-danger"
      } btn-icon" 
              onclick="showKillWorkerModal(${worker.pid}, ${Boolean(
    worker.current_job
  )})">
        <i class="bi bi-x-circle"></i>
      </button>
    </div>
  `;
}

function updateWorkerList(workers) {
  const workerList = document.getElementById("workerList");
  const fragment = document.createDocumentFragment();

  if (workers.length === 0) {
    const emptyState = document.createElement("div");
    emptyState.className = "empty-state text-center";
    emptyState.innerHTML = `
      <div class="empty-state-icon mb-3">🤖</div>
      <h5>No Active Workers</h5>
    `;
    fragment.appendChild(emptyState);
    workerList.innerHTML = "";
    workerList.appendChild(fragment);
    return;
  }

  workers.forEach((worker) => {
    const isEvaluating = worker.current_job !== null;
    const statusClass = isEvaluating
      ? "evaluating"
      : worker.status === "running"
      ? "idle"
      : "stopped";

    const existingWorker = workerList.querySelector(
      `[data-pid="${worker.pid}"]`
    );
    const workerContent = generateWorkerContent(
      worker,
      isEvaluating,
      worker.status
    );

    if (existingWorker) {
      if (existingWorker.innerHTML !== workerContent) {
        existingWorker.innerHTML = workerContent;
        existingWorker.className = `worker-item ${statusClass}`;
      }
    } else {
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

// Update dashboard stats from jobs summary
function updateDashboardStats(jobsSummary) {
  document.getElementById("queuedCount").textContent = jobsSummary.queued;
  document.getElementById("failedCount").textContent = jobsSummary.failed;
  document.getElementById("completedCount").textContent = jobsSummary.completed;
  document.getElementById("activeEvalCount").textContent = `${
    jobsSummary.active || 0
  } Active`;
}

// Initialize the dashboard
function initDashboard() {
  // Initialize theme
  initTheme();

  // Update current time every second
  setInterval(updateCurrentTime, 1000);
  updateCurrentTime();

  // Add refresh button handler
  document.getElementById("refreshWorkers").addEventListener("click", () => {
    updateWorkerStatus();
    updateActiveEvaluations();
  });

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
    .addEventListener("click", async () => {
      const killOption = document.querySelector(
        'input[name="killOption"]:checked'
      ).value;
      const spawnReplacement =
        document.getElementById("spawnReplacement").checked;

      try {
        const response = await fetch(`/workers/kill/${currentWorkerPid}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mode: killOption,
            spawn_replacement: spawnReplacement,
          }),
        });

        if (!response.ok) throw new Error("Failed to kill worker");

        const result = await response.json();
        showToast(
          `Worker ${currentWorkerPid} ${
            killOption === "graceful"
              ? "gracefully shutting down"
              : "terminated"
          } successfully`,
          "success"
        );

        if (result.replacement_worker) {
          showToast(
            `New worker spawned with PID: ${result.replacement_worker.pid}`,
            "info"
          );
        }

        killWorkerModal.hide();
        updateWorkerStatus();
      } catch (error) {
        console.error("Error killing worker:", error);
        showToast(`Failed to kill worker ${currentWorkerPid}`, "danger");
      }
    });
}

function showKillWorkerModal(pid, hasActiveJob) {
  currentWorkerPid = pid;
  document.getElementById("workerPidDisplay").textContent = pid;

  // Enable/disable and set default options based on job status
  const immediateOption = document.getElementById("killImmediately");
  const gracefulOption = document.getElementById("killGracefully");

  if (hasActiveJob) {
    immediateOption.disabled = false;
    gracefulOption.checked = true;
  } else {
    immediateOption.disabled = false;
    immediateOption.checked = true;
  }

  killWorkerModal.show();
}

// Start the dashboard when the page loads
document.addEventListener("DOMContentLoaded", initDashboard);
