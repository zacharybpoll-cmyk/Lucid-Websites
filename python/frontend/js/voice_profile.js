/**
 * Voice Profile — trait pills + insight cards
 */
class VoiceProfileView {
    constructor() {
        this.container = document.getElementById('profile-view');
        this.data = null;
    }

    async load() {
        if (!this.container) return;
        this.container.innerHTML = '<div style="padding:40px;color:#5a6270;">Loading voice profile...</div>';

        try {
            this.data = await API.getVoiceProfile();
            this.render();
        } catch (e) {
            console.error('Failed to load voice profile:', e);
            this.renderEmpty();
        }
    }

    render() {
        if (!this.data) {
            this.renderEmpty();
            return;
        }

        const dq = this.data.data_quality || {};
        if (!dq.sufficient) {
            this.container.innerHTML = `
                <div class="vp-header">
                    <div class="vp-title">Your Voice</div>
                    <div class="vp-subtitle">Voice personality traits and patterns</div>
                </div>
                <div class="vp-needs-data">
                    <h3>Building your voice profile</h3>
                    <p>We need at least 7 days of data to identify your voice traits.<br>
                    You have ${dq.days_tracked || 0} day${(dq.days_tracked || 0) !== 1 ? 's' : ''} so far — keep going!</p>
                </div>
            `;
            return;
        }

        const traits = this.data.traits || [];
        const insights = this.data.insights || [];

        const traitPills = traits.length > 0
            ? traits.map(t => `<span class="vp-trait-pill">${this._sanitize(t)}</span>`).join('')
            : '<span style="color:#8C96A0;font-size:13px;">Not enough variation detected yet</span>';

        const insightCards = insights.length > 0
            ? insights.map(ins => `
                <div class="vp-insight-card">
                    <div class="vp-insight-icon">${this._icon(ins.icon || ins.type)}</div>
                    <div class="vp-insight-text">${this._sanitize(ins.text)}</div>
                </div>
            `).join('')
            : '<div style="color:#8C96A0;font-size:13px;grid-column:1/-1;">Insights will appear as more patterns emerge.</div>';

        this.container.innerHTML = `
            <div class="vp-header">
                <div class="vp-title">Your Voice</div>
                <div class="vp-subtitle">Voice personality traits and patterns</div>
            </div>
            <div class="vp-traits">${traitPills}</div>
            <div class="vp-insights">${insightCards}</div>
            <div class="vp-data-quality">
                <div class="vp-dq-item"><strong>${dq.reading_count || 0}</strong> readings</div>
                <div class="vp-dq-item"><strong>${dq.days_tracked || 0}</strong> days tracked</div>
            </div>
        `;
    }

    renderEmpty() {
        if (!this.container) return;
        this.container.innerHTML = `
            <div class="vp-header">
                <div class="vp-title">Your Voice</div>
                <div class="vp-subtitle">Voice personality traits and patterns</div>
            </div>
            <div class="vp-needs-data">
                <h3>No voice data yet</h3>
                <p>Start using Lucid to build your voice profile.</p>
            </div>
        `;
    }

    _sanitize(str) {
        return typeof sanitizeHTML === 'function' ? sanitizeHTML(str) : str;
    }

    _icon(type) {
        const icons = {
            'clock-calendar': '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
            'clarity_pattern': '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
            'chart-up': '<svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
            'energy_peak': '<svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
            'calendar-stack': '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
            'cognitive_load': '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
            'waveform': '<svg viewBox="0 0 24 24"><path d="M2 12h2l3-9 4 18 3-9h2"/></svg>',
            'pitch_range': '<svg viewBox="0 0 24 24"><path d="M2 12h2l3-9 4 18 3-9h2"/></svg>',
        };
        return icons[type] || icons['waveform'];
    }
}

let voiceProfileView;
function initVoiceProfileView() {
    voiceProfileView = new VoiceProfileView();
}
