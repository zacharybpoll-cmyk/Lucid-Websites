/**
 * Attune Steel Dev — Diagnostics Dashboard Logic
 */

const API = 'http://127.0.0.1:8768';
const memoryHistory = [];

// ============ Tab Navigation ============
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
  });
});

// ============ Fetch Helpers ============
async function fetchJSON(path) {
  try {
    const r = await fetch(API + path);
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

function statusBadge(code) {
  const cls = code < 300 ? 'badge-2xx' : code < 500 ? 'badge-4xx' : 'badge-5xx';
  return `<span class="badge ${cls}">${code}</span>`;
}

function shortTime(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ============ Overview ============
async function refreshOverview() {
  const [status, health, timings] = await Promise.all([
    fetchJSON('/api/dev/status'),
    fetchJSON('/api/health'),
    window.attuneDev ? window.attuneDev.getStartupTimings() : null,
  ]);

  const el = document.getElementById('overview-stats');
  if (status) {
    memoryHistory.push(status.memory_mb);
    if (memoryHistory.length > 60) memoryHistory.shift();

    el.innerHTML = `
      <div class="stat"><div class="label">Memory (RSS)</div><div class="value ${status.memory_mb > 1500 ? 'red' : status.memory_mb > 800 ? 'yellow' : 'green'}">${status.memory_mb} MB</div></div>
      <div class="stat"><div class="label">PID</div><div class="value">${status.pid}</div></div>
      <div class="stat"><div class="label">Uptime</div><div class="value">${Math.floor(status.uptime_sec / 60)}m ${status.uptime_sec % 60}s</div></div>
      <div class="stat"><div class="label">Readings</div><div class="value">${status.reading_count}</div></div>
      <div class="stat"><div class="label">Backend</div><div class="value ${health && health.ready ? 'green' : 'red'}">${health && health.ready ? 'Ready' : 'Not Ready'}</div></div>
      <div class="stat"><div class="label">Port</div><div class="value">8768</div></div>
    `;

    // Memory chart
    renderMemoryChart();
  }

  // Startup timings
  if (timings) {
    const t = timings;
    const lines = [];
    if (t.appReady) lines.push(`App Ready: ${new Date(t.appReady).toLocaleTimeString()}`);
    if (t.splashShown && t.splashStart) lines.push(`Splash: +${t.splashShown - t.splashStart}ms`);
    if (t.pythonSpawned && t.pythonSpawnStart) lines.push(`Python Spawn: +${t.pythonSpawned - t.pythonSpawnStart}ms`);
    if (t.serverReady && t.pythonSpawnStart) lines.push(`Server Ready: +${t.serverReady - t.pythonSpawnStart}ms (from spawn)`);
    if (t.mainWindowShown && t.appReady) lines.push(`Total Startup: +${t.mainWindowShown - t.appReady}ms`);
    document.getElementById('startup-timings').textContent = lines.join('\n') || 'No timings available';
  }
}

function renderMemoryChart() {
  const container = document.getElementById('memory-chart');
  if (!memoryHistory.length) return;

  const max = Math.max(...memoryHistory, 512);
  const barW = Math.max(3, Math.floor(container.clientWidth / 60));
  let html = '';
  memoryHistory.forEach((val, i) => {
    const h = Math.round((val / max) * 110);
    const color = val > 1500 ? 'var(--red)' : val > 800 ? 'var(--yellow)' : 'var(--accent)';
    html += `<div class="chart-bar" style="left:${i * barW}px;width:${barW - 1}px;height:${h}px;background:${color};"></div>`;
  });
  container.innerHTML = html;
}

// ============ API Log ============
async function refreshApiLog() {
  const data = await fetchJSON('/api/dev/request-log?limit=100');
  if (!data) return;

  const filter = document.getElementById('api-filter').value.toLowerCase();
  const filtered = filter ? data.filter(e => e.path.toLowerCase().includes(filter)) : data;
  const tbody = document.getElementById('api-log-body');
  tbody.innerHTML = filtered.reverse().map(e => `
    <tr>
      <td>${shortTime(e.ts)}</td>
      <td>${e.method}</td>
      <td>${e.path}</td>
      <td>${statusBadge(e.status)}</td>
      <td>${e.latency_ms}ms</td>
    </tr>
  `).join('');
}

document.getElementById('api-filter').addEventListener('input', refreshApiLog);

// ============ Performance ============
async function refreshPerformance() {
  const data = await fetchJSON('/api/dev/request-log?limit=200');
  if (!data || !data.length) return;

  // Latency histogram
  const buckets = { '<10ms': 0, '10-50ms': 0, '50-100ms': 0, '100-500ms': 0, '500ms-1s': 0, '>1s': 0 };
  data.forEach(e => {
    const ms = e.latency_ms;
    if (ms < 10) buckets['<10ms']++;
    else if (ms < 50) buckets['10-50ms']++;
    else if (ms < 100) buckets['50-100ms']++;
    else if (ms < 500) buckets['100-500ms']++;
    else if (ms < 1000) buckets['500ms-1s']++;
    else buckets['>1s']++;
  });

  const maxBucket = Math.max(...Object.values(buckets), 1);
  document.getElementById('latency-histogram').innerHTML = Object.entries(buckets).map(([label, count]) => {
    const pct = Math.round((count / maxBucket) * 100);
    return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">
      <span style="width:70px;font-size:11px;color:var(--text-dim);text-align:right;">${label}</span>
      <div style="flex:1;height:16px;background:var(--surface);border-radius:3px;overflow:hidden;">
        <div style="width:${pct}%;height:100%;background:var(--accent);border-radius:3px;"></div>
      </div>
      <span style="width:30px;font-size:11px;font-family:var(--mono);">${count}</span>
    </div>`;
  }).join('');

  // Slowest requests
  const sorted = [...data].sort((a, b) => b.latency_ms - a.latency_ms).slice(0, 15);
  document.getElementById('slowest-requests').innerHTML = sorted.map(e => `
    <tr>
      <td>${e.path}</td>
      <td>${e.method}</td>
      <td style="color:${e.latency_ms > 500 ? 'var(--red)' : e.latency_ms > 100 ? 'var(--yellow)' : 'var(--green)'}">${e.latency_ms}ms</td>
      <td>${statusBadge(e.status)}</td>
    </tr>
  `).join('');
}

// ============ State Inspector ============
async function refreshState() {
  const [health, dashboard] = await Promise.all([
    fetchJSON('/api/health'),
    fetchJSON('/api/dashboard'),
  ]);

  document.getElementById('health-json').textContent = JSON.stringify(health, null, 2) || 'Failed to fetch';
  document.getElementById('dashboard-json').textContent = JSON.stringify(dashboard, null, 2)?.substring(0, 3000) || 'Failed to fetch';
}

// ============ Python Logs ============
async function refreshPythonLogs() {
  let logs = null;
  if (window.attuneDev) {
    logs = await window.attuneDev.getPythonLogs();
  }

  const viewer = document.getElementById('python-log-viewer');
  if (logs && logs.length) {
    viewer.innerHTML = logs.map(l => {
      const time = new Date(l.ts).toLocaleTimeString('en-US', { hour12: false });
      return `<div class="log-line ${l.level}">[${time}] ${escapeHtml(l.msg)}</div>`;
    }).join('');
    viewer.scrollTop = viewer.scrollHeight;
  } else {
    viewer.textContent = 'No logs captured yet. Logs appear here once the Python backend produces output.';
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ============ Quick Actions ============
async function doAction(action) {
  const result = document.getElementById('action-result');
  result.textContent = `Running: ${action}...`;

  try {
    let data;
    switch (action) {
      case 'restart':
        if (window.attuneDev) data = await window.attuneDev.restartBackend();
        else data = { error: 'IPC not available' };
        break;
      case 'gc':
        data = await fetchJSON('/api/dev/force-gc');
        break;
      case 'snapshot':
        data = await fetchJSON('/api/dev/debug-snapshot');
        break;
      case 'reload':
        // This reloads the main window, not diagnostics
        result.textContent = 'Sent reload signal to main window.';
        return;
      case 'clear-cache':
        result.textContent = 'Cache clear requires Electron IPC — use DevTools console.';
        return;
      case 'reset-db': {
        const confirmed = confirm('This will DELETE ALL DATA. Are you sure?');
        if (!confirmed) { result.textContent = 'Cancelled.'; return; }
        const r = await fetch(API + '/api/dev/reset-database', { method: 'POST' });
        data = await r.json();
        break;
      }
    }
    result.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    result.textContent = `Error: ${e.message}`;
  }
}

// ============ Database ============
async function loadTableList() {
  const data = await fetchJSON('/api/dev/tables');
  if (!data) return;

  const select = document.getElementById('db-table-select');
  select.innerHTML = '<option value="">-- Select table --</option>';
  data.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t.name;
    opt.textContent = `${t.name} (${t.rows} rows)`;
    select.appendChild(opt);
  });
}

document.getElementById('db-table-select').addEventListener('change', async (e) => {
  const name = e.target.value;
  if (!name) { document.getElementById('db-table-view').innerHTML = ''; return; }

  const data = await fetchJSON(`/api/dev/table/${name}?limit=50`);
  if (!data) return;

  document.getElementById('db-table-count').textContent = `${data.total} total rows`;

  let html = '<div style="overflow-x:auto;"><table><thead><tr>';
  data.columns.forEach(c => { html += `<th>${escapeHtml(c)}</th>`; });
  html += '</tr></thead><tbody>';
  data.rows.forEach(row => {
    html += '<tr>';
    row.forEach(val => {
      const display = val === null ? '<span style="color:var(--text-dim)">NULL</span>' : escapeHtml(String(val)).substring(0, 100);
      html += `<td>${display}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  document.getElementById('db-table-view').innerHTML = html;
});

async function runSQL() {
  const sql = document.getElementById('sql-input').value.trim();
  if (!sql) return;

  const resultEl = document.getElementById('sql-result');
  resultEl.innerHTML = 'Running...';

  try {
    const r = await fetch(API + '/api/dev/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql }),
    });
    const data = await r.json();

    if (data.error) {
      resultEl.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(data.error)}</span>`;
      return;
    }

    let html = `<div style="margin-bottom:6px;color:var(--text-dim);font-size:11px;">${data.row_count} rows</div>`;
    html += '<div style="overflow-x:auto;"><table><thead><tr>';
    data.columns.forEach(c => { html += `<th>${escapeHtml(c)}</th>`; });
    html += '</tr></thead><tbody>';
    data.rows.forEach(row => {
      html += '<tr>';
      row.forEach(val => {
        const display = val === null ? '<span style="color:var(--text-dim)">NULL</span>' : escapeHtml(String(val)).substring(0, 100);
        html += `<td>${display}</td>`;
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    resultEl.innerHTML = html;
  } catch (e) {
    resultEl.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(e.message)}</span>`;
  }
}

// ============ Polling Loop ============
function startPolling() {
  // Initial load
  refreshOverview();
  refreshApiLog();
  loadTableList();

  // Periodic refresh
  setInterval(refreshOverview, 3000);
  setInterval(refreshApiLog, 3000);
  setInterval(() => {
    const activeTab = document.querySelector('.tab.active')?.dataset.tab;
    if (activeTab === 'performance') refreshPerformance();
    if (activeTab === 'state') refreshState();
    if (activeTab === 'python-logs') refreshPythonLogs();
  }, 3000);
}

// Also refresh on tab switch
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const t = tab.dataset.tab;
    if (t === 'performance') refreshPerformance();
    if (t === 'state') refreshState();
    if (t === 'python-logs') refreshPythonLogs();
    if (t === 'database') loadTableList();
  });
});

startPolling();
