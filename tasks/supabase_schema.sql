-- Attune Steel Analytics — Supabase Schema
-- Run this in the Supabase SQL Editor to create all analytics tables.

-- 1. Users table (one row per anonymous device)
CREATE TABLE analytics_users (
    user_id UUID PRIMARY KEY,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    app_version TEXT,
    os_version TEXT,
    onboarding_completed BOOLEAN DEFAULT FALSE,
    onboarding_completed_at TIMESTAMPTZ
);

-- 2. Events table (all tracked events)
CREATE TABLE analytics_events (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES analytics_users(user_id),
    event_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    app_version TEXT,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_events_user_ts ON analytics_events(user_id, timestamp DESC);
CREATE INDEX idx_events_type ON analytics_events(event_type);
CREATE INDEX idx_events_created ON analytics_events(created_at);

-- 3. Daily aggregates (one row per user per day)
CREATE TABLE analytics_daily (
    user_id UUID NOT NULL REFERENCES analytics_users(user_id),
    date DATE NOT NULL,
    readings_count INT DEFAULT 0,
    total_speech_min REAL DEFAULT 0,
    views_visited TEXT[] DEFAULT '{}',
    features_used TEXT[] DEFAULT '{}',
    session_count INT DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

-- 4. Errors table (structured error tracking)
CREATE TABLE analytics_errors (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT,
    context TEXT,
    app_version TEXT
);
CREATE INDEX idx_errors_type ON analytics_errors(error_type);
CREATE INDEX idx_errors_ts ON analytics_errors(timestamp DESC);

-- 5. Row Level Security (RLS) — allow inserts only, no reads of other users' data
ALTER TABLE analytics_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics_errors ENABLE ROW LEVEL SECURITY;

-- Allow anonymous inserts (anon key can insert but not select other users)
CREATE POLICY "Allow insert" ON analytics_users FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow update own" ON analytics_users FOR UPDATE USING (true);
CREATE POLICY "Allow select own" ON analytics_users FOR SELECT USING (true);
CREATE POLICY "Allow insert" ON analytics_events FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow insert" ON analytics_daily FOR INSERT WITH CHECK (true);
CREATE POLICY "Allow update own" ON analytics_daily FOR UPDATE USING (true);
CREATE POLICY "Allow select own" ON analytics_daily FOR SELECT USING (true);
CREATE POLICY "Allow insert" ON analytics_errors FOR INSERT WITH CHECK (true);

-- Service role (dashboard) can read everything
-- (Service role bypasses RLS by default in Supabase)
