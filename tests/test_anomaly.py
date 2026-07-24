from core.detection.anomaly import _zscore


def test_zscore_high_for_spike() -> None:
    baseline = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]
    assert _zscore(20, baseline) > 3.0


def test_zscore_low_for_normal_variation() -> None:
    baseline = [5, 6, 5, 4, 5, 6, 5, 4, 5, 6]
    assert _zscore(6, baseline) < 2.0


def test_zscore_handles_zero_variance_baseline() -> None:
    baseline = [3, 3, 3, 3, 3]
    assert _zscore(3, baseline) == 0.0
    assert _zscore(10, baseline) > 0.0
