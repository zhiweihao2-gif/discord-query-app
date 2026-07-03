document.addEventListener('DOMContentLoaded', function () {
    loadTableInfo();

    const playerId = document.getElementById('playerId');
    if (playerId) {
        playerId.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') doLookup();
        });
    }

    const workSelect = document.getElementById('workSelect');
    if (workSelect) {
        workSelect.addEventListener('change', doLookup);
    }

    setupUpload();
});

// ── 表格資訊 + 下拉選項 ──
async function loadTableInfo() {
    try {
        const resp = await fetch('/table/info');
        const data = await resp.json();
        const el = document.getElementById('tableInfo');
        if (!data.total_rows) { el.textContent = ''; return; }
        el.textContent = `當前數據：${data.total_rows} 條記錄`;
        loadWorkOptions();
    } catch (e) { }
}

async function loadWorkOptions() {
    try {
        const resp = await fetch('/data');
        const data = await resp.json();
        if (data.error || !data.results.length) return;

        const select = document.getElementById('workSelect');
        if (!select) return;

        let workCol = null;
        for (const col of data.columns) {
            if (col.includes('作品') || col.toLowerCase().includes('work') || col.includes('項目')) {
                workCol = col;
                break;
            }
        }
        if (!workCol && data.columns.length >= 2) workCol = data.columns[1];

        const works = [...new Set(data.results.map(r => String(r[workCol] || '')))].filter(Boolean).sort();

        select.innerHTML = '<option value="">全部作品</option>';
        works.forEach(w => {
            select.innerHTML += `<option value="${escapeHtml(w)}">${escapeHtml(w)}</option>`;
        });
    } catch (e) { }
}

// ── 查詢 ──
async function doLookup() {
    const playerId = document.getElementById('playerId')?.value.trim() || '';
    const work = document.getElementById('workSelect')?.value || '';
    const resultDiv = document.getElementById('result');

    if (!playerId) {
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '<div class="result-card result-error">請輸入玩家ID</div>';
        return;
    }

    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div class="result-card result-loading"><div class="spinner"></div><p>查詢中...</p></div>';

    const params = new URLSearchParams();
    params.set('player_id', playerId);
    if (work) params.set('work', work);

    try {
        const resp = await fetch(`/lookup?${params.toString()}`);
        const data = await resp.json();

        if (data.error) {
            resultDiv.innerHTML = `<div class="result-card result-error"><i class="fas fa-exclamation-circle"></i> ${escapeHtml(data.error)}</div>`;
            return;
        }

        if (data.paid) {
            resultDiv.innerHTML = `
                <div class="result-card result-paid">
                    <div class="result-icon"><i class="fas fa-check-circle"></i></div>
                    <div class="result-title">${escapeHtml(data.message)}</div>
                    <div class="result-meta">玩家ID: ${escapeHtml(data.player_id)} | 作品: ${escapeHtml(data.work)}</div>
                </div>`;
        } else {
            // 未購買（不在列表中 = 同樣視為未購買）
            const reportText = data.report;
            resultDiv.innerHTML = `
                <div class="result-card result-unpaid">
                    <div class="result-icon"><i class="fas fa-exclamation-triangle"></i></div>
                    <div class="result-title">⚠️ ${escapeHtml(data.message)}</div>
                    <div class="result-meta">點擊下方按鈕複製舉報信息</div>
                    <div class="report-box">
                        <pre>${escapeHtml(reportText)}</pre>
                    </div>
                    <button class="btn btn-copy" onclick="copyReport()">
                        <i class="fas fa-copy"></i> 複製舉報信息
                    </button>
                    <span id="copyFeedback" class="copy-feedback"></span>
                </div>`;
            window._lastReport = reportText;
        }
    } catch (e) {
        resultDiv.innerHTML = `<div class="result-card result-error"><i class="fas fa-times-circle"></i> 查詢失敗: ${escapeHtml(e.message)}</div>`;
    }
}

function copyReport() {
    const text = window._lastReport || '';
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        const fb = document.getElementById('copyFeedback');
        if (fb) {
            fb.textContent = '✅ 已複製到剪貼簿！';
            fb.style.display = 'inline';
            setTimeout(() => { fb.style.display = 'none'; }, 2000);
        }
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        const fb = document.getElementById('copyFeedback');
        if (fb) {
            fb.textContent = '✅ 已複製！';
            fb.style.display = 'inline';
            setTimeout(() => { fb.style.display = 'none'; }, 2000);
        }
    });
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── 上傳 ──
function showUpload() { document.getElementById('uploadModal').style.display = 'flex'; }
function closeUpload() {
    document.getElementById('uploadModal').style.display = 'none';
    document.getElementById('uploadResult').innerHTML = '';
}
function setupUpload() {
    const area = document.getElementById('uploadArea');
    const input = document.getElementById('fileInput');
    if (!area || !input) return;
    area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('dragover'); });
    area.addEventListener('dragleave', e => { area.classList.remove('dragover'); });
    area.addEventListener('drop', e => {
        e.preventDefault();
        area.classList.remove('dragover');
        if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', e => { if (e.target.files.length) uploadFile(e.target.files[0]); });
}
async function uploadFile(file) {
    const rd = document.getElementById('uploadResult');
    rd.innerHTML = '<p style="color:var(--text-muted);"><div class="spinner"></div> 上傳中...</p>';
    const fd = new FormData(); fd.append('file', file);
    try {
        const r = await fetch('/upload', { method: 'POST', body: fd });
        const d = await r.json();
        rd.innerHTML = d.error
            ? `<p class="error"><i class="fas fa-times-circle"></i> ${escapeHtml(d.error)}</p>`
            : `<p class="success"><i class="fas fa-check-circle"></i> ${d.message} — ${d.rows} 行</p>`;
        loadTableInfo();
    } catch (e) {
        rd.innerHTML = '<p class="error"><i class="fas fa-times-circle"></i> 上傳失敗</p>';
    }
}

// ── Google Sheets ──
function showSheetsConfig() {
    document.getElementById('sheetsModal').style.display = 'flex';
    fetch('/sheets/url').then(r => r.json()).then(d => {
        if (d.url) document.getElementById('sheetsUrl').value = d.url;
    });
}
function closeSheetsConfig() {
    document.getElementById('sheetsModal').style.display = 'none';
    document.getElementById('sheetsResult').innerHTML = '';
}
async function fetchSheets() {
    const rd = document.getElementById('sheetsResult');
    const url = document.getElementById('sheetsUrl').value.trim();
    if (!url) { rd.innerHTML = '<p class="error">請輸入 Google Sheets 連結</p>'; return; }
    rd.innerHTML = '<p style="color:var(--text-muted);"><div class="spinner"></div> 同步中...</p>';
    try {
        const r = await fetch('/sheets/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
        const d = await r.json();
        rd.innerHTML = d.error
            ? `<p class="error"><i class="fas fa-times-circle"></i> ${escapeHtml(d.error)}</p>`
            : `<p class="success"><i class="fas fa-check-circle"></i> 同步成功 — ${d.rows} 行</p>`;
        loadTableInfo();
    } catch (e) {
        rd.innerHTML = '<p class="error">同步失敗</p>';
    }
}
