/**
 * Attune Steel Dev — Floating Dev Toolbar
 * Injected into the main window via executeJavaScript in main-dev.js.
 * This file exists as documentation / for potential dynamic loading.
 *
 * The actual toolbar injection happens in main-dev.js showMainApp() since
 * it needs to run in the renderer context after page load.
 *
 * Toolbar shows: port, memory usage, reading count
 * Updates every 5 seconds via /api/dev/status
 */

// This script can be loaded via <script> in index.html for dev builds,
// but currently injection via executeJavaScript is preferred to avoid
// touching production files.

(function() {
  if (document.getElementById('attune-dev-toolbar')) return; // Already injected

  const toolbar = document.createElement('div');
  toolbar.id = 'attune-dev-toolbar';
  toolbar.style.cssText = [
    'position:fixed', 'bottom:8px', 'left:8px',
    'background:rgba(0,0,0,0.85)', 'color:#a3e635',
    'padding:4px 12px', 'border-radius:6px',
    'font-size:11px', 'font-family:ui-monospace,monospace',
    'z-index:99999', 'display:flex', 'gap:12px',
    'pointer-events:none',
  ].join(';');

  toolbar.innerHTML = '<span>:8768</span><span id="dev-mem">--MB</span><span id="dev-readings">0 readings</span>';
  document.body.appendChild(toolbar);

  setInterval(async () => {
    try {
      const r = await fetch('/api/dev/status');
      if (r.ok) {
        const d = await r.json();
        document.getElementById('dev-mem').textContent = d.memory_mb + 'MB';
        document.getElementById('dev-readings').textContent = d.reading_count + ' readings';
      }
    } catch {}
  }, 5000);
})();
