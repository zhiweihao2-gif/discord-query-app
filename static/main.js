// ── 页面加载后 ──
document.addEventListener('DOMContentLoaded', function() {
    // 加载表格信息 + 下拉框选项
    loadTableInfo();

    // 搜索框回车触发
    const playerId = document.getElementById('playerId');
    if (playerId) {
        playerId.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') doSearch();
        });
    }

    // 下拉框切换自动搜索
    const workSelect = document.getElementById('workSelect');
    if (workSelect) {
        workSelect.addEventListener('change', function() {
            doSearch();
        });
    }

    // 上传弹窗
    setupUpload();
});

// ── 表格信息 + 填充下拉框 ──
async function loadTableInfo() {
    try {
        const resp = await fetch('/table/info');
        const data = await resp.json();
        const el = document.getElementById('tableInfo');
        if (data.error) { el.textContent = ''; return; }

        if (data.total_rows > 0) {
            el.textContent = `当前数据: ${data.total_rows} 条记录, ${data.columns.length} 个字段`;
        } else {
            el.textContent = '暂无数据，请上传表格或同步 Google Sheets';
        }

        // 填充下拉框
        if (data.total_rows > 0) {
            loadWorkOptions();
        }
    } catch(e) {}
}

async function loadWorkOptions() {
    try {
        const resp = await fetch('/search?q=');
        const data = await resp.json();
        if (data.error) return;

        const select = document.getElementById('workSelect');
        if (!select) return;

        // 找"作品"列（模糊匹配）
        let workCol = null;
        for (const col of data.columns) {
            if (col.includes('作品') || col.toLowerCase().includes('work') || col.includes('項目')) {
                workCol = col;
                break;
            }
        }
        // 如果没找到，用第2列（第1列通常是ID）
        if (!workCol && data.columns.length >= 2) {
            workCol = data.columns[1];
        }

        // 去重
        const works = [...new Set(data.results.map(r => String(r[workCol] || '')))].filter(Boolean).sort();

        select.innerHTML = '<option value="">全部作品</option>';
        works.forEach(w => {
            select.innerHTML += `<option value="${escapeHtml(w)}">${escapeHtml(w)}</option>`;
        });
    } catch(e) {}
}

// ── 搜索 ──
let currentResults = [];
let currentKeyword = '';

async function doSearch() {
    const playerId = document.getElementById('playerId')?.value.trim() || '';
    const work = document.getElementById('workSelect')?.value || '';

    const resultsDiv = document.getElementById('results');
    const head = document.getElementById('resultsHead');
    const body = document.getElementById('resultsBody');
    const title = document.getElementById('resultsTitle');

    // 显示加载中
    resultsDiv.style.display = 'block';
    body.innerHTML = '<tr><td colspan="99" class="loading"><div class="spinner"></div><p>搜索中...</p></td></tr>';

    // 构建参数
    const params = new URLSearchParams();
    if (playerId) params.set('player_id', playerId);
    if (work) params.set('work', work);

    try {
        const resp = await fetch(`/search?${params.toString()}`);
        const data = await resp.json();

        if (data.error) {
            if (data.error === '未登录') { location.reload(); }
            return;
        }

        currentResults = data.results;
        currentKeyword = data.keyword || '';
        const total = data.total;
        const columns = data.columns;

        // 标题
        let conditions = [];
        if (playerId) conditions.push(`玩家ID: ${playerId}`);
        if (work) conditions.push(`作品: ${work}`);
        const condStr = conditions.length ? conditions.join(' + ') : '全部';
        title.innerHTML = `<i class="fas fa-list"></i> ${condStr} — ${total} 条结果`;

        if (columns.length === 0) {
            head.innerHTML = '';
            body.innerHTML = '<tr><td colspan="99" style="text-align:center;color:var(--text-muted);padding:40px;">暂无数据</td></tr>';
            return;
        }

        head.innerHTML = '<tr>' + columns.map(c => `<th>${escapeHtml(c)}</th>`).join('') + '</tr>';

        if (total === 0) {
            body.innerHTML = '<tr><td colspan="99" style="text-align:center;color:var(--text-muted);padding:40px;">未找到匹配结果</td></tr>';
            return;
        }

        body.innerHTML = data.results.map(row => {
            return '<tr>' + columns.map(c => {
                let val = row[c] !== undefined ? String(row[c]) : '';
                return `<td>${escapeHtml(val)}</td>`;
            }).join('') + '</tr>';
        }).join('');
    } catch(e) {
        body.innerHTML = `<tr><td colspan="99" style="text-align:center;color:var(--red);padding:40px;">搜索失败: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── 导出 CSV ──
function exportCSV() {
    if (currentResults.length === 0) {
        alert('没有可导出的数据');
        return;
    }
    const columns = Object.keys(currentResults[0]);
    const lines = [columns.join(',')];
    currentResults.forEach(row => {
        lines.push(columns.map(c => {
            let val = row[c] !== undefined ? String(row[c]) : '';
            if (val.includes(',') || val.includes('"') || val.includes('\n')) {
                val = '"' + val.replace(/"/g, '""') + '"';
            }
            return val;
        }).join(','));
    });
    const csv = '\uFEFF' + lines.join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `search_results_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// ── 上传弹窗 ──
function showUpload() {
    document.getElementById('uploadModal').style.display = 'flex';
}
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
    input.addEventListener('change', e => {
        if (e.target.files.length) uploadFile(e.target.files[0]);
    });
}
async function uploadFile(file) {
    const resultDiv = document.getElementById('uploadResult');
    resultDiv.innerHTML = '<p style="color:var(--text-muted);"><div class="spinner"></div> 上传中...</p>';
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch('/upload', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.error) {
            resultDiv.innerHTML = `<p class="error"><i class="fas fa-times-circle"></i> ${escapeHtml(data.error)}</p>`;
        } else {
            resultDiv.innerHTML = `<p class="success"><i class="fas fa-check-circle"></i> ${data.message} — ${data.rows} 行, ${data.columns.length} 列</p>`;
            loadTableInfo();
            doSearch();
        }
    } catch(e) {
        resultDiv.innerHTML = `<p class="error"><i class="fas fa-times-circle"></i> 上传失败: ${escapeHtml(e.message)}</p>`;
    }
}

// ── Google Sheets 弹窗 ──
function showSheetsConfig() {
    document.getElementById('sheetsModal').style.display = 'flex';
    // 加载已保存的 URL
    fetch('/sheets/url').then(r => r.json()).then(d => {
        if (d.url) document.getElementById('sheetsUrl').value = d.url;
    });
}
function closeSheetsConfig() {
    document.getElementById('sheetsModal').style.display = 'none';
    document.getElementById('sheetsResult').innerHTML = '';
}
async function fetchSheets() {
    const resultDiv = document.getElementById('sheetsResult');
    const url = document.getElementById('sheetsUrl').value.trim();
    if (!url) {
        resultDiv.innerHTML = '<p class="error"><i class="fas fa-times-circle"></i> 请输入 Google Sheets 链接</p>';
        return;
    }
    resultDiv.innerHTML = '<p style="color:var(--text-muted);"><div class="spinner"></div> 同步中...</p>';
    try {
        const resp = await fetch('/sheets/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        const data = await resp.json();
        if (data.error) {
            resultDiv.innerHTML = `<p class="error"><i class="fas fa-times-circle"></i> ${escapeHtml(data.error)}</p>`;
        } else {
            resultDiv.innerHTML = `<p class="success"><i class="fas fa-check-circle"></i> 同步成功 — ${data.rows} 行, ${data.columns.length} 列</p>`;
            loadTableInfo();
            doSearch();
        }
    } catch(e) {
        resultDiv.innerHTML = `<p class="error"><i class="fas fa-times-circle"></i> 同步失败: ${escapeHtml(e.message)}</p>`;
    }
}
