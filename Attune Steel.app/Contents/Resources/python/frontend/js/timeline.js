/**
 * Timeline visualization
 * Oura-inspired color-coded timeline showing zones throughout the day
 */

class Timeline {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.readings = [];
        this.width = 0;
        this.height = 140;
        this.margin = { top: 20, right: 20, bottom: 45, left: 40 };
    }

    render(readings) {
        this.readings = readings;

        if (!readings || readings.length === 0) {
            this.renderEmpty();
            return;
        }

        // Sort readings by timestamp
        this.readings.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

        // Get container width
        this.width = this.container.clientWidth;

        // Clear container
        this.container.textContent = '';

        // Create SVG
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'timeline-svg');
        svg.setAttribute('width', '100%');
        svg.setAttribute('height', this.height);
        svg.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);

        // Define time range (work hours: 6am to 10pm)
        const workStart = 6; // 6am
        const workEnd = 22;  // 10pm
        const totalHours = workEnd - workStart;

        // Calculate x-scale
        const plotWidth = this.width - this.margin.left - this.margin.right;
        const xScale = (hour) => this.margin.left + ((hour - workStart) / totalHours) * plotWidth;

        // Draw time axis
        const axis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        axis.setAttribute('class', 'timeline-axis');
        axis.setAttribute('x1', this.margin.left);
        axis.setAttribute('y1', this.height - this.margin.bottom);
        axis.setAttribute('x2', this.width - this.margin.right);
        axis.setAttribute('y2', this.height - this.margin.bottom);
        svg.appendChild(axis);

        // Draw time labels (every 2 hours) and tick marks (every hour)
        for (let hour = workStart; hour <= workEnd; hour++) {
            const x = xScale(hour);

            // Tick mark every hour
            const tick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            tick.setAttribute('x1', x);
            tick.setAttribute('y1', this.height - this.margin.bottom);
            tick.setAttribute('x2', x);
            tick.setAttribute('y2', this.height - this.margin.bottom + 3);
            tick.setAttribute('stroke', '#5a6270');
            tick.setAttribute('stroke-width', '1');
            svg.appendChild(tick);

            // Label every 2 hours
            if (hour % 2 === 0) {
                const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                label.setAttribute('class', 'time-label');
                label.setAttribute('x', x);
                label.setAttribute('y', this.height - this.margin.bottom + 18);
                label.setAttribute('text-anchor', 'middle');
                label.textContent = hour === 12 ? '12pm' : hour > 12 ? `${hour - 12}pm` : `${hour}am`;
                svg.appendChild(label);
            }
        }

        // Draw zone segments
        const segmentHeight = 40;
        const segmentY = this.margin.top + 10;

        this.readings.forEach((reading, idx) => {
            const timestamp = new Date(reading.timestamp);
            const hour = timestamp.getHours() + timestamp.getMinutes() / 60;

            // Calculate segment width (5 minutes assumed per reading)
            const segmentDuration = 5 / 60; // 5 minutes in hours
            const x = xScale(hour);
            const segmentWidth = (segmentDuration / totalHours) * plotWidth;

            // Create zone rectangle
            const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            rect.setAttribute('class', `zone-segment ${reading.zone || 'steady'}`);
            rect.setAttribute('x', x);
            rect.setAttribute('y', segmentY);
            rect.setAttribute('width', segmentWidth);
            rect.setAttribute('height', segmentHeight);
            rect.setAttribute('data-reading-id', reading.id);

            // Add hover event
            rect.addEventListener('mouseenter', (e) => this.showTooltip(e, reading));
            rect.addEventListener('mouseleave', () => this.hideTooltip());

            svg.appendChild(rect);
        });

        // Draw "now" marker
        const now = new Date();
        const nowHour = now.getHours() + now.getMinutes() / 60;
        if (nowHour >= workStart && nowHour <= workEnd) {
            const nowX = xScale(nowHour);

            const nowLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            nowLine.setAttribute('class', 'now-marker');
            nowLine.setAttribute('x1', nowX);
            nowLine.setAttribute('y1', segmentY);
            nowLine.setAttribute('x2', nowX);
            nowLine.setAttribute('y2', segmentY + segmentHeight);
            svg.appendChild(nowLine);

            const nowLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            nowLabel.setAttribute('class', 'now-label');
            nowLabel.setAttribute('x', nowX);
            nowLabel.setAttribute('y', segmentY - 5);
            nowLabel.setAttribute('text-anchor', 'middle');
            nowLabel.textContent = 'now';
            svg.appendChild(nowLabel);
        }

        // Zone color legend (bottom-right corner)
        const legendZones = [
            { label: 'Calm', color: '#5a9a6e' },
            { label: 'Steady', color: '#b5a84a' },
            { label: 'Tense', color: '#d4943a' },
            { label: 'Stressed', color: '#c4584c' }
        ];
        const legendX = this.width - this.margin.right - 200;
        const legendY = this.height - 12;
        legendZones.forEach((z, i) => {
            const offsetX = legendX + i * 52;
            const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            rect.setAttribute('x', offsetX);
            rect.setAttribute('y', legendY - 7);
            rect.setAttribute('width', 8);
            rect.setAttribute('height', 8);
            rect.setAttribute('fill', z.color);
            svg.appendChild(rect);

            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', offsetX + 11);
            text.setAttribute('y', legendY);
            text.setAttribute('font-size', '9');
            text.setAttribute('font-family', 'Inter, sans-serif');
            text.setAttribute('fill', '#5a6270');
            text.textContent = z.label;
            svg.appendChild(text);
        });

        this.container.appendChild(svg);
    }

    renderEmpty() {
        this.container.innerHTML = '<div class="timeline-empty">No voice data yet today. Speak to see your timeline.</div>';
    }

    showTooltip(event, reading) {
        const tooltip = document.getElementById('tooltip');
        if (!tooltip) return;

        const timestamp = new Date(reading.timestamp);
        const timeStr = timestamp.toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
            hour12: true
        });

        const content = `
            <strong>${timeStr}</strong><br>
            Zone: ${(reading.zone || 'steady').toUpperCase()}<br>
            Wellbeing: ${Math.round(reading.wellbeing_score || 50)}<br>
            Stress: ${Math.round(reading.stress_score || 50)}<br>
            Anxiety: ${reading.anxiety_quantized !== null ? ['None', 'Mild', 'Moderate', 'Severe'][reading.anxiety_quantized] : 'Unknown'}
        `;

        tooltip.innerHTML = content;
        tooltip.style.display = 'block';
        tooltip.style.left = (event.pageX + 10) + 'px';
        tooltip.style.top = (event.pageY + 10) + 'px';
    }

    hideTooltip() {
        const tooltip = document.getElementById('tooltip');
        if (tooltip) {
            tooltip.style.display = 'none';
        }
    }
}

// Global timeline instance
let timeline;

function initTimeline() {
    timeline = new Timeline('timeline-container');
}

function updateTimeline(readings) {
    if (timeline) {
        timeline.render(readings);
    }
}
