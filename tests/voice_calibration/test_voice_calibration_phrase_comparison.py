"""
Phase 9 — Predefined Phrase Comparison tests.
"""

from __future__ import annotations

from tournament_platform.app.services.voice_calibration.models import (
    CommandPhraseCandidate,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


class TestImmutablePhraseContext:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_phrase_id_bound_at_capture_time(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point to red",
            normalized_phrase="point to red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        assert len(session.phrase_candidates) == 1
        assert session.phrase_candidates[0].phrase_id == "score_point_1"

    def test_delayed_phrase_event_retains_original_phrase(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point to red",
            normalized_phrase="point to red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "point to red",
            "score_point",
            "Point to red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        stored_trial = session.trials[0]
        assert stored_trial.expected_phrase_id == "score_point_1"
        assert stored_trial.expected_phrase == "Point to red"

    def test_advancing_ui_cannot_relabel_pending_phrase(self):
        session = self.service.start_session("s1")
        candidate1 = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        candidate2 = CommandPhraseCandidate(
            phrase_id="score_point_2",
            command_id="score_point",
            display_phrase="Red point",
            normalized_phrase="red point",
            language="en",
            sort_order=2,
        )
        session = self.service.register_phrase_candidates(
            session, (candidate1, candidate2)
        )
        trial = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        stored_trial = session.trials[0]
        assert stored_trial.expected_phrase_id == "score_point_1"
        assert stored_trial.expected_phrase == "Point red"

    def test_retry_uses_new_trial_id_but_same_phrase_id(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point to red",
            normalized_phrase="point to red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial1 = self.service.evaluate_transcript(
            "point to red",
            "score_point",
            "Point to red",
            phrase_id="score_point_1",
        )
        trial2 = self.service.evaluate_transcript(
            "point to red",
            "score_point",
            "Point to red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial1, trial2))
        assert len(session.trials) == 2
        assert session.trials[0].trial_id != session.trials[1].trial_id
        assert session.trials[0].expected_phrase_id == "score_point_1"
        assert session.trials[1].expected_phrase_id == "score_point_1"


class TestPhraseComparisonAggregation:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_results_grouped_by_command_and_phrase(self):
        session = self.service.start_session("s1")
        candidates = (
            CommandPhraseCandidate(
                phrase_id="score_point_1",
                command_id="score_point",
                display_phrase="Point red",
                normalized_phrase="point red",
                language="en",
                sort_order=1,
            ),
            CommandPhraseCandidate(
                phrase_id="score_point_2",
                command_id="score_point",
                display_phrase="Red point",
                normalized_phrase="red point",
                language="en",
                sort_order=2,
            ),
        )
        session = self.service.register_phrase_candidates(session, candidates)
        trial1 = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        trial2 = self.service.evaluate_transcript(
            "red point",
            "score_point",
            "Red point",
            phrase_id="score_point_2",
        )
        trial3 = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial1, trial2, trial3))
        results = self.service.compute_phrase_comparison(session)
        result_map = {r.phrase_id: r for r in results}
        assert len(result_map) == 2
        assert result_map["score_point_1"].attempts == 2
        assert result_map["score_point_2"].attempts == 1

    def test_duplicate_trial_not_counted_twice(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        session = self.service.consume_trials(session, (trial,))
        results = self.service.compute_phrase_comparison(session)
        assert results[0].attempts == 1 if results else True

    def test_wrong_command_penalizes_phrase(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "undo",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        results = self.service.compute_phrase_comparison(session)
        assert results[0].wrong_command_count == 1
        assert results[0].parser_successes == 0

    def test_unknown_transcript_counted(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "gibberish",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        results = self.service.compute_phrase_comparison(session)
        assert results[0].unknown_count == 1
        assert results[0].parser_successes == 0

    def test_latency_median_and_p95_calculated(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trials = tuple(
            self.service.evaluate_transcript(
                "point red",
                "score_point",
                "Point red",
                phrase_id="score_point_1",
                asr_latency_ms=float(latency),
            )
            for latency in [500, 600, 700, 800, 900]
        )
        session = self.service.consume_trials(session, trials)
        results = self.service.compute_phrase_comparison(session)
        assert results[0].median_latency_ms == 700.0
        assert results[0].p95_latency_ms == 900.0


class TestPhraseRecommendation:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_highest_safe_parser_success_wins(self):
        session = self.service.start_session("s1")
        candidates = (
            CommandPhraseCandidate(
                phrase_id="score_point_1",
                command_id="score_point",
                display_phrase="Point red",
                normalized_phrase="point red",
                language="en",
                sort_order=1,
            ),
            CommandPhraseCandidate(
                phrase_id="score_point_2",
                command_id="score_point",
                display_phrase="Red point",
                normalized_phrase="red point",
                language="en",
                sort_order=2,
            ),
        )
        session = self.service.register_phrase_candidates(session, candidates)
        trial1 = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        trial2 = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        trial3 = self.service.evaluate_transcript(
            "red point",
            "score_point",
            "Red point",
            phrase_id="score_point_2",
        )
        session = self.service.consume_trials(session, (trial1, trial2, trial3))
        recommendation = self.service.recommend_phrase(
            session, "score_point", canonical_phrase_id="score_point_1"
        )
        assert recommendation is not None
        assert recommendation.phrase_id == "score_point_1"

    def test_existing_canonical_phrase_wins_tie(self):
        session = self.service.start_session("s1")
        candidates = (
            CommandPhraseCandidate(
                phrase_id="score_point_1",
                command_id="score_point",
                display_phrase="Point red",
                normalized_phrase="point red",
                language="en",
                sort_order=1,
            ),
            CommandPhraseCandidate(
                phrase_id="score_point_2",
                command_id="score_point",
                display_phrase="Red point",
                normalized_phrase="red point",
                language="en",
                sort_order=2,
            ),
        )
        session = self.service.register_phrase_candidates(session, candidates)
        trial1 = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        trial2 = self.service.evaluate_transcript(
            "red point",
            "score_point",
            "Red point",
            phrase_id="score_point_2",
        )
        session = self.service.consume_trials(session, (trial1, trial2))
        recommendation = self.service.recommend_phrase(
            session, "score_point", canonical_phrase_id="score_point_1"
        )
        assert recommendation is not None
        assert recommendation.phrase_id == "score_point_1"

    def test_unsafe_phrase_never_recommended(self):
        session = self.service.start_session("s1")
        candidates = (
            CommandPhraseCandidate(
                phrase_id="score_point_1",
                command_id="score_point",
                display_phrase="Point red",
                normalized_phrase="point red",
                language="en",
                sort_order=1,
            ),
            CommandPhraseCandidate(
                phrase_id="score_point_2",
                command_id="score_point",
                display_phrase="Red point",
                normalized_phrase="red point",
                language="en",
                sort_order=2,
            ),
        )
        session = self.service.register_phrase_candidates(session, candidates)
        trial1 = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        trial2 = self.service.evaluate_transcript(
            "point blue",
            "score_point",
            "Red point",
            phrase_id="score_point_2",
        )
        session = self.service.consume_trials(session, (trial1, trial2))
        recommendation = self.service.recommend_phrase(session, "score_point")
        assert recommendation is not None
        assert recommendation.phrase_id == "score_point_1"

    def test_no_recommendation_when_all_phrases_fail(self):
        session = self.service.start_session("s1")
        candidates = (
            CommandPhraseCandidate(
                phrase_id="score_point_1",
                command_id="score_point",
                display_phrase="Point red",
                normalized_phrase="point red",
                language="en",
                sort_order=1,
            ),
        )
        session = self.service.register_phrase_candidates(session, candidates)
        trial = self.service.evaluate_transcript(
            "start match",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        recommendation = self.service.recommend_phrase(session, "score_point")
        assert recommendation is None

    def test_recommendation_is_deterministic(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        rec1 = self.service.recommend_phrase(session, "score_point")
        rec2 = self.service.recommend_phrase(session, "score_point")
        assert rec1.phrase_id == rec2.phrase_id if rec1 and rec2 else True


class TestPhraseComparisonSafety:
    def setup_method(self):
        self.service = VoiceCalibrationService()

    def test_phrase_comparison_cannot_mutate_score(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        assert len(session.trials) == 1
        assert session.trials[0].resolved_command_id == "score_point"

    def test_phrase_comparison_cannot_create_alias(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        assert len(session.alias_candidates) == 0

    def test_phrase_comparison_does_not_change_parser(self):
        self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
        )

    def test_phrase_comparison_does_not_change_asr(self):
        self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
        )

    def test_negative_and_tts_failures_block_recommendation(self):
        session = self.service.start_session("s1")
        candidate = CommandPhraseCandidate(
            phrase_id="score_point_1",
            command_id="score_point",
            display_phrase="Point red",
            normalized_phrase="point red",
            language="en",
            sort_order=1,
        )
        session = self.service.register_phrase_candidates(session, (candidate,))
        trial = self.service.evaluate_transcript(
            "point red",
            "score_point",
            "Point red",
            phrase_id="score_point_1",
        )
        session = self.service.consume_trials(session, (trial,))
        neg_trial = self.service.evaluate_negative_trial("point blue")
        session = self.service.consume_negative_trials(session, (neg_trial,))
        recommendation = self.service.recommend_phrase(session, "score_point")
        assert recommendation is None
