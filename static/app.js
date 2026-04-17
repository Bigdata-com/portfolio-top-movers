// SGX Top Movers Report Generator - Frontend JavaScript

// ============================================================
// API KEY MANAGEMENT
// ============================================================

const API_KEY_STORAGE_KEY = 'bigdata_api_key';
const API_KEY_CHANGED_EVENT = 'bigdata-api-key-changed';

/** Get user's API key from localStorage */
function getUserApiKey() {
    try {
        return localStorage.getItem(API_KEY_STORAGE_KEY) || '';
    } catch {
        return '';
    }
}

/** Set user's API key (dispatches event to trigger data refresh) */
function setUserApiKey(key) {
    try {
        if (key) {
            localStorage.setItem(API_KEY_STORAGE_KEY, key);
        } else {
            localStorage.removeItem(API_KEY_STORAGE_KEY);
        }
        window.dispatchEvent(new CustomEvent(API_KEY_CHANGED_EVENT));
    } catch (e) {
        console.error('Failed to save API key:', e);
    }
}

/** Check if user has a custom key set */
function hasUserApiKey() {
    return !!getUserApiKey();
}

/** Make API request with Bigdata X-API-KEY when configured in Settings */
async function apiRequest(url, options = {}) {
    const apiKey = getUserApiKey();
    const headers = {
        ...options.headers,
    };
    
    if (apiKey) {
        headers['X-API-KEY'] = apiKey;
    }
    
    return fetch(url, {
        ...options,
        headers
    });
}

/** Parse FastAPI-style error bodies for user-visible messages */
async function parseErrorMessage(response) {
    try {
        const data = await response.json();
        const d = data.detail;
        if (typeof d === 'string') return d;
        if (d && typeof d === 'object' && typeof d.message === 'string') return d.message;
        if (d && typeof d === 'object' && d.error && d.message) return `${d.error}: ${d.message}`;
        return JSON.stringify(data);
    } catch {
        return response.statusText || 'Request failed';
    }
}

// ============================================================
// SETTINGS MODAL FUNCTIONS
// ============================================================

/** Open settings modal */
function openSettings() {
    const overlay = document.getElementById('settingsOverlay');
    const input = document.getElementById('settingsApiKey');
    const statusEl = document.getElementById('apiKeyStatus');
    
    const currentKey = getUserApiKey();
    input.value = currentKey;
    
    if (currentKey) {
        statusEl.innerHTML = '<span class="status-configured">✓ Bigdata API key is stored in this browser</span>';
    } else {
        statusEl.innerHTML = '<span class="status-default">No browser key — using server default only if the server has BIGDATA_API_KEY set</span>';
    }
    
    overlay.classList.add('visible');
}

/** Close settings modal */
function closeSettings() {
    const overlay = document.getElementById('settingsOverlay');
    overlay.classList.remove('visible');
}

/** Toggle API key visibility */
function toggleApiKeyVisibility() {
    const input = document.getElementById('settingsApiKey');
    const eyeIcon = document.getElementById('eyeIcon');
    
    if (input.type === 'password') {
        input.type = 'text';
        eyeIcon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>';
    } else {
        input.type = 'password';
        eyeIcon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>';
    }
}

/** Save Bigdata API key from the settings modal */
async function saveSettings() {
    const input = document.getElementById('settingsApiKey');
    const key = input.value.trim();
    
    setUserApiKey(key);
    
    const statusEl = document.getElementById('apiKeyStatus');
    if (key) {
        statusEl.innerHTML = '<span class="status-configured">✓ Bigdata API key is stored in this browser</span>';
    } else {
        statusEl.innerHTML = '<span class="status-default">No browser key — using server default only if configured</span>';
    }
    
    showNotification('Settings saved. Data will refresh automatically.', 'success');
    closeSettings();
    
    loadDefaultWatchlist();
    loadTopics();
    loadReports();
}

/** Clear Bigdata API key */
function clearApiKey() {
    const input = document.getElementById('settingsApiKey');
    input.value = '';
    setUserApiKey('');
    
    const statusEl = document.getElementById('apiKeyStatus');
    statusEl.innerHTML = '<span class="status-default">No browser key — using server default only if configured</span>';
    
    showNotification('Bigdata API key cleared.', 'success');
}

/** Fetch server config and show settings when Bigdata key is required in the browser */
async function checkInitialSetup() {
    const overlay = document.getElementById('settingsOverlay');
    let serverHasBigdata = false;
    try {
        const r = await fetch('/api/config');
        if (r.ok) {
            const cfg = await r.json();
            serverHasBigdata = !!cfg.server_has_bigdata_key;
        }
    } catch (e) {
        console.warn('Could not load /api/config:', e);
    }
    
    const helpEl = document.getElementById('bigdataKeyHelp');
    if (helpEl) {
        helpEl.textContent = serverHasBigdata
            ? 'Optional: override the server Bigdata key. Sent as X-API-KEY on every API call.'
            : 'Required: the server has no BIGDATA_API_KEY. Enter your Bigdata key — it is sent as X-API-KEY on every API call (job list, reports, etc.).';
    }
    
    if (!serverHasBigdata && !hasUserApiKey()) {
        overlay.classList.add('visible');
    } else {
        overlay.classList.remove('visible');
    }
}

// ============================================================
// APPLICATION STATE
// ============================================================

let pollingIntervals = {};
let availableTopics = [];
let deskStandardTopics = [];
let miniTopics = [];
let selectedTopics = [];
let customTopics = [];
let editMode = false;

const TOPIC_SET_DESCRIPTIONS = {
    'standard': 'Movers-focused queries (earnings, analyst, M&A, regulatory, etc.).',
    'desk_standard': 'Full desk-style topic set: financial metrics, M&A, leadership, competition, products, supply chain, costs, regulatory, industry, and financing.',
    'mini': 'Reduced topic set for faster processing with core financial topics.',
    'custom': 'Custom selection - add or remove topics as needed.'
};

// ============================================================
// INITIALIZATION
// ============================================================

/** Default report title: "Daily Movers - {long local date}" using the browser clock. */
function formatDefaultReportTitle() {
    const d = new Date();
    const when = d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
    return `Daily Movers - ${when}`;
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    const reportNameEl = document.getElementById('reportName');
    if (reportNameEl && !reportNameEl.value.trim()) {
        reportNameEl.value = formatDefaultReportTitle();
    }

    void checkInitialSetup();
    
    // Load data
    loadDefaultWatchlist();
    loadTopics();
    loadReports();
    
    document.getElementById('reportForm').addEventListener('submit', handleSubmit);
    
    // Listen for API key changes
    window.addEventListener(API_KEY_CHANGED_EVENT, () => {
        loadDefaultWatchlist();
        loadTopics();
        loadReports();
    });
    
    // Allow clicking outside modal to close (but only if key exists or server has default)
    document.getElementById('settingsOverlay').addEventListener('click', function(e) {
        if (e.target === this) {
            closeSettings();
        }
    });
});

// Load default watchlist from API
async function loadDefaultWatchlist() {
    try {
        const response = await apiRequest('/api/watchlist');
        if (response.ok) {
            const data = await response.json();
            document.getElementById('tickers').value = data.tickers_string;
        }
    } catch (error) {
        console.error('Error loading watchlist:', error);
        document.getElementById('tickers').value =
            'XTSE:RY, XTSE:SHOP, XTSE:TD, XTSE:ENB, XTSE:BN, XTSE:CP, XTSE:BMO, XTSE:CNR, XTSE:CNQ, XTSE:BNS, ' +
            'XSES:D05, XSES:O39, XSES:Z74, XSES:U11, XSES:S63, XSES:J36, XSES:F34, XSES:S68, XSES:H78, XSES:BN4, ' +
            'XNAS:NVDA, XNAS:AAPL, XNAS:MSFT, XNAS:AMZN, XNAS:GOOGL, XNAS:AVGO, XNAS:META, XNAS:TSLA, XNAS:ASML, XNAS:MU';
    }
}

// Load available topics
async function loadTopics() {
    const topicsList = document.getElementById('topicsList');
    
    try {
        const response = await apiRequest('/api/topics');
        if (!response.ok) throw new Error('Failed to load topics');
        
        const data = await response.json();
        availableTopics = data.topics_full;
        deskStandardTopics = data.topics_standard || [];
        miniTopics = data.topics_mini;
        
        // Match default dropdown: Standard Topics
        selectedTopics = [...availableTopics];
        customTopics = [];
        
        renderTopics();
        updateTopicSetDescription();
    } catch (error) {
        console.error('Error loading topics:', error);
        topicsList.innerHTML = '<div class="error-state">Error loading topics</div>';
    }
}

// Handle topic set dropdown change
function onTopicSetChange() {
    const topicSet = document.getElementById('topicSet').value;
    
    if (topicSet === 'standard') {
        selectedTopics = [...availableTopics];
    } else if (topicSet === 'desk_standard') {
        selectedTopics = [...deskStandardTopics];
    } else if (topicSet === 'mini') {
        selectedTopics = [...miniTopics];
    }
    // 'custom' keeps current selection
    
    updateTopicSetDescription();
    renderTopics();
}

// Update topic set description
function updateTopicSetDescription() {
    const topicSet = document.getElementById('topicSet').value;
    const descEl = document.getElementById('topicSetDescription');
    descEl.textContent = TOPIC_SET_DESCRIPTIONS[topicSet];
}

// Render topics as table rows
function renderTopics() {
    const topicsList = document.getElementById('topicsList');
    const topicsCount = document.getElementById('topicsCount');
    
    const allTopics = [...selectedTopics, ...customTopics];
    
    if (allTopics.length === 0) {
        topicsList.innerHTML = '<div class="topic-row"><span class="topic-text" style="grid-column: 1/-1; text-align: center;">No topics selected</span></div>';
        topicsCount.textContent = '0 topics configured';
        return;
    }
    
    let html = '';
    
    for (let i = 0; i < allTopics.length; i++) {
        const topic = allTopics[i];
        const isCustom = customTopics.includes(topic);
        html += `
            <div class="topic-row" data-index="${i}" data-custom="${isCustom}">
                <span class="topic-name">${escapeHtml(topic.topic_name)}</span>
                <span class="topic-text">${escapeHtml(topic.topic_text)}</span>
                <button type="button" class="topic-remove-btn" onclick="removeTopic(${i}, ${isCustom})">Remove</button>
            </div>
        `;
    }
    
    topicsList.innerHTML = html;
    topicsCount.textContent = `${allTopics.length} topics configured`;
}

// Toggle edit mode
function toggleEditMode() {
    editMode = !editMode;
    const btn = document.getElementById('editTopicsBtn');
    const addSection = document.getElementById('addTopicSection');
    const container = document.querySelector('.topics-container');
    
    if (editMode) {
        btn.textContent = 'Done';
        btn.classList.add('active');
        addSection.style.display = 'block';
        container.classList.add('edit-mode');
        // Switch to custom mode when editing
        document.getElementById('topicSet').value = 'custom';
        updateTopicSetDescription();
    } else {
        btn.textContent = 'Edit Topics';
        btn.classList.remove('active');
        addSection.style.display = 'none';
        container.classList.remove('edit-mode');
    }
}

// Remove topic
function removeTopic(index, isCustom) {
    if (isCustom) {
        const customIndex = index - selectedTopics.length;
        customTopics.splice(customIndex, 1);
    } else {
        selectedTopics.splice(index, 1);
    }
    
    // Switch to custom mode since user modified
    document.getElementById('topicSet').value = 'custom';
    updateTopicSetDescription();
    
    renderTopics();
}

// Add custom topic
function addCustomTopic() {
    const nameInput = document.getElementById('customTopicName');
    const textInput = document.getElementById('customTopicText');
    
    const name = nameInput.value.trim();
    const text = textInput.value.trim();
    
    if (!name || !text) {
        showNotification('Please enter both topic name and query text', 'error');
        return;
    }
    
    // Validate that {company} placeholder is present
    if (!text.includes('{company}')) {
        showNotification('Query text must include {company} placeholder', 'error');
        return;
    }
    
    customTopics.push({
        topic_name: name,
        topic_text: text
    });
    
    // Clear inputs
    nameInput.value = '';
    textInput.value = '';
    
    // Switch to custom mode
    document.getElementById('topicSet').value = 'custom';
    updateTopicSetDescription();
    
    renderTopics();
    showNotification(`Added topic: ${name}`, 'success');
}

// Handle form submission
async function handleSubmit(e) {
    e.preventDefault();
    
    const reportName = document.getElementById('reportName').value;
    const topN = parseInt(document.getElementById('topN').value) || 5;
    const daysLookback = parseInt(document.getElementById('daysLookback').value) || 1;
    const tickersInput = document.getElementById('tickers').value;
    
    // Parse tickers
    const tickers = tickersInput.split(',')
        .map(t => t.trim())
        .filter(t => t.length > 0);
    
    if (tickers.length < topN * 2) {
        showNotification(`Need at least ${topN * 2} tickers to find top ${topN} movers`, 'error');
        return;
    }
    
    // Combine selected topics and custom topics
    const allTopics = [...selectedTopics, ...customTopics];
    
    if (allTopics.length === 0) {
        showNotification('Please select at least one topic', 'error');
        return;
    }
    
    const generateBtn = document.getElementById('generateBtn');
    generateBtn.disabled = true;
    generateBtn.textContent = 'Generating...';
    
    try {
        const response = await apiRequest('/api/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tickers: tickers,
                report_name: reportName,
                top_n: topN,
                days_lookback: daysLookback,
                use_mini_topics: false,  // We're using custom topic selection now
                custom_topics: allTopics
            })
        });
        
        if (!response.ok) {
            const msg = await parseErrorMessage(response);
            throw new Error(msg);
        }
        
        const result = await response.json();
        showNotification(`Report generation started! Job ID: ${result.request_id}`, 'success');
        
        loadReports();
        pollJobStatus(result.request_id);
        
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = 'Generate Report';
    }
}

// Load reports list
async function loadReports() {
    const reportsList = document.getElementById('reportsList');
    
    try {
        const response = await apiRequest('/api/reports');
        if (!response.ok) {
            const msg = await parseErrorMessage(response);
            throw new Error(msg);
        }
        
        const data = await response.json();
        const jobs = data.jobs || [];
        
        if (jobs.length === 0) {
            reportsList.innerHTML = '<div class="empty-state">No reports yet. Generate your first report!</div>';
            return;
        }
        
        reportsList.innerHTML = jobs.map(job => {
            const statusColor = {
                'pending': '#8b949e',
                'processing': '#58a6ff',
                'complete': '#238636',
                'failed': '#da3633'
            }[job.status] || '#8b949e';
            
            const createdAt = new Date(job.created_at).toLocaleString();
            
            return `
                <div class="report-card">
                    <div class="report-header">
                        <div class="report-info">
                            <h3>${escapeHtml(job.report_name)}</h3>
                            <span class="report-meta">Top ${job.top_n} movers | ${job.watchlist_size} stocks | ${createdAt}</span>
                        </div>
                        <span class="status-badge" style="background: ${statusColor}20; color: ${statusColor}">
                            ${job.status}
                        </span>
                    </div>
                    <div class="report-actions">
                        ${job.status === 'complete' ? `
                            <button class="btn btn-small btn-success" onclick="viewReport('${job.job_id}', '${escapeHtml(job.report_name)}')">
                                View Report
                            </button>
                            <button class="btn btn-small btn-secondary" onclick="downloadReport('${job.job_id}')">
                                Download
                            </button>
                            <button class="btn btn-small btn-secondary" onclick="downloadSearchResults('${job.job_id}')">
                                Search Results
                            </button>
                        ` : ''}
                        <button class="btn btn-small btn-danger" onclick="deleteJob('${job.job_id}', '${escapeHtml(job.report_name)}')">
                            Delete
                        </button>
                    </div>
                    ${job.error ? `<div class="error-message">${escapeHtml(job.error)}</div>` : ''}
                </div>
            `;
        }).join('');
        
        // Start polling for processing jobs
        jobs.forEach(job => {
            if (job.status === 'processing' || job.status === 'pending') {
                if (!pollingIntervals[job.job_id]) {
                    pollJobStatus(job.job_id);
                }
            }
        });
        
    } catch (error) {
        reportsList.innerHTML = `<div class="error-state">Error loading reports: ${error.message}</div>`;
    }
}

// Poll job status
function pollJobStatus(jobId) {
    if (pollingIntervals[jobId]) {
        clearInterval(pollingIntervals[jobId]);
    }
    
    checkJobStatus(jobId);
    
    pollingIntervals[jobId] = setInterval(() => {
        checkJobStatus(jobId);
    }, 3000);
}

async function checkJobStatus(jobId) {
    try {
        const response = await apiRequest(`/api/status/${jobId}`);
        const data = await response.json();
        
        if (data.status === 'complete') {
            clearInterval(pollingIntervals[jobId]);
            delete pollingIntervals[jobId];
            showNotification('Report completed!', 'success');
            loadReports();
        } else if (data.status === 'failed') {
            clearInterval(pollingIntervals[jobId]);
            delete pollingIntervals[jobId];
            showNotification(`Report failed: ${data.error}`, 'error');
            loadReports();
        }
    } catch (error) {
        console.error('Error checking job status:', error);
    }
}

// View report in modal
async function viewReport(jobId, reportName) {
    const modal = document.getElementById('reportModal');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');
    
    modalTitle.textContent = reportName;
    modal.style.display = 'block';
    modalBody.innerHTML = '<div class="loading">Loading report...</div>';
    
    try {
        const response = await apiRequest(`/api/report/${jobId}/view`);
        if (!response.ok) throw new Error('Failed to load report');
        
        const markdown = await response.text();
        modalBody.innerHTML = markdownToHtml(markdown);
        
    } catch (error) {
        modalBody.innerHTML = `<div class="error-state">Error: ${error.message}</div>`;
    }
}

function closeModal() {
    document.getElementById('reportModal').style.display = 'none';
}

// Download functions - use fetch with headers then create download
async function downloadReport(jobId) {
    try {
        const response = await apiRequest(`/api/report/${jobId}/download`);
        if (!response.ok) throw new Error('Failed to download report');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `movers_report_${jobId}.md`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    } catch (error) {
        showNotification(`Download failed: ${error.message}`, 'error');
    }
}

async function downloadSearchResults(jobId) {
    try {
        const response = await apiRequest(`/api/report/${jobId}/search-results`);
        if (!response.ok) throw new Error('Failed to download search results');
        
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `search_results_${jobId}.csv`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
    } catch (error) {
        showNotification(`Download failed: ${error.message}`, 'error');
    }
}

// Delete job
async function deleteJob(jobId, reportName) {
    if (!confirm(`Delete report "${reportName}"?`)) return;
    
    try {
        const response = await apiRequest(`/api/report/${jobId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete');
        
        showNotification('Report deleted', 'success');
        loadReports();
        
        if (pollingIntervals[jobId]) {
            clearInterval(pollingIntervals[jobId]);
            delete pollingIntervals[jobId];
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
    }
}

// Notification
function showNotification(message, type = 'success') {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type} show`;
    
    setTimeout(() => {
        notification.classList.remove('show');
    }, 3000);
}

// Utility functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Simple markdown to HTML converter
function markdownToHtml(markdown) {
    let html = markdown;
    
    // Escape HTML
    html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    
    // Headers
    html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>');
    html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
    
    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    
    // Italic
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    
    // Tables - improved parsing with thead/tbody
    const tableRegex = /(\|.+\|\n)+/g;
    html = html.replace(tableRegex, function(tableBlock) {
        const lines = tableBlock.trim().split('\n');
        if (lines.length < 2) return tableBlock;
        
        let tableHtml = '<table>';
        let inBody = false;
        
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const cells = line.split('|').filter((_, idx, arr) => idx > 0 && idx < arr.length - 1).map(c => c.trim());
            
            // Check if this is the separator row (contains only dashes)
            if (cells.every(c => c.match(/^[-:]+$/))) {
                tableHtml += '</thead><tbody>';
                inBody = true;
                continue;
            }
            
            if (i === 0) {
                // First row is header
                tableHtml += '<thead><tr>' + cells.map(c => `<th>${c}</th>`).join('') + '</tr>';
            } else {
                // Data rows
                tableHtml += '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
            }
        }
        
        if (inBody) {
            tableHtml += '</tbody>';
        }
        tableHtml += '</table>';
        
        return tableHtml;
    });
    
    // Horizontal rules
    html = html.replace(/^---$/gim, '<hr>');
    
    // Line breaks for bullets
    html = html.replace(/^• /gm, '<br>• ');
    
    // Paragraphs
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p>(<h[1-6]>)/g, '$1');
    html = html.replace(/(<\/h[1-6]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<table>)/g, '$1');
    html = html.replace(/(<\/table>)<\/p>/g, '$1');
    html = html.replace(/<p>(<hr>)<\/p>/g, '$1');
    
    return html;
}

// Close modal on outside click
document.getElementById('reportModal').addEventListener('click', function(e) {
    if (e.target === this) closeModal();
});

// Close modal on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeModal();
});
