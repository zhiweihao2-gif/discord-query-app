// ── 页面加载后 ──
document.addEventListener('DOMContentLoaded', function() {
    // 加载表格信息
    loadTableInfo();

    // 搜索框回车触发搜索
    const input = document.getElementById('searchInput');
    if (input) {
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') doSearch();
        });

        // 实时搜索（防抖）
        let debounceTimer;
        input.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => doSearch(), 300);
        });
    }

    // 上传弹窗拖拽
    setupUpload();
});

// ── 表格信息 ──
async function loadTableInfo() {
    try {
        const resp = await fetch('/table/info');
        const data = await resp.json();
        const el = document.getElementById('tableInfo');
        if (data.error) {
            el.textContent = '';
            return;
        }
        if (data.total_rows > 0) {
            el.textContent = `当前数据: ${data.total_rows} 条记录, ${data.columns.length} 个字段 (${data.columns.join(', ')})`;
        } else {
            el.textContent = '暂无数据，请上传表格';
        }
    } catch(e) {
        // 未登录或其他错误，忽略
    }
}

// ── 搜索 ──
let currentResults = [];
let currentKeyword = '';

async function doSearch() {
    const input = document.getElementById('searchInput');
    if (!input) return;
    const keyword = input.value.trim();
    currentKeyword = keyword;

    const resultsDiv = document.getElementById('results');
    const head = document.getElementById('resultsHead');
    const body = document.getElementById('resultsBody');
    const title = document.getElementById('resultsTitle');

    // 显示加载中
    resultsDiv.style.display = 'block';
    body.innerHTML = '<tr><td colspan="99" class="loading"><div class="spinner"></div><p>搜索中...</p></td></tr>';

    try {
        const resp = await fetch(`/search?q=${encodeURIComponent(keyword)}`);
        const data = await resp.json();

        if (data.error) {
            if (data.error === '未登录') {
                location.reload();
            }
            return;
        }

        currentResults = data.results;
        const total = data.total;
        const columns = data.columns;

        title.innerHTML = `<i class="fas fa-list"></i> ${keyword ? `搜索 "${keyword}"` : '全部数据'} — ${total} 条结果`;

        // 表头
        if (columns.length === 0) {
            head.innerHTML = '';
            body.innerHTML = '<tr><td colspan="99" style="text-align:center;color:var(--text-muted);padding:40px;">暂无数据</td></tr>';
            return;
        }

        head.innerHTML = '<tr>' + columns.map(c => `<th>${escapeHtml(c)}</th>`).join('') + '</tr>';

        // 表体
        if (total === 0) {
            body.innerHTML = '<tr><td colspan="99" style="text-align:center;color:var(--text-muted);padding:40px;">未找到匹配结果</td></tr>';
            return;
        }

        body.innerHTML = data.results.map(row => {
            return '<tr>' + columns.map(c => {
                let val = row[c] !== undefined ? String(row[c]) : '';
                if (keyword) val = highlightKeyword(val, keyword);
                return `<td>${val}</td>`;
            }).join('') + '</tr>';
        }).join('');
    } catch(e) {
        body.innerHTML = `<tr><td colspan="99" style="text-align:center;color:var(--red);padding:40px;">搜索失败: ${escapeHtml(e.message)}</td></tr>`;
    }
}

// ── 高亮关键字 ──
function highlightKeyword(text, keyword) {
    if (!keyword) return escapeHtml(text);
    const escaped = escapeHtml(text);
    const regex = new RegExp(`(${escapeRegex(keyword)})`, 'gi');
    return escaped.replace(regex, '<span class="highlight">$1</span>');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
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
    const csv = '\uFEFF' + lines.join('\n'); // BOM for Excel
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

    // 拖拽
    area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('dragover'); });
    area.addEventListener('dragleave', e => { area.classList.remove('dragover'); });
    area.addEventListener('drop', e => {
        e.preventDefault();
        area.classList.remove('dragover');
        if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
    });

    // 点击选择
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
            doSearch(); // 刷新搜索结果
        }
    } catch(e) {
        resultDiv.innerHTML = `<p class="error"><i class="fas fa-times-circle"></i> 上传失败: ${escapeHtml(e.message)}</p>`;
    }
}
