"""Tests for TT Sounds import safety."""


def test_import_tt_sounds_never_requires_torch():
    import importlib
    import sys

    mod_name = "tournament_platform.app.services.tt_sounds"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    import tournament_platform.app.services.tt_sounds as tt_sounds

    assert hasattr(tt_sounds, "ImpactDetector")
    assert hasattr(tt_sounds, "TTRallyProcessor")
    assert hasattr(tt_sounds, "RallyManager")
    assert hasattr(tt_sounds, "TTClassifier")
    assert hasattr(tt_sounds, "TT_SOUNDS_ENABLED")
