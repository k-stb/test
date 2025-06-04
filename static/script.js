const form = document.getElementById('convert-form');
const progressSection = document.getElementById('progress-section');
const downloadSection = document.getElementById('download-section');
const progressBar = document.getElementById('progress');
const progressText = document.getElementById('progress-text');
const downloadLink = document.getElementById('download-link');

let currentTaskId = null;

form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(form);

    progressSection.classList.remove('hidden');
    downloadSection.classList.add('hidden');
    progressBar.style.width = '0%';
    progressText.textContent = '0%';

    const response = await fetch('/convert', {
        method: 'POST',
        body: formData
    });
    const data = await response.json();

    if (data.task_id) {
        currentTaskId = data.task_id;
        checkStatus();
    } else if (data.error) {
        alert(data.error);
    }
});

async function checkStatus() {
    if (!currentTaskId) return;
    const res = await fetch(`/status/${currentTaskId}`);
    const data = await res.json();
    if (data.status === 'completed') {
        progressBar.style.width = '100%';
        progressText.textContent = 'Fertig';
        downloadLink.href = `/download/${currentTaskId}`;
        downloadSection.classList.remove('hidden');
    } else if (data.status === 'error') {
        alert(data.error || 'Ein Fehler ist aufgetreten');
    } else {
        progressBar.style.width = `${data.progress || 0}%`;
        progressText.textContent = `${data.progress || 0}%`;
        setTimeout(checkStatus, 1000);
    }
}
