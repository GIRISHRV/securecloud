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


def _window(index, edges):
    from backend.telemetry.windows import GraphEdge, GraphSnapshot
    built = tuple(GraphEdge(s, d, c, c, 0, (8080,), ("TCP",), False) for s, d, c in edges)
    return GraphSnapshot(index * 30.0, index * 30.0 + 30, tuple({n for s, d, _ in edges for n in (s, d)}), built, (), 0)


def test_windows_before_a_new_shop_existed_do_not_make_its_paths_look_quiet():
    """Regression: a brand-new shop's ordinary storefront traffic was flagged as a burst,
    because windows from before it existed were counted as zero traffic."""
    from backend.detection.volume import expected_rates
    history = [_window(i, []) for i in range(6)] + [_window(6 + i, [("new-web", "new-api", 24)]) for i in range(3)]
    created = {"new-web": 6 * 30.0, "new-api": 6 * 30.0}
    assert expected_rates(history)[("new-web", "new-api")] == 0.0          # old behaviour: looks quiet
    assert expected_rates(history, created)[("new-web", "new-api")] == 24.0  # only windows it existed
    assert not volume_spike(26, expected_rates(history, created)[("new-web", "new-api")])


def test_new_workloads_get_a_warm_up_but_established_ones_do_not():
    from backend.detection.volume import WARMUP_SECONDS, warming_up
    created = {"new-api": 1000.0, "shipfast-plugin": 0.0, "northstar-api": 0.0}
    assert warming_up(("new-web", "new-api"), created, at=1000.0 + 60)
    assert not warming_up(("new-web", "new-api"), created, at=1000.0 + WARMUP_SECONDS + 1)
    # The real attack case is unchanged: the long-established plugin flooding its approved path.
    assert not warming_up(("shipfast-plugin", "northstar-api"), created, at=1000.0)
    assert volume_spike(186, 0.0)
