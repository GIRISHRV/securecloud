"""Quiet-path volume rule: catches a plugin flooding its approved path, not a storefront sale."""
from backend.detection.volume import volume_spike


def test_quiet_path_burst_is_a_spike():
    assert volume_spike(100, 0.25)   # plugin path normally syncs once every few windows
    assert volume_spike(20, 0.0)


def test_busy_path_surge_is_not_flagged():
    assert not volume_spike(80, 3.0)  # storefront during a sale: busy path, legitimate surge


def test_small_bursts_are_ignored():
    assert not volume_spike(6, 0.0)   # e.g. a port scan's one allowed connection


def test_one_earlier_burst_does_not_make_a_quiet_path_look_busy():
    from backend.detection.volume import expected_rates
    from backend.telemetry.windows import GraphEdge, GraphSnapshot

    def window(index, count):
        edges = (GraphEdge("plugin", "api", count, count, 0, (8080,), ("TCP",), False),) if count else ()
        return GraphSnapshot(index * 30.0, index * 30.0 + 30, ("plugin", "api"), edges, (), 0)

    history = [window(0, 360), window(1, 0), window(2, 1), window(3, 0)]
    assert expected_rates(history)[("plugin", "api")] == 0.5
    assert volume_spike(186, 0.5)
