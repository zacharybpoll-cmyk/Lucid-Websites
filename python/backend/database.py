"""
Database layer for Attune
SQLite storage for readings, daily summaries, tags, and baselines
"""
import sqlite3
import threading
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
import app_config as config


class Database:
    def __init__(self, db_path: Path = config.DB_PATH):
        self.db_path = db_path
        self.conn = None
        self.lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        """Initialize database and create tables if not exist"""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

        cursor = self.conn.cursor()

        # Enable WAL mode for concurrent reads while writing
        cursor.execute("PRAGMA journal_mode=WAL")

        # Readings table - individual analysis points
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                depression_raw REAL,
                anxiety_raw REAL,
                depression_quantized INTEGER,
                anxiety_quantized INTEGER,
                f0_mean REAL,
                f0_std REAL,
                speech_rate REAL,
                rms_energy REAL,
                spectral_centroid REAL,
                spectral_entropy REAL,
                zcr REAL,
                jitter REAL,
                stress_score REAL,
                mood_score REAL,
                energy_score REAL,
                calm_score REAL,
                zone TEXT,
                speech_duration_sec REAL,
                meeting_detected INTEGER DEFAULT 0
            )
        """)

        # Daily summaries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_summaries (
                date TEXT PRIMARY KEY,
                avg_depression REAL,
                avg_anxiety REAL,
                avg_stress REAL,
                avg_mood REAL,
                avg_energy REAL,
                avg_calm REAL,
                peak_stress REAL,
                time_in_stressed_min REAL,
                time_in_tense_min REAL,
                time_in_steady_min REAL,
                time_in_calm_min REAL,
                total_speech_min REAL,
                total_meetings INTEGER,
                burnout_risk REAL,
                resilience_score REAL
            )
        """)

        # Tags table - user annotations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                label TEXT NOT NULL,
                notes TEXT
            )
        """)

        # Baselines table - personal calibration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS baselines (
                metric TEXT PRIMARY KEY,
                mean REAL,
                std REAL,
                samples INTEGER,
                last_updated TEXT
            )
        """)

        # Briefings table - daily wellness briefings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                UNIQUE(date, type)
            )
        """)

        # Grove table - streak forest trees
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grove (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                tree_state TEXT NOT NULL DEFAULT 'growing',
                growth_stage INTEGER DEFAULT 1,
                revived INTEGER DEFAULT 0
            )
        """)

        # User state - grove rainfall, streak freezes, etc.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Achievements (Waypoints)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                tier TEXT NOT NULL,
                achieved INTEGER DEFAULT 0,
                achieved_at TEXT,
                sort_order INTEGER DEFAULT 0
            )
        """)

        # Goals (Rhythm Rings)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                speak_target REAL DEFAULT 15,
                calm_target REAL DEFAULT 15,
                checkin_target INTEGER DEFAULT 5,
                UNIQUE(week_start)
            )
        """)

        # Migrate calm_target 30 → 15
        cursor.execute("UPDATE goals SET calm_target = 15 WHERE calm_target = 30")

        # Echoes (pattern discoveries)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS echoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                message TEXT NOT NULL,
                detail TEXT,
                discovered_at TEXT NOT NULL,
                seen INTEGER DEFAULT 0
            )
        """)

        # Compass entries (weekly direction)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compass_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL UNIQUE,
                direction TEXT NOT NULL,
                biggest_positive TEXT,
                biggest_negative TEXT,
                intention TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Time capsules
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS time_capsules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_type TEXT NOT NULL,
                message TEXT NOT NULL,
                detail TEXT,
                triggered_at TEXT NOT NULL,
                seen INTEGER DEFAULT 0,
                UNIQUE(trigger_type, triggered_at)
            )
        """)

        # Canopy scores (daily composite)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS canopy_scores (
                date TEXT PRIMARY KEY,
                score REAL NOT NULL,
                day_of_week INTEGER,
                weight_profile TEXT,
                computed_at TEXT NOT NULL
            )
        """)

        # Dashboard layout (Voice Garden)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_layout (
                card_id TEXT PRIMARY KEY,
                sort_order INTEGER DEFAULT 0,
                visible INTEGER DEFAULT 1
            )
        """)

        # Notification log — tracks all sent notifications
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                sent_at TEXT NOT NULL
            )
        """)

        # Notification preferences — quiet hours, enabled types
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_prefs (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Speaker profiles — voice enrollment
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS speaker_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT 'default',
                embedding BLOB,
                embedding_dim INTEGER,
                num_enrollment_samples INTEGER DEFAULT 0,
                enrollment_completed INTEGER DEFAULT 0,
                similarity_threshold REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Enrollment samples — individual recordings during setup
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrollment_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER DEFAULT 1,
                mood_label TEXT,
                embedding BLOB,
                duration_sec REAL,
                created_at TEXT NOT NULL
            )
        """)

        # Webhooks — external integrations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                condition_field TEXT,
                condition_op TEXT,
                condition_value REAL,
                created_at TEXT NOT NULL,
                active INTEGER DEFAULT 1
            )
        """)

        # Migrate: add columns if missing
        migrate_columns = [
            ("readings", "depression_mapped", "REAL"),
            ("readings", "anxiety_mapped", "REAL"),
            ("readings", "shimmer", "REAL"),
            ("readings", "voice_breaks", "INTEGER"),
            ("readings", "vad_confidence", "REAL"),
            ("readings", "low_confidence", "INTEGER DEFAULT 0"),
            ("readings", "depression_ci_lower", "REAL"),
            ("readings", "depression_ci_upper", "REAL"),
            ("readings", "anxiety_ci_lower", "REAL"),
            ("readings", "anxiety_ci_upper", "REAL"),
            ("readings", "uncertainty_flag", "TEXT"),
            ("readings", "score_inconsistency", "INTEGER DEFAULT 0"),
            ("readings", "stress_score_raw", "REAL"),
            ("readings", "mood_score_raw", "REAL"),
            ("readings", "energy_score_raw", "REAL"),
            ("readings", "calm_score_raw", "REAL"),
            ("readings", "speaker_verified", "INTEGER DEFAULT -1"),
            ("readings", "speaker_similarity", "REAL"),
        ]
        for table, col, coltype in migrate_columns:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass  # Column already exists

        self.conn.commit()

    def insert_reading(self, reading: Dict[str, Any]) -> int:
        """Insert a new reading and return its ID"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO readings (
                    timestamp, depression_raw, anxiety_raw, depression_quantized, anxiety_quantized,
                    depression_mapped, anxiety_mapped,
                    f0_mean, f0_std, speech_rate, rms_energy, spectral_centroid, spectral_entropy,
                    zcr, jitter, shimmer, voice_breaks,
                    stress_score, mood_score, energy_score, calm_score,
                    stress_score_raw, mood_score_raw, energy_score_raw, calm_score_raw,
                    zone, speech_duration_sec, meeting_detected,
                    vad_confidence, low_confidence,
                    depression_ci_lower, depression_ci_upper,
                    anxiety_ci_lower, anxiety_ci_upper,
                    uncertainty_flag, score_inconsistency,
                    speaker_verified, speaker_similarity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reading.get('timestamp', datetime.now().isoformat()),
                reading.get('depression_raw'),
                reading.get('anxiety_raw'),
                reading.get('depression_quantized'),
                reading.get('anxiety_quantized'),
                reading.get('depression_mapped'),
                reading.get('anxiety_mapped'),
                reading.get('f0_mean'),
                reading.get('f0_std'),
                reading.get('speech_rate'),
                reading.get('rms_energy'),
                reading.get('spectral_centroid'),
                reading.get('spectral_entropy'),
                reading.get('zcr'),
                reading.get('jitter'),
                reading.get('shimmer'),
                reading.get('voice_breaks'),
                reading.get('stress_score'),
                reading.get('mood_score'),
                reading.get('energy_score'),
                reading.get('calm_score'),
                reading.get('stress_score_raw'),
                reading.get('mood_score_raw'),
                reading.get('energy_score_raw'),
                reading.get('calm_score_raw'),
                reading.get('zone'),
                reading.get('speech_duration_sec'),
                reading.get('meeting_detected', 0),
                reading.get('vad_confidence'),
                reading.get('low_confidence', 0),
                reading.get('depression_ci_lower'),
                reading.get('depression_ci_upper'),
                reading.get('anxiety_ci_lower'),
                reading.get('anxiety_ci_upper'),
                reading.get('uncertainty_flag'),
                reading.get('score_inconsistency', 0),
                reading.get('speaker_verified', -1),
                reading.get('speaker_similarity'),
            ))
            self.conn.commit()
            return cursor.lastrowid

    def get_readings(self, start_time: Optional[str] = None, end_time: Optional[str] = None,
                     limit: int = 100) -> List[Dict[str, Any]]:
        """Get readings within time range"""
        with self.lock:
            cursor = self.conn.cursor()

            if start_time and end_time:
                cursor.execute("""
                    SELECT * FROM readings
                    WHERE timestamp BETWEEN ? AND ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (start_time, end_time, limit))
            elif start_time:
                cursor.execute("""
                    SELECT * FROM readings
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (start_time, limit))
            else:
                cursor.execute("""
                    SELECT * FROM readings
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

    def get_today_readings(self) -> List[Dict[str, Any]]:
        """Get all readings from today"""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        return self.get_readings(start_time=today_start, limit=500)

    def compute_daily_summary(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """Compute and store daily summary for a given date"""
        with self.lock:
            if target_date is None:
                target_date = date.today()

            date_str = target_date.isoformat()
            start_time = datetime.combine(target_date, datetime.min.time()).isoformat()
            end_time = datetime.combine(target_date, datetime.max.time()).isoformat()

            readings = self.get_readings(start_time, end_time, limit=1000)

            if not readings:
                return {}

            # Calculate averages
            summary = {
                'date': date_str,
                'avg_depression': sum((r.get('depression_mapped') or r['depression_raw'] or 0) for r in readings) / len(readings),
                'avg_anxiety': sum((r.get('anxiety_mapped') or r['anxiety_raw'] or 0) for r in readings) / len(readings),
                'avg_stress': sum(r['stress_score'] or 0 for r in readings) / len(readings),
                'avg_mood': sum(r['mood_score'] or 0 for r in readings) / len(readings),
                'avg_energy': sum(r['energy_score'] or 0 for r in readings) / len(readings),
                'avg_calm': sum(r['calm_score'] or 0 for r in readings) / len(readings),
                'peak_stress': max((r['stress_score'] or 0 for r in readings), default=0),
                'time_in_stressed_min': sum(1 for r in readings if r['zone'] == 'stressed') * 5,
                'time_in_tense_min': sum(1 for r in readings if r['zone'] == 'tense') * 5,
                'time_in_steady_min': sum(1 for r in readings if r['zone'] == 'steady') * 5,
                'time_in_calm_min': sum(1 for r in readings if r['zone'] == 'calm') * 5,
                'total_speech_min': sum(r['speech_duration_sec'] or 0 for r in readings) / 60,
                'total_meetings': sum(r['meeting_detected'] or 0 for r in readings),
                'burnout_risk': None,  # Computed separately from rolling window
                'resilience_score': None  # Computed separately from rolling window
            }

            # Insert or update
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_summaries (
                    date, avg_depression, avg_anxiety, avg_stress, avg_mood, avg_energy, avg_calm,
                    peak_stress, time_in_stressed_min, time_in_tense_min, time_in_steady_min,
                    time_in_calm_min, total_speech_min, total_meetings, burnout_risk, resilience_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                summary['date'], summary['avg_depression'], summary['avg_anxiety'],
                summary['avg_stress'], summary['avg_mood'], summary['avg_energy'],
                summary['avg_calm'], summary['peak_stress'], summary['time_in_stressed_min'],
                summary['time_in_tense_min'], summary['time_in_steady_min'],
                summary['time_in_calm_min'], summary['total_speech_min'],
                summary['total_meetings'], summary['burnout_risk'], summary['resilience_score']
            ))
            self.conn.commit()

            return summary

    def get_daily_summaries(self, days: int = 14) -> List[Dict[str, Any]]:
        """Get daily summaries for the last N days"""
        with self.lock:
            start_date = (date.today() - timedelta(days=days)).isoformat()
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM daily_summaries
                WHERE date >= ?
                ORDER BY date DESC
            """, (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def update_baseline(self, metric: str, mean: float, std: float, samples: int):
        """Update personal baseline for a metric"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO baselines (metric, mean, std, samples, last_updated)
                VALUES (?, ?, ?, ?, ?)
            """, (metric, mean, std, samples, datetime.now().isoformat()))
            self.conn.commit()

    def get_baseline(self, metric: str) -> Optional[Dict[str, Any]]:
        """Get baseline for a metric"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM baselines WHERE metric = ?", (metric,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_baselines(self) -> Dict[str, Dict[str, Any]]:
        """Get all baselines as a dict"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM baselines")
            return {row['metric']: dict(row) for row in cursor.fetchall()}

    def add_tag(self, timestamp: str, label: str, notes: str = "") -> int:
        """Add a tag/annotation"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO tags (timestamp, label, notes)
                VALUES (?, ?, ?)
            """, (timestamp, label, notes))
            self.conn.commit()
            return cursor.lastrowid

    def get_tags(self, start_time: Optional[str] = None, end_time: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tags within time range"""
        with self.lock:
            cursor = self.conn.cursor()

            if start_time and end_time:
                cursor.execute("""
                    SELECT * FROM tags
                    WHERE timestamp BETWEEN ? AND ?
                    ORDER BY timestamp
                """, (start_time, end_time))
            else:
                cursor.execute("SELECT * FROM tags ORDER BY timestamp DESC LIMIT 50")

            return [dict(row) for row in cursor.fetchall()]

    def insert_briefing(self, date: str, type: str, content: str) -> int:
        """Insert or replace daily briefing"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO briefings (date, type, content, generated_at)
                VALUES (?, ?, ?, ?)
            """, (date, type, content, datetime.now().isoformat()))
            self.conn.commit()
            return cursor.lastrowid

    def get_briefing(self, date: str, type: str) -> Optional[str]:
        """Get briefing for a specific date and type"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT content FROM briefings
                WHERE date = ? AND type = ?
            """, (date, type))
            row = cursor.fetchone()
            return row['content'] if row else None

    def get_readings_for_date(self, target_date: date) -> List[Dict[str, Any]]:
        """Get all readings for a specific date"""
        start_time = datetime.combine(target_date, datetime.min.time()).isoformat()
        end_time = datetime.combine(target_date, datetime.max.time()).isoformat()
        return self.get_readings(start_time, end_time, limit=1000)

    def get_summary_for_date(self, target_date: date) -> Optional[Dict[str, Any]]:
        """Get stored summary for a date, or compute from readings if missing"""
        with self.lock:
            date_str = target_date.isoformat()
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM daily_summaries WHERE date = ?", (date_str,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        # No stored summary — try to compute from readings
        return self.compute_daily_summary(target_date) or None

    def delete_briefing(self, date_str: str, type: str):
        """Delete a cached briefing (for force-regenerate)"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM briefings WHERE date = ? AND type = ?", (date_str, type))
            self.conn.commit()

    # ============ Grove Methods ============

    def get_grove_trees(self, limit: int = 90) -> List[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM grove ORDER BY date DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def add_grove_tree(self, date_str: str, state: str = 'growing', stage: int = 1):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO grove (date, tree_state, growth_stage)
                VALUES (?, ?, ?)
            """, (date_str, state, stage))
            self.conn.commit()

    def update_grove_tree(self, date_str: str, state: str = None, stage: int = None, revived: int = None):
        with self.lock:
            cursor = self.conn.cursor()
            updates = []
            params = []
            if state is not None:
                updates.append("tree_state = ?")
                params.append(state)
            if stage is not None:
                updates.append("growth_stage = ?")
                params.append(stage)
            if revived is not None:
                updates.append("revived = ?")
                params.append(revived)
            if updates:
                params.append(date_str)
                cursor.execute(f"UPDATE grove SET {', '.join(updates)} WHERE date = ?", params)
                self.conn.commit()

    # ============ User State Methods ============

    def get_user_state(self, key: str, default: str = '0') -> str:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value FROM user_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row['value'] if row else default

    def set_user_state(self, key: str, value: str):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_state (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.now().isoformat()))
            self.conn.commit()

    # ============ Achievements Methods ============

    def get_achievements(self) -> List[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM achievements ORDER BY sort_order")
            return [dict(row) for row in cursor.fetchall()]

    def upsert_achievement(self, aid: str, name: str, desc: str, tier: str,
                           achieved: bool, sort_order: int = 0):
        with self.lock:
            cursor = self.conn.cursor()
            # Don't overwrite achieved_at if already achieved
            cursor.execute("SELECT achieved, achieved_at FROM achievements WHERE id = ?", (aid,))
            row = cursor.fetchone()
            if row and row['achieved'] and achieved:
                achieved_at = row['achieved_at']
            else:
                achieved_at = datetime.now().isoformat() if achieved else None

            cursor.execute("""
                INSERT OR REPLACE INTO achievements (id, name, description, tier, achieved, achieved_at, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (aid, name, desc, tier, 1 if achieved else 0, achieved_at, sort_order))
            self.conn.commit()

    # ============ Goals Methods ============

    def get_current_goals(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            today = date.today()
            weekday = today.weekday()
            week_start = (today - timedelta(days=weekday)).isoformat()
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM goals WHERE week_start = ?", (week_start,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_goals(self, week_start: str, speak: float = 15, calm: float = 30, checkin: int = 5):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO goals (week_start, speak_target, calm_target, checkin_target)
                VALUES (?, ?, ?, ?)
            """, (week_start, speak, calm, checkin))
            self.conn.commit()

    # ============ Echoes Methods ============

    def get_echoes(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM echoes ORDER BY discovered_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_unseen_echo_count(self) -> int:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM echoes WHERE seen = 0")
            return cursor.fetchone()['cnt']

    def add_echo(self, pattern_type: str, message: str, detail: str = None):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO echoes (pattern_type, message, detail, discovered_at)
                VALUES (?, ?, ?, ?)
            """, (pattern_type, message, detail, datetime.now().isoformat()))
            self.conn.commit()


    def batch_add_echoes(self, echoes: list):
        """Insert multiple echoes in a single transaction.
        Each echo is a dict with keys: pattern_type, message, detail (optional)."""
        if not echoes:
            return
        with self.lock:
            cursor = self.conn.cursor()
            now = datetime.now().isoformat()
            cursor.executemany("""
                INSERT INTO echoes (pattern_type, message, detail, discovered_at)
                VALUES (?, ?, ?, ?)
            """, [(e['pattern_type'], e['message'], e.get('detail'), now) for e in echoes])
            self.conn.commit()

    def mark_echoes_seen(self):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE echoes SET seen = 1 WHERE seen = 0")
            self.conn.commit()

    # ============ Compass Methods ============

    def get_compass_entry(self, week_start: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM compass_entries WHERE week_start = ?", (week_start,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def upsert_compass(self, week_start: str, direction: str, positive: str, negative: str, intention: str = None):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO compass_entries (week_start, direction, biggest_positive, biggest_negative, intention, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (week_start, direction, positive, negative, intention, datetime.now().isoformat()))
            self.conn.commit()

    def set_compass_intention(self, week_start: str, intention: str):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE compass_entries SET intention = ? WHERE week_start = ?", (intention, week_start))
            self.conn.commit()

    # ============ Time Capsule Methods ============

    def get_time_capsules(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM time_capsules ORDER BY triggered_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def add_time_capsule(self, trigger_type: str, message: str, detail: str = None):
        with self.lock:
            cursor = self.conn.cursor()
            today = date.today().isoformat()
            try:
                cursor.execute("""
                    INSERT INTO time_capsules (trigger_type, message, detail, triggered_at)
                    VALUES (?, ?, ?, ?)
                """, (trigger_type, message, detail, today))
                self.conn.commit()
            except sqlite3.IntegrityError:
                pass  # Already triggered today

    # ============ Canopy Score Methods ============

    def get_canopy_score(self, date_str: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM canopy_scores WHERE date = ?", (date_str,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_canopy_score(self, date_str: str, score: float, dow: int, profile: str):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO canopy_scores (date, score, day_of_week, weight_profile, computed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (date_str, score, dow, profile, datetime.now().isoformat()))
            self.conn.commit()

    # ============ Dashboard Layout Methods ============

    def get_dashboard_layout(self) -> List[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM dashboard_layout ORDER BY sort_order")
            return [dict(row) for row in cursor.fetchall()]

    def set_dashboard_layout(self, layouts: List[Dict[str, Any]]):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM dashboard_layout")
            for item in layouts:
                cursor.execute("""
                    INSERT INTO dashboard_layout (card_id, sort_order, visible)
                    VALUES (?, ?, ?)
                """, (item['card_id'], item.get('sort_order', 0), item.get('visible', 1)))
            self.conn.commit()

    # ============ Notification Log Methods ============

    def log_notification(self, type: str, title: str, message: str = ""):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO notification_log (type, title, message, sent_at)
                VALUES (?, ?, ?, ?)
            """, (type, title, message, datetime.now().isoformat()))
            self.conn.commit()

    def get_notification_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM notification_log ORDER BY sent_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def count_notifications_since(self, since: str) -> int:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM notification_log WHERE sent_at >= ?", (since,))
            return cursor.fetchone()['cnt']

    # ============ Notification Preferences Methods ============

    def get_notification_pref(self, key: str, default: str = '') -> str:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value FROM notification_prefs WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row['value'] if row else default

    def set_notification_pref(self, key: str, value: str):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO notification_prefs (key, value)
                VALUES (?, ?)
            """, (key, value))
            self.conn.commit()

    def get_all_notification_prefs(self) -> Dict[str, str]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT key, value FROM notification_prefs")
            return {row['key']: row['value'] for row in cursor.fetchall()}

    # ============ Webhook Methods ============

    def add_webhook(self, url: str, trigger_type: str, condition_field: str = None,
                    condition_op: str = None, condition_value: float = None) -> int:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO webhooks (url, trigger_type, condition_field, condition_op, condition_value, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (url, trigger_type, condition_field, condition_op, condition_value, datetime.now().isoformat()))
            self.conn.commit()
            return cursor.lastrowid

    def get_webhooks(self, active_only: bool = True) -> List[Dict[str, Any]]:
        with self.lock:
            cursor = self.conn.cursor()
            if active_only:
                cursor.execute("SELECT * FROM webhooks WHERE active = 1")
            else:
                cursor.execute("SELECT * FROM webhooks")
            return [dict(row) for row in cursor.fetchall()]

    def delete_webhook(self, webhook_id: int):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            self.conn.commit()

    # ============ Speaker Verification Methods ============

    def get_speaker_profile(self) -> Optional[Dict[str, Any]]:
        """Get the active speaker profile (default)."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM speaker_profiles
                WHERE name = 'default' AND enrollment_completed = 1
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_speaker_profile(self, embedding: bytes, embedding_dim: int,
                             num_samples: int, threshold: float):
        """Save or update the speaker profile."""
        with self.lock:
            now = datetime.now().isoformat()
            cursor = self.conn.cursor()
            # Delete any existing default profile
            cursor.execute("DELETE FROM speaker_profiles WHERE name = 'default'")
            cursor.execute("""
                INSERT INTO speaker_profiles
                    (name, embedding, embedding_dim, num_enrollment_samples,
                     enrollment_completed, similarity_threshold, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """, ('default', embedding, embedding_dim, num_samples, threshold, now, now))
            self.conn.commit()

    def update_speaker_centroid(self, embedding: bytes):
        """Update the centroid embedding (adaptive EMA drift)."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE speaker_profiles SET embedding = ?, updated_at = ?
                WHERE name = 'default' AND enrollment_completed = 1
            """, (embedding, datetime.now().isoformat()))
            self.conn.commit()

    def delete_speaker_profile(self):
        """Delete speaker profile and enrollment samples."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM speaker_profiles WHERE name = 'default'")
            cursor.execute("DELETE FROM enrollment_samples WHERE profile_id = 1")
            self.conn.commit()

    def add_enrollment_sample(self, mood_label: str, embedding: bytes, duration_sec: float):
        """Add a single enrollment audio sample."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO enrollment_samples (profile_id, mood_label, embedding, duration_sec, created_at)
                VALUES (1, ?, ?, ?, ?)
            """, (mood_label, embedding, duration_sec, datetime.now().isoformat()))
            self.conn.commit()

    def get_enrollment_samples(self) -> List[Dict[str, Any]]:
        """Get all enrollment samples for the default profile."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM enrollment_samples WHERE profile_id = 1 ORDER BY id
            """)
            return [dict(row) for row in cursor.fetchall()]

    def clear_enrollment_samples(self):
        """Clear enrollment samples (before re-enrollment)."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM enrollment_samples WHERE profile_id = 1")
            self.conn.commit()

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
