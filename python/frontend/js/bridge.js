/**
 * API bridge
 * Provides API wrapper functions using relative URLs
 */

const API_BASE = window.location.origin + '/api';

// Cached application config (fetched once from /api/config)
let _appConfig = null;
async function getAppConfig() {
    if (_appConfig) return _appConfig;
    try {
        const resp = await fetch(`${API_BASE}/config`);
        _appConfig = await resp.json();
    } catch (e) {
        // Fallback defaults if config endpoint is unreachable
        _appConfig = {
            api_port: parseInt(window.location.port) || 8765,
            speech_threshold_sec: 60,
            analysis_interval_sec: 5,
            zone_thresholds: { stressed: 70, tense: 40 },
            zone_colors: { calm: '#5B8DB8', steady: '#5a6270', tense: '#DD8452', stressed: '#C44E52' },
            brand_colors: { primary: '#f8f9fa', secondary: '#5a6270' },
        };
    }
    return _appConfig;
}

// API helper function
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            const err = new Error(`API error: ${response.statusText}`);
            err.status = response.status;
            throw err;
        }
        try {
            return await response.json();
        } catch (parseError) {
            throw new Error(`Invalid JSON response from ${endpoint}: ${parseError.message}`);
        }
    } catch (error) {
        console.error(`API call failed for ${endpoint}:`, error);
        throw error;
    }
}

// API functions
const API = {
    async getConfig() { return await getAppConfig(); },
    async getHealth() { return await apiCall('/health'); },
    async getStatus() { return await apiCall('/status'); },
    async getToday() { return await apiCall('/today'); },
    async getInsight() { return await apiCall('/insight'); },
    async getReadings(limit = 100) { return await apiCall(`/readings?limit=${limit}`); },
    async getSummaries(days = 14) { return await apiCall(`/summaries?days=${days}`); },
    async getTrends(days = 14) { return await apiCall(`/trends?days=${days}`); },

    async getBriefing(type = 'morning', force = false) {
        const params = `type=${type}${force ? '&force=true' : ''}`;
        return await apiCall(`/briefing?${params}`);
    },

    async addTag(timestamp, label, notes = '') {
        return await apiCall('/tag', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ timestamp, label, notes })
        });
    },

    async toggleMeeting(active) {
        return await apiCall('/meeting/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ active })
        });
    },

    async pause() { return await apiCall('/pause', { method: 'POST' }); },
    async resume() { return await apiCall('/resume', { method: 'POST' }); },
    async getEngagement() { return await apiCall('/engagement'); },
    async getHistory(days = 30) { return await apiCall(`/history?days=${days}`); },

    // New Feature APIs
    async getWellness() { return await apiCall('/wellness'); },
    async getGrove() { return await apiCall('/grove'); },
    async reviveTree(dateStr) {
        return await apiCall('/grove/revive', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date: dateStr })
        });
    },
    async getWaypoints() { return await apiCall('/waypoints'); },
    async getRings() { return await apiCall('/rings'); },
    async getEchoes() { return await apiCall('/echoes'); },
    async getEchoCount() { return await apiCall('/echoes/count'); },
    async markEchoesSeen() { return await apiCall('/echoes/mark-seen', { method: 'POST' }); },
    async recordAppOpen() { return await apiCall('/app/open'); },
    async getEchoProgress() { return await apiCall('/echoes/progress'); },
    async getCompass() { return await apiCall('/compass'); },
    async setIntention(intention) {
        return await apiCall('/compass/intention', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ intention })
        });
    },
    async getLayout() { return await apiCall('/layout'); },
    async setLayout(cards) {
        return await apiCall('/layout', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cards })
        });
    },

    // Streak Insurance
    async getStreakInsuranceStatus() { return await apiCall('/streak-insurance/status'); },
    async getVoiceSeason() { return await apiCall('/voice-season'); },
    async getVoiceProfile() { return await apiCall('/voice-profile'); },

    // Reports
    async getClinicalPreview(days = 90) { return await apiCall(`/reports/clinical-preview?days=${days}`); },
    async generateClinicalPDF(days = 90) {
        const resp = await fetch(`${API_BASE}/reports/pdf?days=${days}`);
        if (!resp.ok) throw new Error('PDF generation failed');
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `lucid_wellness_report_${days}d.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },
    async getExportHistory() { return await apiCall('/reports/export-history'); },
    async useStreakInsurance() { return await apiCall('/streak-insurance', { method: 'POST' }); },

    // The Beacon
    async getBeacon() { return await apiCall('/beacon'); },

    // Weekly Wrapped
    async getWeeklyWrapped() { return await apiCall('/weekly-wrapped'); },

    // First Spark
    async getFirstSpark() { return await apiCall('/first-spark'); },

    // Notification Preferences
    async getNotifPrefs() { return await apiCall('/notifications/prefs'); },
    async setNotifPref(key, value) {
        return await apiCall('/notifications/prefs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key, value })
        });
    },
    async getNotifLog(limit = 50) { return await apiCall(`/notifications/log?limit=${limit}`); },
    async getNotificationTiming() { return await apiCall('/notifications/timing'); },
    async setAdaptiveTiming(enabled) { return await apiCall('/notifications/timing/enabled', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({enabled}) }); },
    async recordNotificationOpen() { return await apiCall('/notifications/open', { method: 'POST' }); },

    // The Bridge — Export & Webhooks
    async exportJson(days = 30) { return await apiCall(`/export/json?days=${days}`); },
    async getWebhooks() { return await apiCall('/webhooks'); },
    async addWebhook(url, trigger_type, condition_field, condition_op, condition_value) {
        return await apiCall('/webhooks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, trigger_type, condition_field, condition_op, condition_value })
        });
    },
    async deleteWebhook(id) {
        return await apiCall(`/webhooks/${id}`, { method: 'DELETE' });
    },
    async getApiToken() { return await apiCall('/v1/token'); },

    // First Light Quest
    async getFirstLightQuest() { return await apiCall('/quest/first-light'); },
    async completeFirstLightTask(task) {
        return await apiCall('/quest/first-light/complete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task })
        });
    },

    // Recovery Pulse
    async getRecoveryPulse() { return await apiCall('/recovery-pulse'); },

    // Morning Summary
    async getMorningSummary() { return await apiCall('/morning-summary'); },

    // Evening Summary
    async getEveningSummary() { return await apiCall('/evening-summary'); },

    // Speaker Verification
    async getSpeakerStatus() { return await apiCall('/speaker/status'); },
    async enrollSpeakerSample(audioBlob, moodLabel) {
        const response = await fetch(`${API_BASE}/speaker/enroll?mood_label=${moodLabel}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: audioBlob,
        });
        if (!response.ok) {
            const err = new Error(`Enroll failed: ${response.statusText}`);
            err.status = response.status;
            throw err;
        }
        return await response.json();
    },
    async completeSpeakerEnrollment() {
        return await apiCall('/speaker/enroll/complete', { method: 'POST' });
    },
    async resetSpeakerEnrollment() {
        return await apiCall('/speaker/enroll/reset', { method: 'POST' });
    },
    async deleteSpeakerProfile() {
        return await apiCall('/speaker/profile', { method: 'DELETE' });
    },

    // Self-Assessment (ground truth for zone calibration)
    async getSelfAssessmentStatus() { return await apiCall('/self-assessment/status'); },
    async submitSelfAssessment(zone, readingId = null) {
        return await apiCall('/self-assessment', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zone, reading_id: readingId })
        });
    },

    // Phase 1/2/3 insight endpoints
    async getMeetingVsNonMeeting() { return await apiCall('/insights/meeting-vs-nonmeeting'); },
    async getTopicStress() { return await apiCall('/insights/topic-stress'); },
    async getVocabularyTrend() { return await apiCall('/insights/vocabulary-trend'); },
    async getTherapistSummary(days = 30) { return await apiCall(`/export/therapist-summary?days=${days}`); },

    // Linguistic analysis setting
    async getLinguisticAnalysisSetting() { return await apiCall('/settings/linguistic-analysis'); },
    async setLinguisticAnalysisSetting(enabled) {
        return await apiCall('/settings/linguistic-analysis', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
    },

    // Clarity Journey
    async getClarityTracks() { return await apiCall('/clarity/tracks'); },
    async startClarityJourney(track, targetScore) {
        return await apiCall('/clarity/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ track, target_score: targetScore })
        });
    },
    async getClarityJourney() { return await apiCall('/clarity/journey'); },
    async getClarityProgressArc() { return await apiCall('/clarity/progress-arc'); },
    async getClarityToday() { return await apiCall('/clarity/today'); },
    async completeClarityAction(actionId) {
        return await apiCall(`/clarity/action/${actionId}/complete`, { method: 'POST' });
    },
    async triggerClarityWeeklyCheckin() {
        return await apiCall('/clarity/weekly-checkin', { method: 'POST' });
    },
    async getClarityWeeklyCheckin(week) { return await apiCall(`/clarity/weekly-checkin/${week}`); },
    async abandonClarityJourney() {
        return await apiCall('/clarity/abandon', { method: 'POST' });
    },
    async getClaritySummary() { return await apiCall('/clarity/summary'); },

    // Analytics — fire-and-forget (never blocks UI)
    track(eventType, payload = {}) {
        fetch(`${API_BASE}/track`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_type: eventType, payload })
        }).catch(() => {}); // silently ignore failures
    },
};
