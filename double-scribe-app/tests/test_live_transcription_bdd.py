"""
Step definitions for features/live_transcription.feature -- encodes the exact
reported symptoms ("doesn't show live", "takes forever to stop") as executable
acceptance specs, using the same LiveSessionHarness as test_qa_metrics.py so
the audio/model layer is faked and these run fast without a GPU or a mic.
"""
from pytest_bdd import scenarios, given, when, then, parsers

from support import LiveSessionHarness

scenarios("features/live_transcription.feature")


@given(parsers.parse("a live session where transcription is effectively instant"),
       target_fixture="harness")
def harness_fast(monkeypatch, tmp_path):
    return LiveSessionHarness(monkeypatch, tmp_path, inference_delay=0.0)


@given(parsers.parse("a live session where transcription takes {delay:g} seconds per phrase"),
       target_fixture="harness")
def harness_slow(monkeypatch, tmp_path, delay):
    return LiveSessionHarness(monkeypatch, tmp_path, inference_delay=delay)


@when(parsers.parse("{count:d} phrases are spoken"))
def speak_phrases(harness, count):
    for _ in range(count):
        harness.feed_phrase()


@when(parsers.parse("{count:d} phrases are spoken faster than they can be transcribed"))
def speak_phrases_fast(harness, count):
    for _ in range(count):
        harness.feed_phrase()


@when("the session is stopped")
def stop_session(harness):
    harness.stop_latency = harness.stop_and_wait(timeout=10)


@then(parsers.parse("the first phrase appeared within {seconds:g} second"))
@then(parsers.parse("the first phrase appeared within {seconds:g} seconds"))
def first_phrase_within(harness, seconds):
    assert harness.first_phrase_at is not None
    assert harness.first_phrase_at < seconds


@then("no backlog built up")
def no_backlog(harness):
    assert harness.max_backlog <= 1


@then("a backlog built up")
def yes_backlog(harness):
    assert harness.max_backlog >= 2


@then(parsers.parse("stopping finished within {seconds:g} second"))
@then(parsers.parse("stopping finished within {seconds:g} seconds"))
def stop_within(harness, seconds):
    assert harness.stop_latency < seconds


@then("stopping finished within a bounded time")
def stop_bounded(harness):
    # Bounded means "proportional to the backlog", not "instant" and not "forever".
    assert harness.stop_latency < 6 * 0.2 * 3


@then("every spoken phrase was eventually transcribed")
def all_phrases_transcribed(harness):
    assert len(harness.phrases_seen) == 6
