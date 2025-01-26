document.addEventListener("DOMContentLoaded", () => {
  // Initialize theme
  const theme = localStorage.getItem("theme") || "light";
  document.documentElement.setAttribute("data-theme", theme);

  // Initialize empty results with placeholder
  document.querySelectorAll(".result").forEach((result) => {
    if (!result.textContent.trim()) {
      result.innerHTML =
        '<div class="empty-result">Results will appear here...</div>';
    }
  });

  // Immediately hide all loading indicators
  document.querySelectorAll(".loading").forEach((loader) => {
    loader.style.display = "none";
  });

  // Theme toggle logic
  const toggleTheme = () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const newTheme = currentTheme === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", newTheme);
    localStorage.setItem("theme", newTheme);
    updateThemeButtonText();
  };

  const updateThemeButtonText = () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const icon = currentTheme === "light" ? "🌙" : "☀️";
    themeToggle.innerHTML = `${icon} ${
      currentTheme === "light" ? "Dark" : "Light"
    } Mode`;
  };

  // Create and append theme toggle button
  const themeToggle = document.createElement("button");
  themeToggle.className = "theme-toggle";
  document.body.appendChild(themeToggle);
  updateThemeButtonText();
  themeToggle.addEventListener("click", toggleTheme);

  // Tab switching logic
  const tabs = document.querySelectorAll(".tab");
  const contents = document.querySelectorAll(".tab-content");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      contents.forEach((c) => c.classList.remove("active"));

      tab.classList.add("active");
      document.querySelector(`#${tab.dataset.tab}`).classList.add("active");
    });
  });

  // Format functions for each endpoint
  const formatters = {
    score: (data) => {
      return `# Score Evaluation
**Score:** ${data.score}
**Reason:** ${data.reason}

**Rubric:**
${data.rubric}

**Breakdown:**
${data.breakdown}
`;
    },
    "generate-guidelines": (data) => {
      return `# Evaluation Guidelines

${data.guidelines}
`;
    },
    "enhance-qa": (data) => {
      return `# Enhanced Q&A

**Enhanced Question:**
${data.enhanced_question}

**Enhanced Expected Answer:**
${data.enhanced_expected_ans}
`;
    },
    evaluate: (data) => {
      const results = data.results
        .map(
          (r) =>
            `## Student ID: ${r.student_id}
**Score:** ${r.score}
**Reason:** ${r.reason}

**Rubric:**
${r.rubric}

**Breakdown:**
${r.breakdown}
`
        )
        .join("\n\n"); // TODO: Change format of bulk evaluation results
      return `# Bulk Evaluation Results

${results} 
`;
    },
  };

  // API calls with markdown formatting
  async function callAPI(endpoint, data) {
    const loading = document.querySelector(`#${endpoint}-loading`);
    const result = document.querySelector(`#${endpoint}-result`);

    try {
      loading.style.display = "block";
      result.innerHTML = '<div class="empty-result">Processing...</div>';

      const response = await fetch(`/${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
      });

      const json = await response.json();
      const formatter =
        formatters[endpoint] || ((data) => JSON.stringify(data, null, 2));
      const markdown = formatter(json);
      result.innerHTML = marked.parse(markdown);
    } catch (error) {
      result.innerHTML = marked.parse(
        `# Error\n\`\`\`\n${error.message}\n\`\`\``
      );
    } finally {
      loading.style.display = "none";
    }
  }

  // Form submissions
  document
    .querySelector("#score-form")
    .addEventListener("submit", async (e) => {
      e.preventDefault();
      await callAPI("score", {
        question: e.target.question.value,
        student_ans: e.target.student_ans.value,
        expected_ans: e.target.expected_ans.value,
        total_score: parseInt(e.target.total_score.value),
        guidelines: e.target.guidelines.value,
      });
    });

  document
    .querySelector("#guidelines-form")
    .addEventListener("submit", async (e) => {
      e.preventDefault();
      await callAPI("generate-guidelines", {
        question: e.target.question.value,
        expected_ans: e.target.expected_ans.value,
        total_score: parseInt(e.target.total_score.value),
      });
    });

  document
    .querySelector("#enhance-form")
    .addEventListener("submit", async (e) => {
      e.preventDefault();
      await callAPI("enhance-qa", {
        question: e.target.question.value,
        expected_ans: e.target.expected_ans.value,
      });
    });

  document
    .querySelector("#evaluate-form")
    .addEventListener("submit", async (e) => {
      e.preventDefault();
      await callAPI("evaluate", {
        quiz_id: e.target.quiz_id.value,
      });
    });
});
