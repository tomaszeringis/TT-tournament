import pytest
from tournament_platform.app.services.voice_vocab import VoiceVocabulary, TranscriptPostProcessor
from tournament_platform.app.services.voice.commands import parse as grammar_parse, VoiceIntent

@pytest.fixture
def processor():
    return TranscriptPostProcessor()

@pytest.mark.parametrize("input_text, expected_side", [
    ("Taškas kairė", "LEFT"),
    ("Taškas kairė.", "LEFT"),
    ("Taškas kairėje", "LEFT"),
    ("Taškas kairėje.", "LEFT"),
    ("Taškas kairi", "LEFT"),
    ("Taškas kairi.", "LEFT"),
    ("Taškas kairį", "LEFT"),
    ("Taškas kairį.", "LEFT"),
    ("taskas kaire", "LEFT"),
    ("taskas kaireje", "LEFT"),
    ("  Taškas   kairėje.  ", "LEFT"),
    
    ("Taškas dešinė", "RIGHT"),
    ("Taškas dešinė.", "RIGHT"),
    ("Taškas dešinėje", "RIGHT"),
    ("Taškas dešinėje.", "RIGHT"),
    ("taskas desine", "RIGHT"),
    ("taskas desineje", "RIGHT"),
    
    # Side-only (if supported)
    ("kairė", "LEFT"),
    ("kairėje", "LEFT"),
    ("kairi", "LEFT"),
    ("dešinė", "RIGHT"),
    ("dešinėje", "RIGHT"),
])
def test_lithuanian_normalization_matrix(processor, input_text, expected_side):
    # 1. Post-process (Normalization + LT->EN Alias)
    normalized = processor.process(input_text, language="lt")
    
    # 2. Parse with grammar
    result = grammar_parse(normalized)
    
    assert result.intent == VoiceIntent.SCORE_POINT, f"Failed to recognize SCORE_POINT for: {input_text} (normalized: {normalized})"
    assert result.target_side == expected_side, f"Wrong side for: {input_text} (normalized: {normalized}). Expected {expected_side}, got {result.target_side}"

@pytest.mark.parametrize("negative_input", [
    "Iškuštu ne likumė.",
    "šiandien kairėje žaidėjas",
    "dešinėje yra stalas",
    "taškas",
    "kažkas kairėje",
    "labas",
    "gerai",
])
def test_lithuanian_negative_cases(processor, negative_input):
    normalized = processor.process(negative_input, language="lt")
    result = grammar_parse(normalized)
    
    # Unless any of these are intended commands (none are according to requirements)
    assert result.intent == VoiceIntent.UNKNOWN or result.target_side is None, f"Should NOT score for: {negative_input} (normalized: {normalized})"

def test_punctuation_stripping(processor):
    # Test various punctuation variants
    variants = [
        "Taškas kairėje",
        "Taškas kairėje.",
        "Taškas kairėje!",
        "Taškas kairėje,",
    ]
    for v in variants:
        norm = processor.process(v, language="lt")
        # All should normalize to "point left" after alias expansion
        assert norm == "point left", f"Failed punctuation stripping/alias for: {v}"
        res = grammar_parse(norm)
        assert res.intent == VoiceIntent.SCORE_POINT
        assert res.target_side == "LEFT"
