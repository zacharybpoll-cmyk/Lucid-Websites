/**
 * Engagement view - streaks and milestones
 */

class EngagementView {
    constructor() {
        this.data = null;
    }

    async load() {
        try {
            const data = await API.getEngagement();
            this.data = data;
            this.render();
        } catch (e) {
            console.error('Failed to load engagement data:', e);
        }
    }

    render() {
        if (!this.data) return;

        this.renderStats();
        this.renderMilestones();
        this.renderNextMilestone();
    }

    renderStats() {
        const statsEl = document.getElementById('engagement-stats');
        if (!statsEl) return;

        const readings = this.data.total_readings || 0;
        const days = this.data.total_days || 0;

        if (readings === 0) {
            statsEl.innerHTML = `<p class="engagement-empty-state">Take your first voice scan to track your wellbeing over time.</p>`;
            return;
        }

        const parts = [];
        if (readings > 0) parts.push(`<span class="engagement-stat"><strong>${readings}</strong> total scans</span>`);
        if (days > 0) parts.push(`<span class="engagement-stat"><strong>${days}</strong> active days</span>`);

        statsEl.innerHTML = parts.join('<span class="engagement-stat-sep">·</span>');
    }

    renderMilestones() {
        const container = document.getElementById('milestone-badges');
        if (!container || !this.data.milestones) return;

        const achieved = this.data.milestones.filter(m => m.achieved);
        if (achieved.length === 0) {
            container.innerHTML = '';
            container.style.display = 'none';
            return;
        }

        container.innerHTML = achieved.map(m => `
            <span class="milestone-badge" title="${m.description}">${m.name}</span>
        `).join('');
        container.style.display = 'flex';
    }

    renderNextMilestone() {
        const el = document.getElementById('next-milestone');
        if (!el || !this.data.milestones) return;

        const nextMilestone = this.data.milestones.find(m => !m.achieved);
        if (!nextMilestone) {
            el.style.display = 'none';
            return;
        }

        // Estimate progress based on milestone type
        const readings = this.data.total_readings || 0;
        let progressText = '';
        let progressPct = 0;

        const id = nextMilestone.id;
        if (id === 'calibrated') {
            const calibDays = Math.min(readings, 7);
            progressText = `${calibDays} / 7 days of voice data`;
            progressPct = (calibDays / 7) * 100;
        } else if (id === 'first_reading') {
            progressText = 'Take your first scan';
            progressPct = 0;
        } else {
            progressText = nextMilestone.description;
            progressPct = 0;
        }

        progressPct = Math.min(100, Math.round(progressPct));

        el.innerHTML = `
            <div class="next-milestone-label">Next: <strong>${nextMilestone.name}</strong></div>
            <div class="next-milestone-desc">${nextMilestone.description}</div>
            <div class="next-milestone-track">
                <div class="next-milestone-fill" style="width:${progressPct}%"></div>
            </div>
            <div class="next-milestone-progress">${progressText}</div>
        `;
        el.style.display = 'block';
    }
}

let engagementView;

function initEngagementView() {
    engagementView = new EngagementView();
}

async function updateEngagement() {
    if (engagementView) {
        await engagementView.load();
    }
}
