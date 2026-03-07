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

        this.renderStreak();
    }

    renderStreak() {
        const streakEl = document.getElementById('streak-counter');
        if (streakEl && this.data.streak !== undefined) {
            streakEl.textContent = `${this.data.streak} day${this.data.streak !== 1 ? 's' : ''}`;
            streakEl.style.display = 'inline-block';
        }
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
