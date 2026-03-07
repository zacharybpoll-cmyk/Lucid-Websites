"""
Clarity Journey engine — 12-week structured score-improvement coaching.
Three personalization tracks, weekly AI check-ins, progress arc.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger('lucid.clarity')

# Track definitions
TRACKS = {
    'calm': {
        'name': 'Calm',
        'primary': 'calm',
        'secondary': 'stress',
        'desc': 'Build deep calm and reduce stress reactivity',
        'primary_col': 'avg_calm',
        'secondary_col': 'avg_stress',
    },
    'energy': {
        'name': 'Energy',
        'primary': 'activation',
        'secondary': 'wellbeing',
        'desc': 'Boost vocal energy and overall wellbeing',
        'primary_col': 'avg_activation',
        'secondary_col': 'avg_wellbeing',
    },
    'stability': {
        'name': 'Stability',
        'primary': 'emotional_stability',
        'secondary': 'depression',
        'desc': 'Strengthen emotional resilience',
        'primary_col': 'avg_emotional_stability',
        'secondary_col': 'avg_depression_risk',
    },
}

# Action library: per-track, per-phase
# Phases: calibration (W1-2), core (W3-6), progressive (W7-10), review (W11-12)
ACTION_LIBRARY = {
    'calm': {
        'calibration': [
            {'type': 'breathing', 'title': 'Box Breathing', 'desc': 'Inhale 4s, hold 4s, exhale 4s, hold 4s. Repeat 5 cycles.', 'duration': 5},
            {'type': 'reflection', 'title': 'Stress Awareness Journal', 'desc': 'Write down your top 3 stressors today and rate each 1-10.', 'duration': 5},
            {'type': 'breathing', 'title': '4-7-8 Breathing', 'desc': 'Inhale 4s, hold 7s, exhale 8s. Repeat 4 cycles.', 'duration': 5},
            {'type': 'meditation', 'title': 'Body Scan', 'desc': 'Scan from head to toe, noticing tension. Breathe into tight areas.', 'duration': 5},
            {'type': 'reflection', 'title': 'Calm Baseline Check', 'desc': 'Record your current calm level 1-10. Note what affected it today.', 'duration': 3},
        ],
        'core': [
            {'type': 'breathing', 'title': 'Diaphragmatic Breathing', 'desc': 'Deep belly breaths. Hand on chest stays still, hand on belly rises.', 'duration': 5},
            {'type': 'meditation', 'title': 'Guided Relaxation', 'desc': 'Progressive muscle relaxation: tense each group 5s, release 10s.', 'duration': 10},
            {'type': 'journaling', 'title': 'Gratitude Pause', 'desc': 'Write 3 things you are grateful for. Notice the feeling each brings.', 'duration': 5},
            {'type': 'breathing', 'title': 'Coherent Breathing', 'desc': 'Breathe at 5 breaths per minute (6s in, 6s out) for 5 minutes.', 'duration': 5},
            {'type': 'reflection', 'title': 'Trigger Mapping', 'desc': 'Identify one stressor from today. Write an alternative response.', 'duration': 5},
        ],
        'progressive': [
            {'type': 'meditation', 'title': 'Calm Anchor Visualization', 'desc': 'Visualize your calmest memory. Anchor it with a physical gesture.', 'duration': 8},
            {'type': 'breathing', 'title': 'Extended Exhale', 'desc': 'Inhale 4s, exhale 8s. Focus on the slow release. 5 minutes.', 'duration': 5},
            {'type': 'journaling', 'title': 'Stress Reframe', 'desc': 'Take today\'s biggest stressor. Write 3 ways it could be a growth opportunity.', 'duration': 7},
            {'type': 'meditation', 'title': 'Non-Reactive Observation', 'desc': 'Sit quietly. Notice thoughts without reacting. Label them "thinking."', 'duration': 10},
            {'type': 'reflection', 'title': 'Weekly Calm Review', 'desc': 'Compare this week\'s calm moments to last week. What helped most?', 'duration': 5},
        ],
        'review': [
            {'type': 'reflection', 'title': 'Journey Reflection', 'desc': 'Review your calm scores from week 1 to now. What changed?', 'duration': 10},
            {'type': 'journaling', 'title': 'Future Calm Plan', 'desc': 'Write your top 3 strategies for maintaining calm going forward.', 'duration': 7},
            {'type': 'meditation', 'title': 'Celebration Meditation', 'desc': 'Sit with eyes closed. Appreciate the progress you\'ve made.', 'duration': 5},
        ],
    },
    'energy': {
        'calibration': [
            {'type': 'breathing', 'title': 'Energizing Breath', 'desc': 'Quick inhale through nose, sharp exhale through mouth. 20 cycles.', 'duration': 3},
            {'type': 'reflection', 'title': 'Energy Audit', 'desc': 'Track your energy levels every 2 hours today. Note peaks and valleys.', 'duration': 5},
            {'type': 'breathing', 'title': 'Bellows Breath', 'desc': 'Rapid equal inhale/exhale through nose. 15s on, 15s rest. 3 rounds.', 'duration': 5},
            {'type': 'journaling', 'title': 'Vitality Sources', 'desc': 'List 5 activities that give you energy. Rate each 1-10.', 'duration': 5},
            {'type': 'reflection', 'title': 'Energy Baseline', 'desc': 'Rate your current energy 1-10. What time of day do you feel best?', 'duration': 3},
        ],
        'core': [
            {'type': 'breathing', 'title': 'Power Breathing', 'desc': 'Standing: inhale arms up, exhale arms down forcefully. 2 minutes.', 'duration': 5},
            {'type': 'reflection', 'title': 'Energy Drains', 'desc': 'Identify your top 3 energy drains this week. Plan one change.', 'duration': 5},
            {'type': 'meditation', 'title': 'Morning Activation', 'desc': 'Before getting up: visualize your day going well. Feel the energy.', 'duration': 5},
            {'type': 'journaling', 'title': 'Peak Performance Log', 'desc': 'Describe a moment today when you felt most alive. What caused it?', 'duration': 5},
            {'type': 'breathing', 'title': 'Alternate Nostril', 'desc': 'Block right nostril inhale left, switch, exhale right. 5 minutes.', 'duration': 5},
        ],
        'progressive': [
            {'type': 'meditation', 'title': 'Energy Visualization', 'desc': 'Imagine warm golden light flowing from your core to your limbs.', 'duration': 8},
            {'type': 'reflection', 'title': 'Rhythm Optimization', 'desc': 'Review your energy patterns. Reschedule one task to match your peak.', 'duration': 5},
            {'type': 'journaling', 'title': 'Activation Statement', 'desc': 'Write a personal mantra for energy. Repeat it 10 times aloud.', 'duration': 5},
            {'type': 'breathing', 'title': 'Fire Breath', 'desc': 'Rapid diaphragmatic pumping. 30s on, 30s rest. 3 rounds.', 'duration': 5},
            {'type': 'reflection', 'title': 'Weekly Energy Review', 'desc': 'Chart your weekly energy trend. What patterns emerge?', 'duration': 5},
        ],
        'review': [
            {'type': 'reflection', 'title': 'Energy Journey Review', 'desc': 'Compare your energy scores from week 1 to now.', 'duration': 10},
            {'type': 'journaling', 'title': 'Sustainable Energy Plan', 'desc': 'Write your top 3 strategies for maintaining energy.', 'duration': 7},
            {'type': 'meditation', 'title': 'Gratitude for Growth', 'desc': 'Reflect on how your energy has transformed over 12 weeks.', 'duration': 5},
        ],
    },
    'stability': {
        'calibration': [
            {'type': 'breathing', 'title': 'Grounding Breath', 'desc': 'Feel your feet on the floor. Breathe slowly 5s in, 5s out.', 'duration': 5},
            {'type': 'reflection', 'title': 'Emotional Weather Report', 'desc': 'Describe your emotional state like weather. Sunny? Stormy? Cloudy?', 'duration': 5},
            {'type': 'journaling', 'title': 'Mood Swings Log', 'desc': 'Note each significant mood shift today. What triggered each one?', 'duration': 5},
            {'type': 'meditation', 'title': 'Equanimity Practice', 'desc': 'Sit with whatever you feel. Don\'t try to change it. Just observe.', 'duration': 5},
            {'type': 'reflection', 'title': 'Stability Baseline', 'desc': 'Rate your emotional stability 1-10. When do you feel most grounded?', 'duration': 3},
        ],
        'core': [
            {'type': 'breathing', 'title': 'Centering Breath', 'desc': 'Breathe into your center of gravity (2 inches below navel). 5 minutes.', 'duration': 5},
            {'type': 'reflection', 'title': 'Reaction vs Response', 'desc': 'Recall a reactive moment today. How could you have responded instead?', 'duration': 5},
            {'type': 'meditation', 'title': 'Mountain Meditation', 'desc': 'Visualize yourself as a mountain: solid, unmoved by weather.', 'duration': 8},
            {'type': 'journaling', 'title': 'Emotional Toolkit', 'desc': 'List 3 strategies that help you regain balance when upset.', 'duration': 5},
            {'type': 'breathing', 'title': 'Heart-Centered Breathing', 'desc': 'Focus attention on your heart area. Breathe slowly through it.', 'duration': 5},
        ],
        'progressive': [
            {'type': 'meditation', 'title': 'Inner Anchor', 'desc': 'Find your still point inside. Return to it when emotions surge.', 'duration': 10},
            {'type': 'reflection', 'title': 'Trigger Inoculation', 'desc': 'Imagine a known trigger. Practice your calm response mentally.', 'duration': 7},
            {'type': 'journaling', 'title': 'Resilience Narrative', 'desc': 'Write about a time you bounced back from difficulty. What helped?', 'duration': 7},
            {'type': 'breathing', 'title': 'Vagal Toning Breath', 'desc': 'Long hum on exhale. Feel the vibration in your chest. 5 minutes.', 'duration': 5},
            {'type': 'reflection', 'title': 'Weekly Stability Review', 'desc': 'How many emotional peaks/valleys this week vs last?', 'duration': 5},
        ],
        'review': [
            {'type': 'reflection', 'title': 'Stability Journey Review', 'desc': 'Compare emotional stability from week 1 to now.', 'duration': 10},
            {'type': 'journaling', 'title': 'Resilience Blueprint', 'desc': 'Write your top 3 strategies for emotional resilience.', 'duration': 7},
            {'type': 'meditation', 'title': 'Integration Meditation', 'desc': 'Sit quietly. Feel the stability you\'ve cultivated. It\'s yours.', 'duration': 5},
        ],
    },
}


def _get_phase(week: int) -> str:
    """Return phase name for a given week number (1-12)."""
    if week <= 2:
        return 'calibration'
    elif week <= 6:
        return 'core'
    elif week <= 10:
        return 'progressive'
    else:
        return 'review'


class ClarityEngine:
    def __init__(self, db):
        self.db = db

    def start_journey(self, track: str, target_score: float) -> Dict[str, Any]:
        """Start a new 12-week clarity journey."""
        if track not in TRACKS:
            raise ValueError(f"Invalid track: {track}. Must be one of {list(TRACKS.keys())}")

        # Check for existing active journey
        active = self.db.get_active_clarity_journey()
        if active:
            raise ValueError("An active journey already exists. Abandon it first.")

        track_info = TRACKS[track]
        baseline = self._compute_baseline(track_info['primary_col'])

        journey_id = self.db.insert_clarity_journey(
            track=track,
            target_gauge=track_info['primary'],
            secondary_gauge=track_info['secondary'],
            baseline=baseline,
            target=target_score,
        )

        # Generate first 2 weeks of actions
        self._generate_week_actions(journey_id, track, 1)
        self._generate_week_actions(journey_id, track, 2)

        return self.get_journey_progress(journey_id)

    def get_active_journey(self) -> Optional[Dict[str, Any]]:
        """Get the active journey or None."""
        return self.db.get_active_clarity_journey()

    def get_journey_progress(self, journey_id: int = None) -> Optional[Dict[str, Any]]:
        """Full progress data for a journey."""
        if journey_id is None:
            journey = self.db.get_active_clarity_journey()
            if not journey:
                return None
            journey_id = journey['id']
        else:
            journey = self.db.get_active_clarity_journey()
            if not journey or journey['id'] != journey_id:
                return None

        snapshots = self.db.get_clarity_weekly_snapshots(journey_id)
        today_action = self.get_todays_action(journey_id)
        completion = self.db.get_clarity_action_completion_rate(journey_id)
        track_info = TRACKS.get(journey['track'], {})

        # Get current score
        current_score = self._compute_baseline(track_info.get('primary_col', 'avg_calm'))

        return {
            'id': journey_id,
            'track': journey['track'],
            'track_name': track_info.get('name', journey['track']),
            'track_desc': track_info.get('desc', ''),
            'target_gauge': journey['target_gauge'],
            'secondary_gauge': journey['secondary_gauge'],
            'baseline_score': journey['baseline_score'],
            'target_score': journey['target_score'],
            'current_score': current_score,
            'current_week': journey['current_week'],
            'status': journey['status'],
            'started_at': journey['started_at'],
            'snapshots': snapshots,
            'today_action': today_action,
            'completion': completion,
            'phase': _get_phase(journey['current_week']),
        }

    def get_todays_action(self, journey_id: int = None) -> Optional[Dict[str, Any]]:
        """Get today's micro-action."""
        if journey_id is None:
            journey = self.db.get_active_clarity_journey()
            if not journey:
                return None
            journey_id = journey['id']

        today_str = date.today().isoformat()
        actions = self.db.get_clarity_actions(journey_id, date_filter=today_str)
        return actions[0] if actions else None

    def complete_action(self, action_id: int) -> Dict[str, Any]:
        """Mark an action as complete."""
        success = self.db.complete_clarity_action(action_id)
        if not success:
            raise ValueError(f"Action {action_id} not found or already completed")
        return {'success': True, 'completed_at': datetime.now().isoformat()}

    def advance_week(self) -> Optional[Dict[str, Any]]:
        """Check if we need to advance to next week based on date. Called on load."""
        journey = self.db.get_active_clarity_journey()
        if not journey:
            return None

        journey_id = journey['id']
        started = datetime.fromisoformat(journey['started_at'])
        days_elapsed = (datetime.now() - started).days
        expected_week = min((days_elapsed // 7) + 1, 12)

        if expected_week > journey['current_week']:
            # Compute snapshot for the completed week
            self._compute_weekly_snapshot(journey_id, journey['current_week'], journey['track'])

            # Advance
            new_week = expected_week
            self.db.update_clarity_journey(journey_id, current_week=new_week)

            # Generate actions for the new week (and next if available)
            self._generate_week_actions(journey_id, journey['track'], new_week)
            if new_week < 12:
                self._generate_week_actions(journey_id, journey['track'], new_week + 1)

            # Check graduation
            if new_week >= 12:
                self.graduate_journey(journey_id)

        return self.get_journey_progress(journey_id)

    def get_progress_arc_data(self, journey_id: int = None) -> Dict[str, Any]:
        """Chart data: actual scores vs projected trajectory."""
        if journey_id is None:
            journey = self.db.get_active_clarity_journey()
            if not journey:
                return {'weeks': [], 'baseline': 0, 'target': 0}
            journey_id = journey['id']
        else:
            journey = self.db.get_active_clarity_journey()

        if not journey:
            return {'weeks': [], 'baseline': 0, 'target': 0}

        baseline = journey['baseline_score'] or 0
        target = journey['target_score'] or 0
        snapshots = self.db.get_clarity_weekly_snapshots(journey_id)

        weeks = []
        for w in range(1, 13):
            projected = baseline + (target - baseline) * (w / 12)
            snap = next((s for s in snapshots if s['week_number'] == w), None)
            actual = snap['avg_target_score'] if snap else None

            milestone = None
            if w == 2:
                milestone = 'Calibration Complete'
            elif w == 6:
                milestone = 'Core Phase Complete'
            elif w == 10:
                milestone = 'Progressive Phase Complete'
            elif w == 12:
                milestone = 'Journey Complete'

            weeks.append({
                'week': w,
                'projected': round(projected, 1),
                'actual': round(actual, 1) if actual is not None else None,
                'milestone': milestone,
                'phase': _get_phase(w),
            })

        return {
            'weeks': weeks,
            'baseline': round(baseline, 1),
            'target': round(target, 1),
        }

    def get_summary_for_dashboard(self) -> Optional[Dict[str, Any]]:
        """Lightweight summary for the Today dashboard widget."""
        journey = self.db.get_active_clarity_journey()
        if not journey:
            return None

        track_info = TRACKS.get(journey['track'], {})
        today_action = self.get_todays_action(journey['id'])
        completion = self.db.get_clarity_action_completion_rate(journey['id'])
        current_score = self._compute_baseline(track_info.get('primary_col', 'avg_calm'))

        return {
            'track': journey['track'],
            'track_name': track_info.get('name', journey['track']),
            'current_week': journey['current_week'],
            'total_weeks': 12,
            'baseline_score': journey['baseline_score'],
            'current_score': current_score,
            'target_score': journey['target_score'],
            'today_action': today_action,
            'completion_rate': completion.get('overall_rate', 0),
        }

    def graduate_journey(self, journey_id: int = None):
        """Mark journey as graduated."""
        if journey_id is None:
            journey = self.db.get_active_clarity_journey()
            if not journey:
                return
            journey_id = journey['id']
        self.db.update_clarity_journey(
            journey_id,
            status='graduated',
            graduated_at=datetime.now().isoformat()
        )

    def abandon_journey(self) -> bool:
        """Abandon the active journey."""
        journey = self.db.get_active_clarity_journey()
        if not journey:
            return False
        self.db.update_clarity_journey(journey['id'], status='abandoned')
        return True

    def get_tracks_with_scores(self) -> List[Dict[str, Any]]:
        """Return available tracks with current gauge scores."""
        result = []
        for key, info in TRACKS.items():
            score = self._compute_baseline(info['primary_col'])
            result.append({
                'key': key,
                'name': info['name'],
                'desc': info['desc'],
                'primary_gauge': info['primary'],
                'secondary_gauge': info['secondary'],
                'current_score': score,
                'suggested_target': min(round((score or 50) + 15, 0), 95),
            })
        return result

    # ── Private helpers ──

    def _compute_baseline(self, col_name: str) -> Optional[float]:
        """Compute baseline from last 14 days of daily summaries."""
        with self.db.lock:
            cursor = self.db.conn.cursor()
            start = (date.today() - timedelta(days=14)).isoformat()
            cursor.execute(
                f"SELECT AVG({col_name}) as avg_val FROM daily_summaries WHERE date >= ? AND {col_name} IS NOT NULL",
                (start,)
            )
            row = cursor.fetchone()
            val = row['avg_val'] if row else None
            return round(val, 1) if val is not None else None

    def _generate_week_actions(self, journey_id: int, track: str, week: int):
        """Generate daily actions for a given week."""
        if week < 1 or week > 12:
            return

        phase = _get_phase(week)
        library = ACTION_LIBRARY.get(track, {}).get(phase, [])
        if not library:
            return

        journey = self.db.get_active_clarity_journey()
        if not journey:
            return

        started = datetime.fromisoformat(journey['started_at'])
        week_start = started + timedelta(weeks=week - 1)

        actions = []
        for day in range(7):
            action_template = library[day % len(library)]
            action_date = (week_start + timedelta(days=day)).date().isoformat()
            actions.append({
                'journey_id': journey_id,
                'week_number': week,
                'day_of_week': day,
                'action_type': action_template['type'],
                'action_title': action_template['title'],
                'action_description': action_template['desc'],
                'duration_min': action_template['duration'],
                'scheduled_date': action_date,
            })

        self.db.insert_clarity_actions(actions)

    def _compute_weekly_snapshot(self, journey_id: int, week: int, track: str):
        """Compute and store a weekly snapshot."""
        journey = self.db.get_active_clarity_journey()
        if not journey:
            return

        track_info = TRACKS.get(track, {})
        started = datetime.fromisoformat(journey['started_at'])
        week_start = (started + timedelta(weeks=week - 1)).date().isoformat()
        week_end = (started + timedelta(weeks=week)).date().isoformat()

        # Compute average scores for the week from daily_summaries
        primary_col = track_info.get('primary_col', 'avg_calm')
        secondary_col = track_info.get('secondary_col', 'avg_stress')

        with self.db.lock:
            cursor = self.db.conn.cursor()
            cursor.execute(
                f"SELECT AVG({primary_col}) as avg_p, AVG({secondary_col}) as avg_s "
                f"FROM daily_summaries WHERE date >= ? AND date < ?",
                (week_start, week_end)
            )
            row = cursor.fetchone()
            avg_target = round(row['avg_p'], 1) if row and row['avg_p'] is not None else None
            avg_secondary = round(row['avg_s'], 1) if row and row['avg_s'] is not None else None

        # Count completed actions for this week
        actions = self.db.get_clarity_actions(journey_id, week=week)
        actions_completed = sum(1 for a in actions if a.get('completed'))

        self.db.insert_clarity_weekly_snapshot(
            journey_id=journey_id,
            week=week,
            avg_target=avg_target,
            avg_secondary=avg_secondary,
            actions_completed=actions_completed,
            coach_text=None,
        )
