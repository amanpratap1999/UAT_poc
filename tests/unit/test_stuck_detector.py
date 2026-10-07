import pytest
from agent.cognition.stuck_detector import StuckDetector, StuckResult

def test_no_actions_recorded():
    detector = StuckDetector()
    result = detector.check()
    assert not result.is_stuck

def test_two_different_actions():
    detector = StuckDetector()
    detector.record("click", "button")
    detector.record("type", "input")
    result = detector.check()
    assert not result.is_stuck

def test_same_action_repeated_default_threshold():
    detector = StuckDetector()
    detector.record("click", "button")
    detector.record("click", "button")
    result = detector.check()
    assert result.is_stuck
    assert result.repetition_count == 2
    assert result.repeated_action == "click: button"

def test_same_action_repeated_with_different_action_in_between():
    detector = StuckDetector()
    detector.record("click", "button")
    detector.record("type", "input")
    detector.record("click", "button")
    result = detector.check()
    assert not result.is_stuck

def test_reset_clears_history():
    detector = StuckDetector()
    detector.record("click", "button")
    detector.record("click", "button")
    assert detector.check().is_stuck
    detector.reset()
    assert not detector.check().is_stuck

def test_custom_max_repeats_threshold():
    detector = StuckDetector(max_repeats=3)
    detector.record("click", "button")
    detector.record("click", "button")
    assert not detector.check().is_stuck
    detector.record("click", "button")
    result = detector.check()
    assert result.is_stuck
    assert result.repetition_count == 3

def test_case_insensitive_comparison():
    detector = StuckDetector()
    detector.record("CLICK", "Button")
    detector.record("click", "button")
    assert detector.check().is_stuck
