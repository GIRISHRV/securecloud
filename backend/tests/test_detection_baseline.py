from backend.detection import DenialBurstBaseline, FlowRecord


def flow(identifier: str, at: float, decision: str = "denied") -> FlowRecord:
    return FlowRecord(
        id=identifier,
        source_id="source",
        destination_id="destination",
        source_tenant="college",
        destination_tenant="hospital",
        port=8080,
        at=at,
        decision=decision,
        reason="cross-tenant",
    )


def test_denial_burst_baseline_requires_three_events_in_the_window():
    detector = DenialBurstBaseline(window_seconds=60, denial_threshold=3)

    for index, at in enumerate((100.0, 110.0), start=1):
        event = flow(str(index), at)
        assert detector.score_event(event).is_anomalous is False
        detector.record_flow(event)

    third = flow("3", 120.0)
    result = detector.score_event(third)
    assert result.is_anomalous is True
    assert result.supporting_facts["recent_denials_in_window"] == 3

    detector.record_flow(third)
    after_window = flow("4", 181.0)
    assert detector.score_event(after_window).is_anomalous is False
