-- Attune Steel Analytics — Dashboard Queries
-- Run these in Supabase SQL Editor to analyze user behavior.

-- ============ 1. DAU / WAU / MAU ============

-- Daily Active Users (last 30 days)
SELECT date_trunc('day', timestamp)::date AS day,
       COUNT(DISTINCT user_id) AS dau
FROM analytics_events
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY 1 ORDER BY 1;

-- Weekly Active Users (last 12 weeks)
SELECT date_trunc('week', timestamp)::date AS week,
       COUNT(DISTINCT user_id) AS wau
FROM analytics_events
WHERE timestamp > NOW() - INTERVAL '12 weeks'
GROUP BY 1 ORDER BY 1;

-- ============ 2. Retention Cohorts ============

-- Day 1 / 7 / 30 retention by signup week
WITH cohorts AS (
    SELECT user_id,
           date_trunc('week', first_seen_at)::date AS cohort_week
    FROM analytics_users
),
activity AS (
    SELECT DISTINCT user_id,
           date_trunc('day', timestamp)::date AS active_day
    FROM analytics_events
)
SELECT c.cohort_week,
       COUNT(DISTINCT c.user_id) AS cohort_size,
       COUNT(DISTINCT CASE WHEN a.active_day = c.cohort_week + 1 THEN c.user_id END) AS day1,
       COUNT(DISTINCT CASE WHEN a.active_day = c.cohort_week + 7 THEN c.user_id END) AS day7,
       COUNT(DISTINCT CASE WHEN a.active_day = c.cohort_week + 30 THEN c.user_id END) AS day30
FROM cohorts c
LEFT JOIN activity a ON c.user_id = a.user_id
GROUP BY 1 ORDER BY 1;

-- ============ 3. Onboarding Funnel ============

-- Drop-off at each onboarding step
SELECT payload->>'step_name' AS step,
       payload->>'action' AS action,
       COUNT(*) AS count
FROM analytics_events
WHERE event_type = 'onboarding_step'
GROUP BY 1, 2
ORDER BY (payload->>'step')::int, 2;

-- Onboarding completion rate
SELECT
    COUNT(DISTINCT CASE WHEN event_type = 'onboarding_step' AND payload->>'step' = '1' THEN user_id END) AS started,
    COUNT(DISTINCT CASE WHEN event_type = 'onboarding_complete' THEN user_id END) AS completed,
    ROUND(
        COUNT(DISTINCT CASE WHEN event_type = 'onboarding_complete' THEN user_id END)::numeric /
        NULLIF(COUNT(DISTINCT CASE WHEN event_type = 'onboarding_step' AND payload->>'step' = '1' THEN user_id END), 0) * 100, 1
    ) AS completion_pct
FROM analytics_events;

-- ============ 4. Feature Adoption ============

-- Most used features (last 30 days)
SELECT payload->>'feature' AS feature,
       COUNT(*) AS uses,
       COUNT(DISTINCT user_id) AS unique_users
FROM analytics_events
WHERE event_type = 'feature_interact'
  AND timestamp > NOW() - INTERVAL '30 days'
GROUP BY 1 ORDER BY 2 DESC;

-- ============ 5. View Popularity ============

-- Most visited views (last 30 days)
SELECT payload->>'to_view' AS view,
       COUNT(*) AS visits,
       COUNT(DISTINCT user_id) AS unique_users,
       ROUND(AVG((payload->>'time_on_previous_sec')::numeric), 1) AS avg_time_sec
FROM analytics_events
WHERE event_type = 'view_switch'
  AND timestamp > NOW() - INTERVAL '30 days'
GROUP BY 1 ORDER BY 2 DESC;

-- ============ 6. Error Frequency ============

-- Top errors (last 7 days)
SELECT error_type,
       error_message,
       COUNT(*) AS occurrences,
       COUNT(DISTINCT user_id) AS affected_users
FROM analytics_errors
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY 1, 2 ORDER BY 3 DESC
LIMIT 20;

-- ============ 7. User Timeline ============

-- User lifecycle overview
SELECT u.user_id,
       u.first_seen_at::date AS first_seen,
       u.last_seen_at::date AS last_seen,
       u.app_version,
       u.onboarding_completed,
       COALESCE(SUM(d.readings_count), 0) AS total_readings,
       COALESCE(ROUND(SUM(d.total_speech_min)::numeric, 1), 0) AS total_speech_min,
       COUNT(DISTINCT d.date) AS active_days
FROM analytics_users u
LEFT JOIN analytics_daily d ON u.user_id = d.user_id
GROUP BY 1, 2, 3, 4, 5
ORDER BY u.last_seen_at DESC;

-- ============ 8. Button Click Heatmap ============

-- Most clicked buttons (last 30 days)
SELECT payload->>'button_id' AS button,
       payload->>'context_view' AS context,
       COUNT(*) AS clicks,
       COUNT(DISTINCT user_id) AS unique_users
FROM analytics_events
WHERE event_type = 'button_click'
  AND timestamp > NOW() - INTERVAL '30 days'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- ============ 9. Session Duration Distribution ============

SELECT
    CASE
        WHEN (payload->>'session_duration_sec')::int < 60 THEN '<1 min'
        WHEN (payload->>'session_duration_sec')::int < 300 THEN '1-5 min'
        WHEN (payload->>'session_duration_sec')::int < 1800 THEN '5-30 min'
        WHEN (payload->>'session_duration_sec')::int < 3600 THEN '30-60 min'
        ELSE '>1 hour'
    END AS duration_bucket,
    COUNT(*) AS sessions
FROM analytics_events
WHERE event_type = 'app_quit'
GROUP BY 1 ORDER BY MIN((payload->>'session_duration_sec')::int);

-- ============ 10. Daily Engagement Trends ============

SELECT date,
       COUNT(DISTINCT user_id) AS active_users,
       SUM(readings_count) AS total_readings,
       ROUND(AVG(readings_count)::numeric, 1) AS avg_readings_per_user,
       ROUND(SUM(total_speech_min)::numeric, 1) AS total_speech_min
FROM analytics_daily
WHERE date > CURRENT_DATE - 30
GROUP BY 1 ORDER BY 1;
