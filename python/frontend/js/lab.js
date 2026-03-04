/**
 * lab.js — Biomarker Lab
 * "Nerd mode for your voice"
 *
 * Fetches biomarker data from:
 *   GET /api/lab/biomarkers   → { biomarkers: { [key]: { meta, latest_value, sparkline, ... } } }
 *   GET /api/lab/fingerprint  → { radar: [{dim, value}], unique_markers: [{name, description}], ... }
 *
 * Renders interactive cards with sparklines, range bars, and expandable science sections.
 * Exposed as window.labView for app.js navigation integration.
 */

const labView = (() => {

    // ── Module state ────────────────────────────────────────────────────────
    let _loaded      = false;
    let _data        = null;
    let _currentCat  = 'acoustic';

    // ── Entry point (called by app.js when navigating to #lab) ──────────────

    async function load() {
        const container = document.getElementById('lab-view');
        if (!container) return;

        // Return cached render if already loaded
        if (_loaded && _data) {
            render(_data);
            return;
        }

        container.innerHTML = '<div class="lab-loading">Loading biomarker data</div>';

        try {
            const [bioRes, fpRes] = await Promise.all([
                fetch('/api/lab/biomarkers'),
                fetch('/api/lab/fingerprint'),
            ]);

            if (!bioRes.ok || !fpRes.ok) {
                throw new Error(`API error: ${bioRes.status} / ${fpRes.status}`);
            }

            const bioData = await bioRes.json();
            const fpData  = await fpRes.json();

            _data   = { bioData, fpData };
            _loaded = true;
            render(_data);

        } catch (e) {
            console.warn('[lab] Failed to load biomarker data:', e);
            container.innerHTML = `
                <div class="lab-empty">
                    <p>No biomarker data yet.</p>
                    <p>Start a voice session to see your biomarkers here.</p>
                </div>`;
        }
    }

    // ── Top-level render ────────────────────────────────────────────────────

    function render({ bioData, fpData }) {
        const container = document.getElementById('lab-view');
        if (!container) return;

        container.innerHTML = `
            <div class="lab-header">
                <div class="lab-title">What Your Voice Reveals</div>
                <div class="lab-subtitle">Every reading, every biomarker — your complete voice fingerprint.</div>
            </div>
            ${renderFingerprint(fpData)}
            <div class="lab-tabs" role="tablist" aria-label="Biomarker categories">
                ${renderTabs()}
            </div>
            <div class="lab-cards-grid" id="lab-cards-grid" role="list">
                ${renderCards(bioData, _currentCat)}
            </div>
        `;

        // Draw canvas radar (must happen after DOM is painted)
        drawRadar(fpData && fpData.radar ? fpData.radar : []);

        // Animate range bars on next paint (start at 0, then transition to target)
        requestAnimationFrame(() => {
            container.querySelectorAll('.lab-range-marker').forEach(marker => {
                const pos = marker.dataset.pos;
                if (pos !== undefined) {
                    marker.style.left = (parseFloat(pos) * 100).toFixed(1) + '%';
                }
            });
            container.querySelectorAll('.lab-range-bar-fill').forEach(fill => {
                const pos = fill.dataset.pos;
                if (pos !== undefined) {
                    fill.style.width = (parseFloat(pos) * 100).toFixed(1) + '%';
                }
            });
        });
    }

    // ── Tabs ────────────────────────────────────────────────────────────────

    const CATEGORIES = [
        { id: 'acoustic',     label: 'Acoustic'      },
        { id: 'linguistic',   label: 'Linguistic'    },
        { id: 'mental_health', label: 'Mental Health' },
    ];

    function renderTabs() {
        return CATEGORIES.map(cat => `
            <button
                class="lab-tab ${_currentCat === cat.id ? 'active' : ''}"
                role="tab"
                aria-selected="${_currentCat === cat.id}"
                onclick="labView.switchCategory('${cat.id}')"
            >${sanitizeHTML(cat.label)}</button>
        `).join('');
    }

    // ── Fingerprint card ────────────────────────────────────────────────────

    function renderFingerprint(fpData) {
        if (!fpData) return '';

        const markers = (fpData.unique_markers || []);
        const markerHTML = markers.length
            ? markers.map(m => `
                <div class="lab-unique-marker-item">
                    <div class="lab-unique-marker-name">${sanitizeHTML(m.name || '')}</div>
                    <div class="lab-unique-marker-desc">${sanitizeHTML(m.description || '')}</div>
                </div>
            `).join('')
            : '<div style="font-size:12px;color:#8C96A0;">Needs more readings to compute.</div>';

        const totalReadings = Number.isFinite(fpData.total_readings) ? fpData.total_readings : 0;
        const daysTracked   = Number.isFinite(fpData.days_tracked)   ? fpData.days_tracked   : 0;

        return `
            <div class="lab-fingerprint-card">
                <div class="lab-fingerprint-left">
                    <div class="lab-fingerprint-section-label">YOUR VOICE FINGERPRINT</div>
                    <canvas
                        class="lab-radar-canvas"
                        id="lab-radar-canvas"
                        width="180"
                        height="180"
                        aria-label="Voice fingerprint radar chart"
                    ></canvas>
                </div>
                <div class="lab-fingerprint-right">
                    <div style="font-size:13px;font-weight:600;color:#1a1d21;margin-bottom:12px;">
                        What makes your voice unique
                    </div>
                    <div class="lab-unique-markers">${markerHTML}</div>
                    <div class="lab-fingerprint-meta">
                        ${totalReadings} readings
                        <span class="lab-fingerprint-meta-dot"></span>
                        ${daysTracked} day${daysTracked !== 1 ? 's' : ''} tracked
                    </div>
                </div>
            </div>
        `;
    }

    // ── Cards ────────────────────────────────────────────────────────────────

    function renderCards(bioData, category) {
        const biomarkers = (bioData && bioData.biomarkers) ? bioData.biomarkers : {};

        const filtered = Object.entries(biomarkers).filter(([, val]) => {
            return val && val.meta && val.meta.category === category;
        });

        if (filtered.length === 0) {
            return '<div class="lab-empty"><p>No data for this category yet.</p></div>';
        }

        return filtered.map(([key, val]) => renderCard(key, val)).join('');
    }

    function renderCard(key, val) {
        const meta      = val.meta     || {};
        const sparkline = Array.isArray(val.sparkline) ? val.sparkline : [];
        const latest    = val.latest_value;
        const rangePos  = typeof val.range_position === 'number'
            ? Math.min(1, Math.max(0, val.range_position))
            : 0.5;
        const withinNormal = val.within_normal_range !== false;  // default true if missing
        const zScore    = typeof val.z_score === 'number' ? val.z_score : 0;

        // Card status class
        let statusClass = 'within-normal';
        if (!withinNormal) {
            statusClass = zScore > 0 ? 'elevated' : 'low';
        }

        // Format latest value display
        let latestDisplay = '—';
        if (latest !== null && latest !== undefined && !isNaN(latest)) {
            const unit = (meta.normal_range && meta.normal_range.unit) ? meta.normal_range.unit : '';
            latestDisplay = parseFloat(latest).toFixed(2) + (unit ? '\u00a0' + unit : '');
        }

        // Evidence badge
        const evidenceLevel = meta.evidence_level || 'RESEARCH-ONLY';
        const evidenceLabel = evidenceLevel === 'RESEARCH-ONLY'
            ? 'Research Only'
            : (evidenceLevel.charAt(0).toUpperCase() + evidenceLevel.slice(1).toLowerCase());

        // Sparkline: only render if we have at least 2 non-null points
        const hasSparkline = sparkline.filter(v => v !== null && v !== undefined).length >= 2;

        // Safe content
        const displayName   = sanitizeHTML(meta.display_name   || key);
        const technicalName = sanitizeHTML(meta.technical_name || key);
        const description   = sanitizeHTML(meta.description    || '');
        const sciSummary    = sanitizeHTML(meta.science_summary || '');
        const sciCitation   = sanitizeHTML(meta.evidence_citation || '');
        const safeKey       = key.replace(/[^a-zA-Z0-9_-]/g, '_');

        return `
            <div class="lab-card ${statusClass}" id="lab-card-${safeKey}" role="listitem">
                <div class="lab-card-header">
                    <div class="lab-card-name-block">
                        <div class="lab-card-display-name">${displayName}</div>
                        <div class="lab-card-technical-name">${technicalName}</div>
                    </div>
                    <span class="lab-evidence-badge ${evidenceLevel}">${sanitizeHTML(evidenceLabel)}</span>
                </div>

                <div class="lab-card-description">${description}</div>

                <div class="lab-range-bar-wrap">
                    <div class="lab-range-label">
                        <span>Population range</span>
                        <span style="color:#1a1d21;font-weight:500">${sanitizeHTML(latestDisplay)}</span>
                    </div>
                    <div class="lab-range-bar-bg">
                        <div
                            class="lab-range-bar-fill"
                            style="width:0%"
                            data-pos="${rangePos}"
                            aria-valuenow="${Math.round(rangePos * 100)}"
                            aria-valuemin="0"
                            aria-valuemax="100"
                            role="progressbar"
                        ></div>
                        <div
                            class="lab-range-marker"
                            style="left:50%"
                            data-pos="${rangePos}"
                        ></div>
                    </div>
                </div>

                ${hasSparkline ? `
                <div class="lab-sparkline-wrap">
                    <div class="lab-sparkline-label">Last 14 days</div>
                    <svg
                        class="lab-sparkline"
                        viewBox="0 0 220 32"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        ${renderSparklineSVG(sparkline)}
                    </svg>
                </div>` : ''}

                <button
                    class="lab-science-toggle"
                    onclick="labView.toggleScience('${safeKey}')"
                    aria-expanded="false"
                    aria-controls="lab-science-${safeKey}"
                >
                    <span>The Science</span>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </button>
                <div
                    class="lab-science-body"
                    id="lab-science-${safeKey}"
                    role="region"
                    aria-label="Science details for ${displayName}"
                >
                    <div>${sciSummary}</div>
                    ${sciCitation ? `<div class="lab-science-citation">${sciCitation}</div>` : ''}
                </div>
            </div>
        `;
    }

    // ── Sparkline SVG ────────────────────────────────────────────────────────

    function renderSparklineSVG(values) {
        const nonNull = values.filter(v => v !== null && v !== undefined && !isNaN(v));

        if (nonNull.length < 2) {
            // Flat placeholder line
            return '<line x1="0" y1="16" x2="220" y2="16" stroke="#e4e8ec" stroke-width="1"/>';
        }

        const minVal = Math.min(...nonNull);
        const maxVal = Math.max(...nonNull);
        const range  = maxVal - minVal || 1;

        // Map each value to (x, y) — skip null values by building segments
        const points = values.map((v, i) => ({
            x: (i / (values.length - 1)) * 220,
            y: (v !== null && v !== undefined && !isNaN(v))
                ? 28 - ((v - minVal) / range) * 24
                : null,
        }));

        // Build path segments (split at nulls)
        let pathD = '';
        let segmentStart = true;

        points.forEach(pt => {
            if (pt.y === null) {
                segmentStart = true;
                return;
            }
            const cmd = segmentStart ? 'M' : 'L';
            pathD += `${cmd} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)} `;
            segmentStart = false;
        });

        if (!pathD.trim()) return '';

        // Last non-null point for the dot
        const lastPt = [...points].reverse().find(p => p.y !== null);

        return `
            <path
                d="${pathD.trim()}"
                fill="none"
                stroke="#5B8DB8"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
            />
            ${lastPt ? `<circle cx="${lastPt.x.toFixed(1)}" cy="${lastPt.y.toFixed(1)}" r="2.5" fill="#5B8DB8"/>` : ''}
        `;
    }

    // ── Radar chart (Canvas) ─────────────────────────────────────────────────

    function drawRadar(dimensions) {
        const canvas = document.getElementById('lab-radar-canvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const cx  = 90;
        const cy  = 90;
        const r   = 68;
        const n   = dimensions.length;

        ctx.clearRect(0, 0, 180, 180);

        if (n < 3) {
            // Not enough dimensions — draw a placeholder ring
            ctx.beginPath();
            ctx.arc(cx, cy, r * 0.5, 0, Math.PI * 2);
            ctx.strokeStyle = '#e4e8ec';
            ctx.lineWidth = 1.5;
            ctx.stroke();

            ctx.font = '10px Inter, sans-serif';
            ctx.fillStyle = '#c8cfd8';
            ctx.textAlign = 'center';
            ctx.fillText('More data needed', cx, cy + 4);
            return;
        }

        const angleFor = i => (i / n) * Math.PI * 2 - Math.PI / 2;
        const ptAt = (i, scale) => ({
            x: cx + Math.cos(angleFor(i)) * r * scale,
            y: cy + Math.sin(angleFor(i)) * r * scale,
        });

        // Grid rings
        [0.25, 0.5, 0.75, 1].forEach(scale => {
            ctx.beginPath();
            for (let i = 0; i < n; i++) {
                const p = ptAt(i, scale);
                i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
            }
            ctx.closePath();
            ctx.strokeStyle = scale === 1 ? '#d4dbe3' : '#e4e8ec';
            ctx.lineWidth = scale === 1 ? 1 : 0.75;
            ctx.stroke();
        });

        // Spokes
        for (let i = 0; i < n; i++) {
            const outer = ptAt(i, 1);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(outer.x, outer.y);
            ctx.strokeStyle = '#e4e8ec';
            ctx.lineWidth = 0.75;
            ctx.stroke();
        }

        // Data polygon fill
        ctx.beginPath();
        dimensions.forEach((d, i) => {
            const scale = Math.min(1, Math.max(0, (d.value || 0) / 100));
            const p = ptAt(i, scale);
            i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
        });
        ctx.closePath();
        ctx.fillStyle   = 'rgba(91,141,184,0.14)';
        ctx.fill();
        ctx.strokeStyle = '#5B8DB8';
        ctx.lineWidth   = 1.5;
        ctx.stroke();

        // Data points
        dimensions.forEach((d, i) => {
            const scale = Math.min(1, Math.max(0, (d.value || 0) / 100));
            const p = ptAt(i, scale);
            ctx.beginPath();
            ctx.arc(p.x, p.y, 2.5, 0, Math.PI * 2);
            ctx.fillStyle = '#5B8DB8';
            ctx.fill();
        });

        // Labels
        ctx.font      = '9px Inter, sans-serif';
        ctx.fillStyle = '#8C96A0';
        ctx.textAlign = 'center';
        dimensions.forEach((d, i) => {
            const angle = angleFor(i);
            const lx = cx + Math.cos(angle) * (r + 15);
            const ly = cy + Math.sin(angle) * (r + 15) + 3;
            ctx.fillText(d.dim || '', lx, ly);
        });
    }

    // ── Public API ───────────────────────────────────────────────────────────

    /**
     * Switch the active category tab and re-render the cards grid.
     * Called from inline onclick in tab buttons.
     */
    function switchCategory(cat) {
        if (!_data) return;
        _currentCat = cat;

        // Update tab active states
        document.querySelectorAll('.lab-tab').forEach(btn => {
            const isCat = btn.textContent.trim().toLowerCase().replace(/\s+/g, '_') === cat ||
                          btn.getAttribute('onclick') === `labView.switchCategory('${cat}')`;
            btn.classList.toggle('active', isCat);
            btn.setAttribute('aria-selected', isCat ? 'true' : 'false');
        });

        // Re-render cards grid
        const grid = document.getElementById('lab-cards-grid');
        if (grid) {
            grid.innerHTML = renderCards(_data.bioData, cat);

            // Animate bars on next frame
            requestAnimationFrame(() => {
                grid.querySelectorAll('.lab-range-marker').forEach(m => {
                    const pos = m.dataset.pos;
                    if (pos !== undefined) m.style.left = (parseFloat(pos) * 100).toFixed(1) + '%';
                });
                grid.querySelectorAll('.lab-range-bar-fill').forEach(f => {
                    const pos = f.dataset.pos;
                    if (pos !== undefined) f.style.width = (parseFloat(pos) * 100).toFixed(1) + '%';
                });
            });
        }
    }

    /**
     * Toggle the "The Science" expandable section for a card.
     * Called from inline onclick in card buttons.
     */
    function toggleScience(key) {
        const body   = document.getElementById(`lab-science-${key}`);
        const toggle = body ? body.previousElementSibling : null;
        if (!body) return;

        const isOpen = body.classList.contains('open');
        body.classList.toggle('open', !isOpen);
        if (toggle) {
            toggle.classList.toggle('open', !isOpen);
            toggle.setAttribute('aria-expanded', !isOpen ? 'true' : 'false');
        }
    }

    /**
     * Force a fresh fetch on next load() call.
     * Call this after a new voice session completes.
     */
    function invalidate() {
        _loaded = false;
        _data   = null;
    }

    // Expose public surface
    return { load, switchCategory, toggleScience, invalidate };

})();

// Make globally accessible for app.js navigation and inline event handlers
window.labView = labView;
