"""
Database layer for Attune
SQLite storage for readings, daily summaries, tags, and baselines
"""
import sqlite3
import threading
import logging
import os
import shutil
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
import app_config as config

logger = logging.getLogger(__name__)


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

        # Enable foreign key enforcement
        cursor.execute("PRAGMA foreign_keys = ON")

        # WAL auto-checkpoint every 500 pages (~2MB)
        cursor.execute("PRAGMA wal_autocheckpoint = 500")

        # Auto-backup on startup if DB has data (>10KB)
        try:
            db_size = os.path.getsize(str(self.db_path)) if os.path.exists(str(self.db_path)) else 0
            if db_size > 10240:
                backup_path = str(self.db_path) + '.backup'
                backup_conn = sqlite3.connect(backup_path)
                self.conn.backup(backup_conn)
                backup_conn.close()
                logger.info(f"Auto-backup created ({db_size // 1024}KB)")
        except Exception as e:
            logger.warning(f"Auto-backup on startup failed (non-fatal): {e}")

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
            # Next-gen scores
            ("readings", "wellbeing_score", "REAL"),
            ("readings", "wellbeing_score_raw", "REAL"),
            ("readings", "depression_risk_score", "REAL"),
            ("readings", "depression_risk_score_raw", "REAL"),
            ("readings", "activation_score", "REAL"),
            ("readings", "activation_score_raw", "REAL"),
            ("readings", "anxiety_risk_score", "REAL"),
            ("readings", "anxiety_risk_score_raw", "REAL"),
            ("readings", "emotional_stability_score", "REAL"),
            ("readings", "emotional_stability_score_raw", "REAL"),
            # Next-gen acoustic features
            ("readings", "alpha_ratio", "REAL"),
            ("readings", "mfcc3", "REAL"),
            ("readings", "pitch_range", "REAL"),
            ("readings", "rms_sd", "REAL"),
            ("readings", "phonation_ratio", "REAL"),
            ("readings", "h1_h2", "REAL"),
            ("readings", "hnr", "REAL"),
            ("readings", "voice_tremor_index", "REAL"),
            ("readings", "pause_mean", "REAL"),
            ("readings", "pause_sd", "REAL"),
            ("readings", "pause_rate", "REAL"),
            # Next-gen daily summary columns
            ("daily_summaries", "avg_wellbeing", "REAL"),
            ("daily_summaries", "avg_activation", "REAL"),
            ("daily_summaries", "avg_depression_risk", "REAL"),
            ("daily_summaries", "avg_anxiety_risk", "REAL"),
            ("daily_summaries", "avg_emotional_stability", "REAL"),
        ]
        for table, col, coltype in migrate_columns:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e).lower():
                    logger.warning("Unexpected ALTER TABLE error for %s.%s: %s", table, col, e)

        # Active assessments (Voice Scan)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                speech_duration_sec REAL,
                recording_duration_sec REAL,
                depression_raw REAL,
                anxiety_raw REAL,
                depression_mapped REAL,
                anxiety_mapped REAL,
                depression_quantized INTEGER,
                anxiety_quantized INTEGER,
                depression_ci_lower REAL,
                depression_ci_upper REAL,
                anxiety_ci_lower REAL,
                anxiety_ci_upper REAL,
                uncertainty_flag TEXT,
                score_inconsistency INTEGER DEFAULT 0,
                stress_score REAL,
                mood_score REAL,
                energy_score REAL,
                calm_score REAL,
                wellbeing_score REAL,
                activation_score REAL,
                depression_risk_score REAL,
                anxiety_risk_score REAL,
                emotional_stability_score REAL,
                zone TEXT,
                prompt_text TEXT,
                notes TEXT
            )
        """)

        # Schema version tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT
            )
        """)

        self.conn.commit()

        # Run versioned migrations
        self._run_migrations()

        # Auto-vacuum if database is large
        self._maybe_vacuum()

    def _run_migrations(self):
        """Run pending schema migrations in order."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        current = cursor.fetchone()[0]

        migrations = [
            (1, "Add performance indexes", self._migration_001_indexes),
            (2, "Add FK on enrollment_samples", self._migration_002_enrollment_fk),
        ]

        for version, desc, func in migrations:
            if version > current:
                logger.info("Running migration %d: %s", version, desc)
                try:
                    func(cursor)
                    cursor.execute(
                        "INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                        (version, datetime.now().isoformat(), desc)
                    )
                    self.conn.commit()
                    logger.info("Migration %d complete", version)
                except Exception as e:
                    self.conn.rollback()
                    logger.exception("Migration %d failed: %s", version, desc)
                    raise

    def _migration_001_indexes(self, cursor):
        """Add indexes on frequently-queried columns."""
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_summaries_date ON daily_summaries(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notification_log_sent_at ON notification_log(sent_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_grove_date ON grove(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_echoes_discovered_at ON echoes(discovered_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_echoes_seen ON echoes(seen)")

    def _migration_002_enrollment_fk(self, cursor):
        """Recreate enrollment_samples with FK constraint on speaker_profiles."""
        cursor.execute("SELECT COUNT(*) FROM enrollment_samples")
        if cursor.fetchone()[0] == 0:
            # No data — safe to drop and recreate with FK
            cursor.execute("DROP TABLE IF EXISTS enrollment_samples")
            cursor.execute("""
                CREATE TABLE enrollment_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER DEFAULT 1 REFERENCES speaker_profiles(id) ON DELETE CASCADE,
                    mood_label TEXT,
                    embedding BLOB,
                    duration_sec REAL,
                    created_at TEXT NOT NULL
                )
            """)
        else:
            # Has data — create new table, copy, swap
            cursor.execute("""
                CREATE TABLE enrollment_samples_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER DEFAULT 1 REFERENCES speaker_profiles(id) ON DELETE CASCADE,
                    mood_label TEXT,
                    embedding BLOB,
                    duration_sec REAL,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                INSERT INTO enrollment_samples_new (id, profile_id, mood_label, embedding, duration_sec, created_at)
                SELECT id, profile_id, mood_label, embedding, duration_sec, created_at
                FROM enrollment_samples
            """)
            cursor.execute("DROP TABLE enrollment_samples")
            cursor.execute("ALTER TABLE enrollment_samples_new RENAME TO enrollment_samples")

    def _maybe_vacuum(self):
        """VACUUM if database file is over 100MB to reclaim space."""
        try:
            db_size = os.path.getsize(self.db_path)
            if db_size > 100 * 1024 * 1024:  # 100MB
                logger.info("Database is %d MB, running VACUUM", db_size // (1024 * 1024))
                self.conn.execute("VACUUM")
                logger.info("VACUUM complete")
        except OSError:
            pass  # File doesn't exist yet or permission error

    def health_check(self) -> bool:
        """Verify database connection is alive."""
        try:
            with self.lock:
                self.conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.debug("Health check failed: %s", e)
            return False

    def check_and_repair(self) -> bool:
        """Run integrity check. If corrupt, backup corrupt file and create fresh DB."""
        try:
            with self.lock:
                result = self.conn.execute("PRAGMA integrity_check").fetchone()
                if result[0] == 'ok':
                    return True
                logger.error(f"Database corruption detected: {result[0]}")
                corrupt_path = str(self.db_path) + '.corrupt.' + date.today().isoformat()
                shutil.copy2(str(self.db_path), corrupt_path)
                logger.info(f"Corrupt database backed up to {corrupt_path}")
                self.conn.close()
                os.rename(str(self.db_path), corrupt_path)
                self._init_db()
                return False
        except Exception as e:
            logger.error(f"Integrity check failed: {e}")
            return True  # assume OK if check itself fails

    def insert_reading(self, reading: Dict[str, Any]) -> int:
        """Insert a new reading and return its ID.
        Validates data through Pydantic ReadingInsert model before inserting."""
        from api.schemas import ReadingInsert

        # Validate and sanitize through Pydantic — clamps scores, checks ranges
        validated = ReadingInsert(**reading)
        r = validated.model_dump()

        # Fill in timestamp if not provided
        if r['timestamp'] is None:
            r['timestamp'] = datetime.now().isoformat()

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
                    speaker_verified, speaker_similarity,
                    wellbeing_score, wellbeing_score_raw,
                    depression_risk_score, depression_risk_score_raw,
                    activation_score, activation_score_raw,
                    anxiety_risk_score, anxiety_risk_score_raw,
                    emotional_stability_score, emotional_stability_score_raw,
                    alpha_ratio, mfcc3, pitch_range, rms_sd, phonation_ratio,
                    h1_h2, hnr, voice_tremor_index, pause_mean, pause_sd, pause_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r['timestamp'],
                r['depression_raw'],
                r['anxiety_raw'],
                r['depression_quantized'],
                r['anxiety_quantized'],
                r['depression_mapped'],
                r['anxiety_mapped'],
                r['f0_mean'],
                r['f0_std'],
                r['speech_rate'],
                r['rms_energy'],
                r['spectral_centroid'],
                r['spectral_entropy'],
                r['zcr'],
                r['jitter'],
                r['shimmer'],
                r['voice_breaks'],
                r['stress_score'],
                r['mood_score'],
                r['energy_score'],
                r['calm_score'],
                r['stress_score_raw'],
                r['mood_score_raw'],
                r['energy_score_raw'],
                r['calm_score_raw'],
                r['zone'],
                r['speech_duration_sec'],
                r['meeting_detected'],
                r['vad_confidence'],
                r['low_confidence'],
                r['depression_ci_lower'],
                r['depression_ci_upper'],
                r['anxiety_ci_lower'],
                r['anxiety_ci_upper'],
                r['uncertainty_flag'],
                r['score_inconsistency'],
                r['speaker_verified'],
                r['speaker_similarity'],
                r['wellbeing_score'],
                r['wellbeing_score_raw'],
                r['depression_risk_score'],
                r['depression_risk_score_raw'],
                r['activation_score'],
                r['activation_score_raw'],
                r['anxiety_risk_score'],
                r['anxiety_risk_score_raw'],
                r['emotional_stability_score'],
                r['emotional_stability_score_raw'],
                r['alpha_ratio'],
                r['mfcc3'],
                r['pitch_range'],
                r['rms_sd'],
                r['phonation_ratio'],
                r['h1_h2'],
                r['hnr'],
                r['voice_tremor_index'],
                r['pause_mean'],
                r['pause_sd'],
                r['pause_rate'],
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

    def count_readings(self) -> int:
        """Return total number of readings (efficient COUNT query)."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM readings")
            return cursor.fetchone()['cnt']

    def get_first_reading_timestamp(self) -> Optional[str]:
        """Return timestamp of the earliest reading."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT timestamp FROM readings ORDER BY timestamp ASC LIMIT 1")
            row = cursor.fetchone()
            return row['timestamp'] if row else None

    def count_readings_since(self, start_time: str) -> int:
        """Return count of readings since a given timestamp."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM readings WHERE timestamp >= ?", (start_time,))
            return cursor.fetchone()['cnt']

    def count_daily_summaries(self, days: int = 365) -> int:
        """Return count of daily summaries in the last N days."""
        with self.lock:
            start_date = (date.today() - timedelta(days=days)).isoformat()
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM daily_summaries WHERE date >= ?", (start_date,))
            return cursor.fetchone()['cnt']

    def prune_old_readings(self, retention_days: int = 90) -> int:
        """Delete readings older than retention_days. Returns count deleted."""
        with self.lock:
            cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM readings WHERE timestamp < ?", (cutoff,))
            count = cursor.fetchone()['cnt']
            if count > 0:
                cursor.execute("DELETE FROM readings WHERE timestamp < ?", (cutoff,))
                self.conn.commit()
                logger.info(f"Pruned {count} readings older than {retention_days} days")
            return count

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

            # Helper for safe averaging (filters out None values)
            def safe_avg(key):
                vals = [r.get(key) for r in readings if r.get(key) is not None]
                return sum(vals) / len(vals) if vals else 0

            # Calculate averages
            summary = {
                'date': date_str,
                'avg_depression': sum((r.get('depression_mapped') or r.get('depression_raw') or 0) for r in readings) / len(readings),
                'avg_anxiety': sum((r.get('anxiety_mapped') or r.get('anxiety_raw') or 0) for r in readings) / len(readings),
                'avg_stress': safe_avg('stress_score'),
                'avg_mood': safe_avg('mood_score'),
                'avg_energy': safe_avg('energy_score'),
                'avg_calm': safe_avg('calm_score'),
                'peak_stress': max((r.get('stress_score') or 0 for r in readings), default=0),
                'time_in_stressed_min': sum(1 for r in readings if r.get('zone') == 'stressed') * 5,
                'time_in_tense_min': sum(1 for r in readings if r.get('zone') == 'tense') * 5,
                'time_in_steady_min': sum(1 for r in readings if r.get('zone') == 'steady') * 5,
                'time_in_calm_min': sum(1 for r in readings if r.get('zone') == 'calm') * 5,
                'total_speech_min': sum(r.get('speech_duration_sec') or 0 for r in readings) / 60,
                'total_meetings': sum(r.get('meeting_detected') or 0 for r in readings),
                'burnout_risk': None,
                'resilience_score': None,
                # Next-gen averages (fall back to legacy score names for old readings)
                'avg_wellbeing': safe_avg('wellbeing_score') or safe_avg('mood_score'),
                'avg_activation': safe_avg('activation_score') or safe_avg('energy_score'),
                'avg_depression_risk': safe_avg('depression_risk_score'),
                'avg_anxiety_risk': safe_avg('anxiety_risk_score'),
                'avg_emotional_stability': safe_avg('emotional_stability_score'),
            }

            # Insert or update
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_summaries (
                    date, avg_depression, avg_anxiety, avg_stress, avg_mood, avg_energy, avg_calm,
                    peak_stress, time_in_stressed_min, time_in_tense_min, time_in_steady_min,
                    time_in_calm_min, total_speech_min, total_meetings, burnout_risk, resilience_score,
                    avg_wellbeing, avg_activation, avg_depression_risk, avg_anxiety_risk, avg_emotional_stability
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                summary['date'], summary['avg_depression'], summary['avg_anxiety'],
                summary['avg_stress'], summary['avg_mood'], summary['avg_energy'],
                summary['avg_calm'], summary['peak_stress'], summary['time_in_stressed_min'],
                summary['time_in_tense_min'], summary['time_in_steady_min'],
                summary['time_in_calm_min'], summary['total_speech_min'],
                summary['total_meetings'], summary['burnout_risk'], summary['resilience_score'],
                summary['avg_wellbeing'], summary['avg_activation'],
                summary['avg_depression_risk'], summary['avg_anxiety_risk'],
                summary['avg_emotional_stability'],
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
            try:
                cursor.execute("BEGIN")
                cursor.execute("DELETE FROM dashboard_layout")
                for item in layouts:
                    cursor.execute("""
                        INSERT INTO dashboard_layout (card_id, sort_order, visible)
                        VALUES (?, ?, ?)
                    """, (item['card_id'], item.get('sort_order', 0), item.get('visible', 1)))
                self.conn.commit()
            except Exception as e:
                self.conn.rollback()
                logger.error("Failed to save dashboard layout: %s", e)
                raise

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

    def delete_speaker_profile(self, profile_id: int = 1):
        """Delete speaker profile and enrollment samples."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM speaker_profiles WHERE name = 'default'")
            cursor.execute("DELETE FROM enrollment_samples WHERE profile_id = ?", (profile_id,))
            self.conn.commit()

    def add_enrollment_sample(self, mood_label: str, embedding: bytes, duration_sec: float,
                              profile_id: int = 1):
        """Add a single enrollment audio sample."""
        with self.lock:
            cursor = self.conn.cursor()
            # Ensure placeholder profile exists so FK constraint is satisfied
            cursor.execute("SELECT id FROM speaker_profiles WHERE id = ?", (profile_id,))
            if cursor.fetchone() is None:
                now = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO speaker_profiles (id, name, enrollment_completed, created_at, updated_at)
                    VALUES (?, 'default', 0, ?, ?)
                """, (profile_id, now, now))
            cursor.execute("""
                INSERT INTO enrollment_samples (profile_id, mood_label, embedding, duration_sec, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (profile_id, mood_label, embedding, duration_sec, datetime.now().isoformat()))
            self.conn.commit()

    def get_enrollment_samples(self, profile_id: int = 1) -> List[Dict[str, Any]]:
        """Get all enrollment samples for the given profile."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM enrollment_samples WHERE profile_id = ? ORDER BY id
            """, (profile_id,))
            return [dict(row) for row in cursor.fetchall()]

    def clear_enrollment_samples(self, profile_id: int = 1):
        """Clear enrollment samples (before re-enrollment)."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM enrollment_samples WHERE profile_id = ?", (profile_id,))
            self.conn.commit()

    def backup(self, dest_path=None):
        """Create a backup of the database using SQLite backup API."""
        if dest_path is None:
            dest_path = str(self.db_path) + '.backup'
        try:
            with self.lock:
                backup_conn = sqlite3.connect(dest_path)
                self.conn.backup(backup_conn)
                backup_conn.close()
            logger.info(f"Database backed up to {dest_path}")
            return True
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            return False

    def integrity_check(self):
        """Run SQLite integrity check. Returns True if database is healthy."""
        try:
            with self.lock:
                cursor = self.conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()[0]
            if result == 'ok':
                logger.debug("Database integrity check passed")
                return True
            else:
                logger.error(f"Database integrity check failed: {result}")
                return False
        except Exception as e:
            logger.error(f"Database integrity check error: {e}")
            return False

    def restore_from_backup(self):
        """Attempt to restore database from backup file."""
        backup_path = str(self.db_path) + '.backup'
        if not os.path.exists(backup_path):
            logger.warning("No backup file found for restoration")
            return False
        try:
            if self.conn:
                self.conn.close()
            shutil.copy2(backup_path, str(self.db_path))
            self._init_db()
            logger.info("Database restored from backup")
            return True
        except Exception as e:
            logger.error(f"Database restore failed: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Active Assessments (Voice Scan)
    # ------------------------------------------------------------------ #

    def insert_active_assessment(self, data: Dict[str, Any]) -> int:
        """Insert a voice scan result and return its ID."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO active_assessments (
                    timestamp, speech_duration_sec, recording_duration_sec,
                    depression_raw, anxiety_raw, depression_mapped, anxiety_mapped,
                    depression_quantized, anxiety_quantized,
                    depression_ci_lower, depression_ci_upper,
                    anxiety_ci_lower, anxiety_ci_upper,
                    uncertainty_flag, score_inconsistency,
                    stress_score, mood_score, energy_score, calm_score,
                    wellbeing_score, activation_score,
                    depression_risk_score, anxiety_risk_score,
                    emotional_stability_score, zone, prompt_text, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get('timestamp', datetime.now().isoformat()),
                data.get('speech_duration_sec'),
                data.get('recording_duration_sec'),
                data.get('depression_raw'),
                data.get('anxiety_raw'),
                data.get('depression_mapped'),
                data.get('anxiety_mapped'),
                data.get('depression_quantized'),
                data.get('anxiety_quantized'),
                data.get('depression_ci_lower'),
                data.get('depression_ci_upper'),
                data.get('anxiety_ci_lower'),
                data.get('anxiety_ci_upper'),
                data.get('uncertainty_flag'),
                data.get('score_inconsistency', 0),
                data.get('stress_score'),
                data.get('mood_score'),
                data.get('energy_score'),
                data.get('calm_score'),
                data.get('wellbeing_score'),
                data.get('activation_score'),
                data.get('depression_risk_score'),
                data.get('anxiety_risk_score'),
                data.get('emotional_stability_score'),
                data.get('zone'),
                data.get('prompt_text'),
                data.get('notes'),
            ))
            self.conn.commit()
            return cursor.lastrowid

    def get_active_assessments(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent voice scan results."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM active_assessments
                ORDER BY timestamp DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_active_assessment(self) -> Optional[Dict[str, Any]]:
        """Get the most recent voice scan result."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM active_assessments
                ORDER BY timestamp DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_active_assessment_notes(self, assessment_id: int, notes: str) -> bool:
        """Update notes on an existing voice scan."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE active_assessments SET notes = ? WHERE id = ?",
                (notes, assessment_id)
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def close(self):
        """Close database connection with WAL checkpoint."""
        with self.lock:
            if self.conn:
                try:
                    self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception as e:
                    logger.warning("WAL checkpoint on close failed: %s", e)
                try:
                    self.conn.close()
                except Exception as e:
                    logger.warning("Database close failed: %s", e)
                self.conn = None
