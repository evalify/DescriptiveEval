document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('evaluationForm');
    const providerSelect = document.getElementById('provider');
    const resultDiv = document.getElementById('result');
    const submitButton = form.querySelector('button[type="submit"]');
    const loadingStates = {
        default: 'Evaluate',
        loading: 'Evaluating...'
    };

    function setLoadingState(isLoading) {
        submitButton.disabled = isLoading;
        submitButton.textContent = isLoading ? loadingStates.loading : loadingStates.default;
        if (isLoading) {
            submitButton.classList.add('loading');
        } else {
            submitButton.classList.remove('loading');
        }
    }

    function displayError(message) {
        resultDiv.innerHTML = `
            <div class="error">
                <h2>Error</h2>
                <p>${message}</p>
            </div>
        `;
        resultDiv.classList.remove('hidden');
    }

    function displayResult(result) {
        resultDiv.innerHTML = `
            <h2>Evaluation Result</h2>
            <div class="score">Score: <span>${result.score}</span></div>
            <div class="reason">Reason: <span>${result.reason}</span></div>
        `;
        resultDiv.classList.remove('hidden');
    }

    async function handleProviderChange(provider) {
        try {
            const response = await fetch('/set-provider', { // Use absolute path
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider })
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            return data;
        } catch (error) {
            throw new Error(`Failed to switch provider: ${error.message}`);
        }
    }

    async function handleEvaluation(formData) {
        const response = await fetch('/score', { // Use absolute path
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    }

    // Event Listeners
    providerSelect.addEventListener('change', async function(e) {
        try {
            setLoadingState(true);
            await handleProviderChange(this.value);
        } catch (error) {
            displayError(error.message);
        } finally {
            setLoadingState(false);
        }
    });

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        if (submitButton.disabled) return;

        const formData = {
            student_ans: document.getElementById('student_ans').value.trim(),
            expected_ans: document.getElementById('expected_ans').value.trim(),
            total_score: parseInt(document.getElementById('total_score').value)
        };

        const question = document.getElementById('question').value.trim();
        if (question) {
            formData.question = question;
        }

        try {
            setLoadingState(true);
            const result = await handleEvaluation(formData);
            displayResult(result);
        } catch (error) {
            displayError(error.message);
        } finally {
            setLoadingState(false);
        }
    });
});
