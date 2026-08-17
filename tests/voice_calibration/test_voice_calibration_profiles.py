"""
Phase 12 — Per-user calibration profile persistence tests.
"""

from __future__ import annotations

import time

import pytest

from tournament_platform.app.services.voice_calibration.models import (
    AcousticSummarySnapshot,
    AliasCandidateStatus,
    AliasConfirmationCandidate,
    CalibrationProfileIdentity,
    CalibrationProfileStatus,
    CalibrationSession,
    CommandTrial,
    NegativeSpeechSnapshot,
    TtsEchoSnapshot,
    TrialClassification,
    VerificationMetadata,
    VoiceCalibrationProfile,
)
from tournament_platform.app.services.voice_calibration.profile_store import (
    InMemoryCalibrationProfileStore,
)
from tournament_platform.app.services.voice_calibration.service import (
    VoiceCalibrationService,
)


def _make_session(session_id: str = "s1") -> CalibrationSession:
    return CalibrationSession(
        session_id=session_id,
        created_at=time.time(),
        commands=("score_point",),
        attempts_per_command=1,
        current_command_index=0,
    )


def _make_trial(trial_id: str = "t1") -> CommandTrial:
    return CommandTrial(
        trial_id=trial_id,
        expected_command_id="score_point",
        expected_phrase="point red",
        raw_transcript="point read",
        normalized_transcript="point read",
        resolved_command_id="score_point",
        classification=TrialClassification.EXACT,
        parser_confidence=0.9,
        rejection_reason=None,
    )


class TestCalibrationProfileIdentity:
    def test_profile_identity_equality(self):
        identity_a = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        identity_b = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        assert identity_a == identity_b

    def test_profile_identity_inequality(self):
        identity_a = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        identity_b = CalibrationProfileIdentity(
            language="fr",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        assert identity_a != identity_b


class TestCalibrationProfileStore:
    def test_in_memory_store_save_and_load(self):
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        profile = VoiceCalibrationProfile(
            profile_id="profile-1",
            owner_id="user-1",
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=("point red",),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        store.save("user-1", profile)
        loaded = store.load("user-1", identity)
        assert loaded is not None
        assert loaded.profile_id == "profile-1"

    def test_in_memory_store_delete(self):
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        profile = VoiceCalibrationProfile(
            profile_id="profile-1",
            owner_id="user-1",
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=(),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        store.save("user-1", profile)
        store.delete("user-1", "profile-1")
        assert store.load("user-1", identity) is None

    def test_in_memory_store_clear(self):
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        profile = VoiceCalibrationProfile(
            profile_id="profile-1",
            owner_id="user-1",
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=(),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        store.save("user-1", profile)
        store.clear()
        assert store.load("user-1", identity) is None

    def test_owner_cannot_load_other_users_profile(self):
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        profile = VoiceCalibrationProfile(
            profile_id="profile-1",
            owner_id="user-1",
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=(),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        store.save("user-1", profile)
        assert store.load("user-2", identity) is None

    def test_owner_cannot_delete_other_users_profile(self):
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        profile = VoiceCalibrationProfile(
            profile_id="profile-1",
            owner_id="user-1",
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=(),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        store.save("user-1", profile)
        with pytest.raises(ValueError, match="owner_id mismatch"):
            store.delete("user-2", "profile-1")
        assert store.load("user-1", identity) is not None

    def test_save_owner_mismatch_raises(self):
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        profile = VoiceCalibrationProfile(
            profile_id="profile-1",
            owner_id="user-1",
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=(),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        with pytest.raises(ValueError, match="owner_id mismatch"):
            store.save("user-2", profile)


class TestCalibrationProfileService:
    def test_build_profile_identity(self):
        service = VoiceCalibrationService()
        session = _make_session()
        identity = service.build_profile_identity(
            session=session,
            asr_provider="faster_whisper",
            asr_model="tiny.en",
        )
        assert identity.language == "en"
        assert identity.asr_provider == "faster_whisper"
        assert identity.asr_model == "tiny.en"
        assert identity.profile_schema_version == 1

    def test_build_calibration_profile(self):
        service = VoiceCalibrationService()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
            preferred_phrases=("point red",),
        )
        assert profile.status == CalibrationProfileStatus.VERIFIED
        assert profile.owner_id == "user-1"
        assert profile.preferred_phrases == ("point red",)
        assert profile.identity == identity

    def test_verify_profile_identity_match(self):
        service = VoiceCalibrationService()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        status, reasons = service.verify_profile_identity(profile, identity)
        assert status == CalibrationProfileStatus.VERIFIED
        assert reasons == ()

    def test_verify_profile_identity_mismatch(self):
        service = VoiceCalibrationService()
        session = _make_session()
        identity_a = service.build_profile_identity(session=session)
        identity_b = CalibrationProfileIdentity(
            language="fr",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type="int8",
            microphone_device_hash="mic-1",
            sample_rate_hz=16000,
        )
        profile = service.build_calibration_profile(
            session=session,
            identity=identity_a,
            owner_id="user-1",
        )
        status, reasons = service.verify_profile_identity(profile, identity_b)
        assert status == CalibrationProfileStatus.NEEDS_VERIFICATION
        assert "language_mismatch" in reasons

    def test_save_and_load_profile_via_service(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        loaded = service.load_profile(store, "user-1", identity)
        assert loaded is not None
        assert loaded.profile_id == profile.profile_id

    def test_delete_profile_via_service(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        service.delete_profile(store, "user-1", profile.profile_id)
        assert service.load_profile(store, "user-1", identity) is None

    def test_profile_includes_confirmed_aliases(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial()
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        session = service.confirm_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        assert len(profile.confirmed_aliases) == 1
        assert profile.confirmed_aliases[0].status == AliasCandidateStatus.CONFIRMED

    def test_activate_profile_returns_profile_when_identity_matches(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        active = service.activate_profile(store, "user-1", identity)
        assert active is not None
        assert active.profile_id == profile.profile_id

    def test_activate_profile_returns_none_when_not_found(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type=None,
            microphone_device_hash=None,
            sample_rate_hz=None,
        )
        active = service.activate_profile(store, "user-1", identity)
        assert active is None

    def test_activate_profile_returns_none_when_identity_mismatch(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity_a = service.build_profile_identity(session=session)
        identity_b = CalibrationProfileIdentity(
            language="fr",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type=None,
            microphone_device_hash=None,
            sample_rate_hz=None,
        )
        profile = service.build_calibration_profile(
            session=session,
            identity=identity_a,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        active = service.activate_profile(store, "user-1", identity_b)
        assert active is None

    def test_deactivate_profile_removes_profile(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        service.deactivate_profile(store, "user-1", profile.profile_id)
        assert service.load_profile(store, "user-1", identity) is None

    def test_store_owner_isolation(self):
        store = InMemoryCalibrationProfileStore()
        identity_a = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type=None,
            microphone_device_hash=None,
            sample_rate_hz=None,
        )
        identity_b = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type=None,
            microphone_device_hash=None,
            sample_rate_hz=None,
        )
        profile_a = VoiceCalibrationProfile(
            profile_id="profile-a",
            owner_id="user-1",
            identity=identity_a,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=(),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        store.save("user-1", profile_a)
        assert store.load("user-1", identity_a) is not None
        assert store.load("user-2", identity_a) is None
        assert store.load("user-2", identity_b) is None

    def test_profile_owner_mismatch_rejected_by_store(self):
        store = InMemoryCalibrationProfileStore()
        identity = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type=None,
            microphone_device_hash=None,
            sample_rate_hz=None,
        )
        profile = VoiceCalibrationProfile(
            profile_id="profile-1",
            owner_id="user-1",
            identity=identity,
            status=CalibrationProfileStatus.VERIFIED,
            preferred_phrases=(),
            confirmed_aliases=(),
            selected_asr_config=None,
            acoustic_summary=AcousticSummarySnapshot(),
            negative_speech_outcome=NegativeSpeechSnapshot(),
            tts_echo_outcome=TtsEchoSnapshot(),
            verification_metadata=VerificationMetadata(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        with pytest.raises(ValueError, match="owner_id mismatch"):
            store.save("user-2", profile)

    def test_only_confirmed_aliases_are_persisted(self):
        service = VoiceCalibrationService()
        session = _make_session()
        trial = _make_trial()
        session = service.consume_trials(session, (trial,))
        candidates = service.compute_alias_candidates(session=session)
        session = service.confirm_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        session = service.reject_alias(
            session=session, candidate_id=candidates[0].candidate_id
        )
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        assert len(profile.confirmed_aliases) == 0

    def test_negative_or_tts_alias_never_persisted(self):
        service = VoiceCalibrationService()
        session = _make_session()
        neg_trial = service.evaluate_negative_trial("point blue")
        session = service.consume_negative_trials(session, (neg_trial,))
        candidates = service.compute_alias_candidates(session=session)
        assert len(candidates) == 0

    def test_loading_profile_does_not_activate_profile(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        loaded = service.load_profile(store, "user-1", identity)
        assert loaded is not None
        assert loaded.status == CalibrationProfileStatus.VERIFIED

    def test_profile_requires_explicit_session_activation(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        active = service.activate_profile(store, "user-1", identity)
        assert active is not None
        assert active.profile_id == profile.profile_id

    def test_deactivation_restores_defaults(self):
        service = VoiceCalibrationService()
        store = InMemoryCalibrationProfileStore()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        service.save_profile(store, "user-1", profile)
        service.deactivate_profile(store, "user-1", profile.profile_id)
        assert service.load_profile(store, "user-1", identity) is None

    def test_profile_schema_mismatch_requires_verification(self):
        service = VoiceCalibrationService()
        session = _make_session()
        identity_a = service.build_profile_identity(session=session)
        identity_b = CalibrationProfileIdentity(
            language="en",
            asr_provider="faster_whisper",
            asr_model="tiny.en",
            compute_type=None,
            microphone_device_hash=None,
            sample_rate_hz=None,
            profile_schema_version=2,
        )
        profile = service.build_calibration_profile(
            session=session,
            identity=identity_a,
            owner_id="user-1",
        )
        status, reasons = service.verify_profile_identity(profile, identity_b)
        assert status == CalibrationProfileStatus.NEEDS_VERIFICATION
        assert "schema_version_mismatch" in reasons

    def test_no_raw_audio_in_serialized_profile(self):
        service = VoiceCalibrationService()
        session = _make_session()
        identity = service.build_profile_identity(session=session)
        profile = service.build_calibration_profile(
            session=session,
            identity=identity,
            owner_id="user-1",
        )
        serialized = profile.__dict__
        assert "audio_bytes" not in serialized
        assert "pcm" not in str(serialized).lower()
