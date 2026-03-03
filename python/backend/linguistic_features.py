"""
Linguistic feature extraction from speech transcripts using local Whisper.

Privacy model: Audio → Whisper transcription → extract numerical features → discard transcript.
Raw transcript text is NEVER stored, logged, or persisted. Only derived numerical features are kept.

Phase 1 features (original):
- filler_rate: "um", "uh", "like", "you know" per minute (cognitive load/anxiety)
- hedging_score: hedging phrases per minute (uncertainty/anxiety)
- negative_sentiment: proportion of negative-valence words (affect)
- disfluency_rate: repetitions, false starts per minute (cognitive load)
- lexical_diversity: type-token ratio (decreases under stress)

Phase 2 features (expanded NLP):
- topic_work_score: work-related entity density (0-1)
- topic_relationships_score: relationship-related entity density (0-1)
- topic_health_score: health-related keyword density (0-1)
- pronoun_i_ratio: 1st-person singular pronoun ratio (depression marker, Rude et al. 2004)
- absolutist_ratio: absolutist/black-white thinking language ratio (Al-Mosaiwi & Johnstone 2018)
- sentiment_valence: overall valence (-1 to +1, ANEW-style)
- sentiment_arousal: overall arousal (0 to 1, ANEW-style)

Phase 3 features (semantic coherence):
- semantic_coherence: cosine similarity across speech chunks (sentence-transformers, 0-1)

Model: OpenAI Whisper 'base' (~140MB, MIT license, fully offline)
spaCy: en_core_web_sm (~12MB, MIT license, fully offline)
sentence-transformers: all-MiniLM-L6-v2 (~22MB, Apache 2.0, fully offline)
"""
import json
import logging
import os
import numpy as np
import re
from typing import Dict, Optional

logger = logging.getLogger('lucid.linguistic')

# Lazy-loaded models (loaded on first use)
_whisper_model = None
_whisper_load_failed = False
_spacy_nlp = None
_spacy_load_failed = False
_sentence_model = None
_sentence_model_load_failed = False

# Load lexicons at module import (small files, fast)
_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def _load_json_lexicon(filename: str) -> dict:
    try:
        path = os.path.join(_DATA_DIR, filename)
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load lexicon {filename}: {e}")
    return {}

_absolutist_data = _load_json_lexicon('absolutist_lexicon.json')
ABSOLUTIST_WORDS = frozenset(_absolutist_data.get('words', []))

_anew_data = _load_json_lexicon('anew_valence_arousal.json')
ANEW_LEXICON = _anew_data.get('words', {})  # word -> [valence, arousal]

# Simple negative sentiment lexicon (high-frequency negative words)
NEGATIVE_WORDS = frozenset([
    'angry', 'annoyed', 'anxious', 'awful', 'bad', 'boring', 'broken',
    "can't", 'confused', 'crazy', 'depressed', 'difficult', 'disappointed',
    'disgusting', 'dreadful', 'exhausted', 'fail', 'failed', 'failing',
    'frustrated', 'hate', 'horrible', 'hurt', 'impossible', 'irritated',
    'lonely', 'lost', 'miserable', 'nervous', 'never', 'nothing',
    'overwhelmed', 'painful', 'problem', 'sad', 'scared', 'sick',
    'stressed', 'struggle', 'struggling', 'stupid', 'terrible', 'tired',
    'ugly', 'unhappy', 'upset', 'useless', 'worried', 'worse', 'worst',
    'wrong',
])

# Filler words/phrases
FILLERS = frozenset(['um', 'uh', 'erm', 'hmm', 'hm', 'ah'])
FILLER_PHRASES = ['you know', 'i mean', 'kind of', 'sort of']

# Hedging phrases (uncertainty markers)
HEDGING_PHRASES = [
    'i think', 'i guess', 'i suppose', 'maybe', 'perhaps', 'probably',
    'sort of', 'kind of', 'like', 'i feel like', 'it seems',
    'not sure', 'not certain', 'might be', 'could be',
]

# 1st-person singular pronouns (Rude et al. 2004 depression marker)
PRONOUNS_I = frozenset(['i', 'me', 'my', 'myself', 'mine'])

# Work-related keywords for topic detection (fallback when spaCy unavailable)
WORK_KEYWORDS = frozenset([
    'meeting', 'deadline', 'project', 'work', 'boss', 'manager', 'team',
    'client', 'report', 'email', 'office', 'job', 'career', 'salary',
    'promotion', 'review', 'task', 'schedule', 'presentation', 'budget',
    'colleague', 'coworker', 'department', 'company', 'business',
])

HEALTH_KEYWORDS = frozenset([
    'doctor', 'hospital', 'sick', 'pain', 'health', 'medical', 'medicine',
    'symptom', 'treatment', 'therapy', 'medication', 'diagnosis', 'injury',
    'exercise', 'sleep', 'diet', 'weight', 'energy', 'tired', 'fatigue',
])

RELATIONSHIP_KEYWORDS = frozenset([
    'friend', 'family', 'partner', 'relationship', 'love', 'marriage',
    'boyfriend', 'girlfriend', 'husband', 'wife', 'parent', 'child',
    'mother', 'father', 'brother', 'sister', 'son', 'daughter',
    'argue', 'fight', 'conflict', 'support', 'together', 'lonely',
])


def _load_whisper():
    """Lazy-load Whisper model on first use."""
    global _whisper_model, _whisper_load_failed

    if _whisper_load_failed:
        return None
    if _whisper_model is not None:
        return _whisper_model

    try:
        import whisper
        logger.info("Loading Whisper 'base' model (first use)...")
        _whisper_model = whisper.load_model('base')
        logger.info("Whisper model loaded successfully")
        return _whisper_model
    except ImportError:
        logger.warning("openai-whisper not installed — linguistic features disabled")
        _whisper_load_failed = True
        return None
    except Exception as e:
        logger.error(f"Failed to load Whisper model: {e}")
        _whisper_load_failed = True
        return None


def _load_spacy():
    """Lazy-load spaCy en_core_web_sm on first use."""
    global _spacy_nlp, _spacy_load_failed

    if _spacy_load_failed:
        return None
    if _spacy_nlp is not None:
        return _spacy_nlp

    try:
        import spacy
        logger.info("Loading spaCy en_core_web_sm (first use)...")
        _spacy_nlp = spacy.load('en_core_web_sm')
        logger.info("spaCy model loaded successfully")
        return _spacy_nlp
    except ImportError:
        logger.warning("spacy not installed — topic NER disabled")
        _spacy_load_failed = True
        return None
    except OSError:
        logger.warning("spaCy en_core_web_sm not found — topic NER disabled. Run: python -m spacy download en_core_web_sm")
        _spacy_load_failed = True
        return None
    except Exception as e:
        logger.error(f"Failed to load spaCy model: {e}")
        _spacy_load_failed = True
        return None


def _load_sentence_model():
    """Lazy-load sentence-transformers all-MiniLM-L6-v2 on first use."""
    global _sentence_model, _sentence_model_load_failed

    if _sentence_model_load_failed:
        return None
    if _sentence_model is not None:
        return _sentence_model

    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading sentence-transformers all-MiniLM-L6-v2 (first use)...")
        _sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Sentence transformer loaded successfully")
        return _sentence_model
    except ImportError:
        logger.warning("sentence-transformers not installed — semantic coherence disabled")
        _sentence_model_load_failed = True
        return None
    except Exception as e:
        logger.error(f"Failed to load sentence transformer: {e}")
        _sentence_model_load_failed = True
        return None


def extract_linguistic_features(audio: np.ndarray, sample_rate: int = 16000,
                                  enhanced: bool = True) -> Dict[str, float]:
    """Extract linguistic features from audio using Whisper transcription.

    Args:
        audio: numpy array of audio samples (float32, mono)
        sample_rate: audio sample rate (Whisper expects 16kHz)
        enhanced: if True, run Phase 2 NLP features (NER, pronoun, absolutist, valence/arousal, coherence)

    Returns:
        Dict with all linguistic features (numerical only, no text stored).
    """
    model = _load_whisper()
    if model is None:
        return _get_zero_features()

    try:
        audio = audio.astype(np.float32)
        duration_min = len(audio) / sample_rate / 60.0

        if duration_min < 0.1:  # Less than 6 seconds
            return _get_zero_features()

        # Transcribe (Whisper handles resampling internally if needed)
        result = model.transcribe(
            audio,
            language='en',
            fp16=False,  # CPU-safe
        )
        transcript = result.get('text', '').strip()

        if not transcript:
            return _get_zero_features()

        # Phase 1: base features
        features = {
            'filler_rate': _count_fillers(transcript, duration_min),
            'hedging_score': _count_hedging(transcript, duration_min),
            'negative_sentiment': _compute_negative_sentiment(transcript),
            'disfluency_rate': _count_disfluencies(transcript, duration_min),
            'lexical_diversity': _compute_lexical_diversity(transcript),
        }

        if enhanced:
            # Phase 2: expanded NLP features
            topic_scores = _compute_topic_scores(transcript)
            features.update(topic_scores)

            features['pronoun_i_ratio'] = _compute_pronoun_i_ratio(transcript)
            features['absolutist_ratio'] = _compute_absolutist_ratio(transcript)

            valence, arousal = _compute_valence_arousal(transcript)
            features['sentiment_valence'] = valence
            features['sentiment_arousal'] = arousal

            # Phase 3: semantic coherence (only for longer transcripts)
            words = transcript.split()
            if len(words) >= 50:
                features['semantic_coherence'] = _compute_semantic_coherence(transcript)
            else:
                features['semantic_coherence'] = None  # Not enough text
        else:
            # Phase 2 zeros when enhanced is off
            features.update(_get_enhanced_zeros())

        logger.info(
            f"Linguistic features: fillers={features['filler_rate']:.1f}/min, "
            f"hedging={features['hedging_score']:.1f}/min, "
            f"neg_sent={features['negative_sentiment']:.2f}, "
            f"lex_div={features['lexical_diversity']:.2f}, "
            f"pronoun_i={features.get('pronoun_i_ratio', 0):.3f}, "
            f"absolutist={features.get('absolutist_ratio', 0):.3f}, "
            f"valence={features.get('sentiment_valence', 0):.2f}, "
            f"arousal={features.get('sentiment_arousal', 0):.2f}"
        )

        # PRIVACY: transcript is discarded here — only numerical features returned
        del transcript, result

        return features

    except Exception as e:
        logger.error(f"Linguistic feature extraction failed: {e}")
        return _get_zero_features()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: Base feature extractors
# ─────────────────────────────────────────────────────────────────────────────

def _count_fillers(transcript: str, duration_min: float) -> float:
    """Count filler words and phrases per minute."""
    text_lower = transcript.lower()
    count = 0

    words = text_lower.split()
    for word in words:
        clean = re.sub(r"[^\w']", '', word)
        if clean in FILLERS:
            count += 1

    for phrase in FILLER_PHRASES:
        count += text_lower.count(phrase)

    return count / max(0.1, duration_min)


def _count_hedging(transcript: str, duration_min: float) -> float:
    """Count hedging phrases per minute."""
    text_lower = transcript.lower()
    count = 0
    for phrase in HEDGING_PHRASES:
        count += text_lower.count(phrase)
    return count / max(0.1, duration_min)


def _compute_negative_sentiment(transcript: str) -> float:
    """Compute ratio of negative-valence words to total words."""
    words = re.findall(r"[a-z']+", transcript.lower())
    if len(words) == 0:
        return 0.0
    neg_count = sum(1 for w in words if w in NEGATIVE_WORDS)
    return neg_count / len(words)


def _count_disfluencies(transcript: str, duration_min: float) -> float:
    """Count speech disfluencies (repetitions, false starts) per minute."""
    words = transcript.lower().split()
    if len(words) < 2:
        return 0.0

    count = 0
    for i in range(1, len(words)):
        if words[i] == words[i - 1]:
            count += 1
        elif (len(words[i]) >= 3 and len(words[i - 1]) >= 3
              and words[i][:3] == words[i - 1][:3] and words[i] != words[i - 1]):
            count += 0.5

    return count / max(0.1, duration_min)


def _compute_lexical_diversity(transcript: str) -> float:
    """Compute type-token ratio (unique words / total words)."""
    words = re.findall(r"[a-z']+", transcript.lower())
    if len(words) == 0:
        return 0.0
    return len(set(words)) / len(words)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: Enhanced NLP extractors
# ─────────────────────────────────────────────────────────────────────────────

def _compute_topic_scores(transcript: str) -> Dict[str, float]:
    """Compute topic attribution scores using spaCy NER + keyword fallback.

    Returns dict with topic_work_score, topic_relationships_score, topic_health_score (0-1).
    """
    text_lower = transcript.lower()
    words = re.findall(r"[a-z]+", text_lower)
    total_words = max(1, len(words))

    nlp = _load_spacy()

    if nlp is not None:
        try:
            doc = nlp(transcript[:5000])  # Limit to 5000 chars to keep fast

            work_count = 0
            relationship_count = 0
            health_count = 0

            for ent in doc.ents:
                ent_lower = ent.text.lower()
                if ent.label_ in ('ORG', 'PRODUCT', 'MONEY', 'PERCENT', 'DATE', 'TIME'):
                    work_count += 1
                elif ent.label_ == 'PERSON':
                    relationship_count += 1
                # GPE (place) could be work or personal — neutral

            # Add keyword matches on top of NER
            work_kw = sum(1 for w in words if w in WORK_KEYWORDS)
            health_kw = sum(1 for w in words if w in HEALTH_KEYWORDS)
            rel_kw = sum(1 for w in words if w in RELATIONSHIP_KEYWORDS)

            work_count += work_kw
            relationship_count += rel_kw
            health_count += health_kw

            total = max(1, work_count + relationship_count + health_count)
            return {
                'topic_work_score': min(1.0, work_count / total_words * 5),
                'topic_relationships_score': min(1.0, relationship_count / total_words * 5),
                'topic_health_score': min(1.0, health_count / total_words * 5),
            }
        except Exception as e:
            logger.warning(f"spaCy NER failed, using keyword fallback: {e}")

    # Keyword-only fallback (no spaCy)
    work_count = sum(1 for w in words if w in WORK_KEYWORDS)
    health_count = sum(1 for w in words if w in HEALTH_KEYWORDS)
    rel_count = sum(1 for w in words if w in RELATIONSHIP_KEYWORDS)

    return {
        'topic_work_score': min(1.0, work_count / total_words * 5),
        'topic_relationships_score': min(1.0, rel_count / total_words * 5),
        'topic_health_score': min(1.0, health_count / total_words * 5),
    }


def _compute_pronoun_i_ratio(transcript: str) -> float:
    """Compute 1st-person singular pronoun ratio (Rude et al. 2004 depression marker).

    Higher self-focus (more 'I', 'me', 'my') associated with depression and rumination.
    """
    words = re.findall(r"[a-z']+", transcript.lower())
    if not words:
        return 0.0
    i_count = sum(1 for w in words if w in PRONOUNS_I)
    return i_count / len(words)


def _compute_absolutist_ratio(transcript: str) -> float:
    """Compute absolutist/black-white thinking language ratio (Al-Mosaiwi & Johnstone 2018).

    Higher absolutist language associated with anxiety and depression.
    """
    text_lower = transcript.lower()
    words = re.findall(r"[a-z]+", text_lower)
    if not words:
        return 0.0

    count = 0
    for w in words:
        if w in ABSOLUTIST_WORDS:
            count += 1

    # Also check multi-word absolutist phrases
    for phrase in ['no one', 'nothing works', 'nothing helps', 'no one cares',
                   'no one understands', 'without fail', 'without exception', 'no matter what']:
        count += text_lower.count(phrase)

    return count / len(words)


def _compute_valence_arousal(transcript: str) -> tuple:
    """Compute sentiment valence and arousal from ANEW-style lexicon.

    Returns (valence, arousal):
    - valence: -1 (very negative) to +1 (very positive)
    - arousal: 0 (calm) to 1 (highly activated/excited)

    Enables fear (high arousal + negative valence) vs. sadness (low arousal + negative valence).
    """
    if not ANEW_LEXICON:
        return 0.0, 0.5  # Neutral defaults if lexicon missing

    words = re.findall(r"[a-z]+", transcript.lower())
    if not words:
        return 0.0, 0.5

    valences = []
    arousals = []

    for w in words:
        if w in ANEW_LEXICON:
            v, a = ANEW_LEXICON[w]
            valences.append(v)
            arousals.append(a)

    if not valences:
        return 0.0, 0.5

    valence = float(np.mean(valences))
    arousal = float(np.mean(arousals))

    return valence, arousal


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: Semantic coherence
# ─────────────────────────────────────────────────────────────────────────────

def _compute_semantic_coherence(transcript: str) -> Optional[float]:
    """Compute semantic coherence across speech chunks using sentence-transformers.

    Splits transcript into 3 chunks, computes embeddings, returns mean cosine
    similarity between adjacent chunks. Higher = more coherent/focused speech.
    Lower = fragmented thinking (potential alogia signal).

    Returns None if sentence-transformers unavailable or transcript too short.
    """
    model = _load_sentence_model()
    if model is None:
        return None

    try:
        words = transcript.split()
        if len(words) < 50:
            return None

        # Split into 3 roughly equal chunks
        chunk_size = len(words) // 3
        chunks = [
            ' '.join(words[:chunk_size]),
            ' '.join(words[chunk_size:2 * chunk_size]),
            ' '.join(words[2 * chunk_size:]),
        ]

        # Filter empty chunks
        chunks = [c for c in chunks if len(c.strip()) > 0]
        if len(chunks) < 2:
            return None

        embeddings = model.encode(chunks, convert_to_numpy=True)

        # Compute cosine similarities between adjacent chunks
        similarities = []
        for i in range(len(embeddings) - 1):
            a = embeddings[i]
            b = embeddings[i + 1]
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a > 0 and norm_b > 0:
                cos_sim = float(np.dot(a, b) / (norm_a * norm_b))
                similarities.append(cos_sim)

        if not similarities:
            return None

        # Map cosine similarity [-1,1] to coherence [0,1]
        raw = float(np.mean(similarities))
        coherence = (raw + 1.0) / 2.0
        return round(coherence, 4)

    except Exception as e:
        logger.error(f"Semantic coherence computation failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Zero-feature helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_enhanced_zeros() -> Dict[str, float]:
    """Zero values for Phase 2+ features."""
    return {
        'topic_work_score': 0.0,
        'topic_relationships_score': 0.0,
        'topic_health_score': 0.0,
        'pronoun_i_ratio': 0.0,
        'absolutist_ratio': 0.0,
        'sentiment_valence': 0.0,
        'sentiment_arousal': 0.0,
        'semantic_coherence': None,
    }


def _get_zero_features() -> Dict[str, float]:
    """Return zero features (for error cases or when Whisper is unavailable)."""
    features = {
        'filler_rate': 0.0,
        'hedging_score': 0.0,
        'negative_sentiment': 0.0,
        'disfluency_rate': 0.0,
        'lexical_diversity': 0.0,
    }
    features.update(_get_enhanced_zeros())
    return features
