Feature: Live transcription latency and stop responsiveness
  As someone using Double Scribe on a live call, I need transcribed phrases to
  appear promptly and Stop to return quickly, even when several phrases queue
  up faster than they can be transcribed.

  Scenario: A fast (GPU-class) model keeps up in real time
    Given a live session where transcription is effectively instant
    When 5 phrases are spoken
    And the session is stopped
    Then the first phrase appeared within 1 second
    And no backlog built up
    And stopping finished within 1 second

  Scenario: A slow model still drains its backlog and finishes, not hangs
    Given a live session where transcription takes 0.2 seconds per phrase
    When 6 phrases are spoken faster than they can be transcribed
    And the session is stopped
    Then a backlog built up
    And stopping finished within a bounded time
    And every spoken phrase was eventually transcribed
