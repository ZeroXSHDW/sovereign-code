"""Tests for domain routing: classification, protocols, and verdict parsing."""

from __future__ import annotations

from sovereign_code.domains import (
    DEFINITIVE_PROTOCOL,
    DOMAINS,
    FORCE_VERDICT,
    classify,
    confidence,
    system_prompt,
    verdict,
)


def test_general_is_the_fallback():
    assert [domain.key for domain in classify("hello there")] == ["general"]


def test_legal_prompt_routes_to_legal():
    picked = classify("Does this supplier contract breach the GDPR privacy policy?")
    assert picked[0].key == "legal"


def test_security_prompt_routes_to_security():
    picked = classify("Is this endpoint vulnerable to SQL injection and XSS?")
    assert picked[0].key == "security"


def test_ethics_prompt_routes_to_ethics():
    picked = classify("Is it ethical to collect this personal data without consent?")
    assert picked[0].key == "ethics"


def test_code_prompt_routes_to_code():
    picked = classify("Refactor this Python function and add a regression test")
    assert picked[0].key == "code"


def test_keywords_match_whole_words():
    """A substring match made 'decode' a code hit and 'latest' a test hit."""
    assert classify("please decode this barcode")[0].key == "general"
    assert classify("the latest release of curl")[0].key == "general"
    assert classify("a rapid turnaround")[0].key == "general"


def test_stems_still_match_inflections():
    assert classify("is this contract compliant?")[0].key == "legal"
    assert classify("what are the ethics here")[0].key == "ethics"
    assert classify("check the vulnerability report")[0].key == "security"


def test_system_prompt_carries_the_protocol():
    domain = DOMAINS["legal"]
    prompt = system_prompt(domain)
    assert domain.system in prompt
    assert "VERDICT:" in prompt
    assert "CONFIDENCE:" in DEFINITIVE_PROTOCOL


def test_verdict_is_read_from_the_last_block():
    text = "VERDICT: first try\nmore text\nVERDICT: the real one\n"
    assert verdict(text) == "the real one"
    assert verdict("no verdict here") is None
    assert verdict("**VERDICT:** bold answer") == "bold answer"


def test_confidence_is_read():
    assert confidence("CONFIDENCE: high - the clause is explicit") is not None
    assert confidence("nothing") is None


def test_force_verdict_prompt_exists():
    assert "VERDICT" in FORCE_VERDICT


def test_every_domain_has_a_usable_shape():
    for key, domain in DOMAINS.items():
        assert domain.key == key
        assert domain.alias and domain.fallback
        assert domain.system
