/**
 * Stress Area Chart
 * Area chart with Y-axis (0-100), time X-axis, gradient fill, line stroke,
 * colored data dots, and a vertical dashed NOW marker.
 */

class StressDotTimeline {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.readings = [];
        this.height = 180;
        this.margin = { top: 16, right: 20, bottom: 32, left: 40 };
        this.workStart = 6;
        this.workEnd = 22;

        // Color stops for continuous interpolation
        this.colorStops = [
            { at: 0,   r: 90,  g: 154, b: 110 }, // #5a9a6e green
            { at: 33,  r: 138, g: 168, b: 140 }, // cool muted sage
            { at: 66,  r: 196, g: 120, b: 70  }, // slightly cooler amber-orange
            { at: 100, r: 196, g: 88,  b: 76  }  // #c4584c coral
        ];
    }

    /** Map stress_score (0-100) to RGB color via continuous interpolation */
    stressToColor(score) {
        const s = Math.max(0, Math.min(100, score));
        let lower = this.colorStops[0];
        let upper = this.colorStops[this.colorStops.length - 1];

        for (let i = 0; i < this.colorStops.length - 1; i++) {
            if (s >= this.colorStops[i].at && s <= this.colorStops[i + 1].at) {
                lower = this.colorStops[i];
                upper = this.colorStops[i + 1];
                break;
            }
        }

        const range = upper.at - lower.at;
        const t = range === 0 ? 0 : (s - lower.at) / range;
        const r = Math.round(lower.r + (upper.r - lower.r) * t);
        const g = Math.round(lower.g + (upper.g - lower.g) * t);
        const b = Math.round(lower.b + (upper.b - lower.b) * t);
        return `rgb(${r},${g},${b})`;
    }

    /** Get a stress label for tooltip */
    stressLabel(score) {
        if (score <= 25) return 'Low';
        if (score <= 50) return 'Mild';
        if (score <= 75) return 'Moderate';
        return 'High';
    }

    render(readings) {
        this.readings = (readings || []).filter(r =>
            r.stress_score !== null && r.stress_score !== undefined
        );

        if (!this.readings || this.readings.length === 0) {
            this.renderEmpty();
            return;
        }

        this.readings.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        this.container.textContent = '';

        // Theme-aware colors
        const isDay = document.documentElement.dataset.theme === 'day';
        const lineColor = isDay ? 'rgba(64,72,84,0.6)' : 'rgba(168,192,208,0.6)';
        const fillColor = isDay ? '#6a7a8c' : '#8ab4cc';
        const gridColor = isDay ? 'rgba(0,0,0,0.08)' : 'rgba(168,192,208,0.08)';
        const labelColor = isDay ? 'rgba(60,68,80,0.45)' : 'rgba(168,192,208,0.38)';
        const nowColor   = isDay ? 'rgba(60,68,80,0.3)' : 'rgba(168,192,208,0.3)';

        const width = this.container.clientWidth || 600;
        const plotWidth = width - this.margin.left - this.margin.right;
        const plotHeight = this.height - this.margin.top - this.margin.bottom;

        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '100%');
        svg.setAttribute('height', this.height);
        svg.setAttribute('viewBox', `0 0 ${width} ${this.height}`);

        // --- Defs: gradient fill + glow filter ---
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

        // Vertical gradient for area fill: green at bottom, coral at top
        const grad = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');
        grad.setAttribute('id', 'area-gradient');
        grad.setAttribute('x1', '0'); grad.setAttribute('y1', '1');
        grad.setAttribute('x2', '0'); grad.setAttribute('y2', '0');
        const stop1 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop1.setAttribute('offset', '0%');
        stop1.setAttribute('stop-color', fillColor);
        stop1.setAttribute('stop-opacity', '0.28');
        grad.appendChild(stop1);
        const stop2 = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop2.setAttribute('offset', '100%');
        stop2.setAttribute('stop-color', fillColor);
        stop2.setAttribute('stop-opacity', '0');
        grad.appendChild(stop2);
        defs.appendChild(grad);

        // Dot glow filter
        const filter = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
        filter.setAttribute('id', 'dot-glow');
        filter.setAttribute('x', '-50%'); filter.setAttribute('y', '-50%');
        filter.setAttribute('width', '200%'); filter.setAttribute('height', '200%');
        const blur = document.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur');
        blur.setAttribute('stdDeviation', '3');
        blur.setAttribute('result', 'glow');
        filter.appendChild(blur);
        const merge = document.createElementNS('http://www.w3.org/2000/svg', 'feMerge');
        const mn1 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
        mn1.setAttribute('in', 'glow'); merge.appendChild(mn1);
        const mn2 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
        mn2.setAttribute('in', 'SourceGraphic'); merge.appendChild(mn2);
        filter.appendChild(merge);
        defs.appendChild(filter);

        // Bio-glow filter for main line
        const bioGlow = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
        bioGlow.setAttribute('id', 'bio-glow');
        bioGlow.setAttribute('x', '-20%'); bioGlow.setAttribute('y', '-20%');
        bioGlow.setAttribute('width', '140%'); bioGlow.setAttribute('height', '140%');
        const bioBlur = document.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur');
        bioBlur.setAttribute('in', 'SourceGraphic');
        bioBlur.setAttribute('stdDeviation', '2.5');
        bioBlur.setAttribute('result', 'blur');
        bioGlow.appendChild(bioBlur);
        const bioMerge = document.createElementNS('http://www.w3.org/2000/svg', 'feMerge');
        const bioMN1 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
        bioMN1.setAttribute('in', 'blur'); bioMerge.appendChild(bioMN1);
        const bioMN2 = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
        bioMN2.setAttribute('in', 'SourceGraphic'); bioMerge.appendChild(bioMN2);
        bioGlow.appendChild(bioMerge);
        defs.appendChild(bioGlow);

        svg.appendChild(defs);

        // --- Scale helpers ---
        const xScale = (hour) => this.margin.left + ((hour - this.workStart) / (this.workEnd - this.workStart)) * plotWidth;
        const yScale = (value) => this.margin.top + plotHeight - (Math.max(0, Math.min(100, value)) / 100) * plotHeight;
        const yBottom = this.margin.top + plotHeight;

        // --- Y-axis gridlines and labels ---
        const yTicks = [0, 25, 50, 75, 100];
        for (const tick of yTicks) {
            const y = yScale(tick);

            // Gridline
            const gridline = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            gridline.setAttribute('x1', this.margin.left);
            gridline.setAttribute('y1', y);
            gridline.setAttribute('x2', width - this.margin.right);
            gridline.setAttribute('y2', y);
            gridline.setAttribute('class', 'gridline');
            svg.appendChild(gridline);

            // Label
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.setAttribute('x', this.margin.left - 8);
            label.setAttribute('y', y + 3);
            label.setAttribute('text-anchor', 'end');
            label.setAttribute('class', 'axis-label');
            label.textContent = tick;
            svg.appendChild(label);
        }

        // --- X-axis time labels ---
        for (let hour = this.workStart; hour <= this.workEnd; hour++) {
            const x = xScale(hour);

            // Small tick
            const tick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            tick.setAttribute('x1', x);
            tick.setAttribute('y1', yBottom);
            tick.setAttribute('x2', x);
            tick.setAttribute('y2', yBottom + 4);
            tick.setAttribute('stroke', gridColor);
            tick.setAttribute('stroke-width', '1');
            svg.appendChild(tick);

            // Label every 2 hours
            if (hour % 2 === 0) {
                const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                label.setAttribute('x', x);
                label.setAttribute('y', yBottom + 18);
                label.setAttribute('text-anchor', 'middle');
                label.setAttribute('class', 'axis-label');
                label.textContent = hour === 12 ? '12 PM' : hour > 12 ? `${hour - 12} PM` : `${hour} AM`;
                svg.appendChild(label);
            }
        }

        // --- Build data points within work hours ---
        const points = [];
        for (const reading of this.readings) {
            const ts = new Date(reading.timestamp);
            const hour = ts.getHours() + ts.getMinutes() / 60;
            if (hour < this.workStart || hour > this.workEnd) continue;
            points.push({
                x: xScale(hour),
                y: yScale(reading.stress_score),
                score: reading.stress_score,
                reading: reading
            });
        }

        if (points.length === 0) {
            this.container.appendChild(svg);
            return;
        }

        // --- Area fill + line (only if 2+ points) ---
        if (points.length >= 2) {
            // Build area path: line along data, then down to bottom, back to start
            let areaD = `M ${points[0].x} ${points[0].y}`;
            for (let i = 1; i < points.length; i++) {
                areaD += ` L ${points[i].x} ${points[i].y}`;
            }
            areaD += ` L ${points[points.length - 1].x} ${yBottom}`;
            areaD += ` L ${points[0].x} ${yBottom} Z`;

            const areaPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            areaPath.setAttribute('d', areaD);
            areaPath.setAttribute('fill', 'url(#area-gradient)');
            svg.appendChild(areaPath);

            // Line path data
            let lineD = `M ${points[0].x} ${points[0].y}`;
            for (let i = 1; i < points.length; i++) {
                lineD += ` L ${points[i].x} ${points[i].y}`;
            }

            // Ghost echo line 2 (farthest, most transparent)
            const ghostLine2 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            ghostLine2.setAttribute('d', lineD);
            ghostLine2.setAttribute('fill', 'none');
            ghostLine2.setAttribute('stroke', gridColor);
            ghostLine2.setAttribute('stroke-width', '1.5');
            ghostLine2.setAttribute('stroke-linecap', 'round');
            ghostLine2.setAttribute('stroke-linejoin', 'round');
            ghostLine2.setAttribute('transform', 'translate(0,-8)');
            svg.appendChild(ghostLine2);

            // Ghost echo line 1
            const ghostLine1 = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            ghostLine1.setAttribute('d', lineD);
            ghostLine1.setAttribute('fill', 'none');
            ghostLine1.setAttribute('stroke', isDay ? 'rgba(64,72,84,0.2)' : 'rgba(168,192,208,0.2)');
            ghostLine1.setAttribute('stroke-width', '1.5');
            ghostLine1.setAttribute('stroke-linecap', 'round');
            ghostLine1.setAttribute('stroke-linejoin', 'round');
            ghostLine1.setAttribute('transform', 'translate(0,-4)');
            svg.appendChild(ghostLine1);

            // Main line stroke with bioluminescent glow
            const linePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            linePath.setAttribute('d', lineD);
            linePath.setAttribute('fill', 'none');
            linePath.setAttribute('stroke', lineColor);
            linePath.setAttribute('stroke-width', '1.5');
            linePath.setAttribute('stroke-linecap', 'round');
            linePath.setAttribute('stroke-linejoin', 'round');
            linePath.setAttribute('filter', 'url(#bio-glow)');
            svg.appendChild(linePath);
        }

        // --- Data dots ---
        for (const pt of points) {
            const color = this.stressToColor(pt.score);

            // Glow halo
            const halo = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            halo.setAttribute('cx', pt.x);
            halo.setAttribute('cy', pt.y);
            halo.setAttribute('r', '5');
            halo.setAttribute('fill', color);
            halo.setAttribute('filter', 'url(#dot-glow)');
            halo.setAttribute('opacity', '0.6');
            svg.appendChild(halo);

            // Solid dot
            const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            dot.setAttribute('cx', pt.x);
            dot.setAttribute('cy', pt.y);
            dot.setAttribute('r', '4');
            dot.setAttribute('fill', color);
            dot.setAttribute('stroke', 'rgba(255,255,255,0.35)');
            dot.setAttribute('stroke-width', '1');
            svg.appendChild(dot);

            // Invisible hover target
            const hitArea = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            hitArea.setAttribute('cx', pt.x);
            hitArea.setAttribute('cy', pt.y);
            hitArea.setAttribute('r', '12');
            hitArea.setAttribute('fill', 'transparent');
            hitArea.setAttribute('cursor', 'pointer');

            hitArea.addEventListener('click', (e) => {
                e.stopPropagation();
                this.showClickPopup(pt, svg);
            });
            svg.appendChild(hitArea);
        }

        // --- NOW marker (vertical dashed line) ---
        const now = new Date();
        const nowHour = now.getHours() + now.getMinutes() / 60;
        if (nowHour >= this.workStart && nowHour <= this.workEnd) {
            const nowX = xScale(nowHour);

            // Dashed vertical line
            const nowLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            nowLine.setAttribute('x1', nowX);
            nowLine.setAttribute('y1', this.margin.top);
            nowLine.setAttribute('x2', nowX);
            nowLine.setAttribute('y2', yBottom);
            nowLine.setAttribute('stroke', nowColor);
            nowLine.setAttribute('stroke-width', '1.5');
            nowLine.setAttribute('stroke-dasharray', '4 3');
            svg.appendChild(nowLine);

            // "NOW" label above the line
            const nowLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            nowLabel.setAttribute('x', nowX);
            nowLabel.setAttribute('y', this.margin.top - 4);
            nowLabel.setAttribute('text-anchor', 'middle');
            nowLabel.setAttribute('font-size', '9');
            nowLabel.setAttribute('font-weight', '700');
            nowLabel.setAttribute('font-family', 'Inter, sans-serif');
            nowLabel.setAttribute('fill', isDay ? 'rgba(60,68,80,0.5)' : 'rgba(168,192,208,0.6)');
            nowLabel.setAttribute('letter-spacing', '1');
            nowLabel.textContent = 'NOW';
            svg.appendChild(nowLabel);
        }

        this.container.appendChild(svg);
    }

    renderEmpty() {
        this.container.innerHTML = '<div class="stress-empty">Listening for stress data...</div>';
    }

    showClickPopup(pt, svg) {
        // Remove any existing popup
        this.dismissPopup();

        const reading = pt.reading;
        const timestamp = new Date(reading.timestamp);
        const timeStr = timestamp.toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
            hour12: true
        });

        const score = Math.round(reading.stress_score);
        const color = this.stressToColor(score);

        // Create popup div anchored near the dot
        const popup = document.createElement('div');
        popup.className = 'stress-dot-popup';
        popup.innerHTML = `<span style="font-weight:600">${timeStr}</span> &mdash; Score: <span style="color:${color};font-weight:700">${score}</span>`;

        // Position relative to the SVG container
        const svgRect = svg.getBoundingClientRect();
        const containerRect = this.container.getBoundingClientRect();
        const dotX = pt.x;
        const dotY = pt.y;

        // Convert SVG coordinates to container-relative pixels
        const svgWidth = svg.viewBox.baseVal.width || svgRect.width;
        const svgHeight = svg.viewBox.baseVal.height || svgRect.height;
        const scaleX = svgRect.width / svgWidth;
        const scaleY = svgRect.height / svgHeight;

        let popupLeft = dotX * scaleX + (svgRect.left - containerRect.left);
        let popupTop = dotY * scaleY + (svgRect.top - containerRect.top) - 36;

        popup.style.left = popupLeft + 'px';
        popup.style.top = popupTop + 'px';

        this.container.appendChild(popup);
        this._activePopup = popup;

        // Adjust if popup overflows right edge
        const popupRect = popup.getBoundingClientRect();
        if (popupRect.right > containerRect.right - 4) {
            popupLeft -= (popupRect.right - containerRect.right + 8);
            popup.style.left = popupLeft + 'px';
        }
        if (popupRect.left < containerRect.left + 4) {
            popup.style.left = '4px';
        }

        // Dismiss on click outside
        const dismissHandler = (e) => {
            if (!popup.contains(e.target)) {
                this.dismissPopup();
                document.removeEventListener('click', dismissHandler, true);
            }
        };
        // Delay adding listener so this click doesn't immediately dismiss
        setTimeout(() => {
            document.addEventListener('click', dismissHandler, true);
        }, 0);
        this._dismissHandler = dismissHandler;
    }

    dismissPopup() {
        if (this._activePopup) {
            this._activePopup.remove();
            this._activePopup = null;
        }
        if (this._dismissHandler) {
            document.removeEventListener('click', this._dismissHandler, true);
            this._dismissHandler = null;
        }
    }
}

// Backward-compat globals (app.js calls these)
let stressDotTimeline;

function initAnxietyTimeline() {
    stressDotTimeline = new StressDotTimeline('stress-dot-timeline');
}

function updateAnxietyTimeline(readings) {
    if (stressDotTimeline) {
        stressDotTimeline.render(readings);
    }
}
