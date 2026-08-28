from pipeline.common.cadence import is_due, snapshot_interval_mins


def test_dense_near_close_so_clv_is_capturable():
    # CLV is measured at T-60m; that window must be sampled at 15-min resolution
    assert snapshot_interval_mins(60) == 15
    assert snapshot_interval_mins(6 * 60) == 15


def test_sparse_far_from_close():
    assert snapshot_interval_mins(24 * 60) == 60
    assert snapshot_interval_mins(15 * 24 * 60) == 360


def test_never_skips_first_observation_of_a_new_market():
    assert is_due(15 * 24 * 60, None) is True


def test_skips_when_not_yet_due():
    assert is_due(15 * 24 * 60, 30) is False       # 6h cadence, only 30m elapsed
    assert is_due(15 * 24 * 60, 360) is True


def test_tolerance_absorbs_early_cron_fire():
    # job fires a few seconds early -> must still snapshot, not skip a cycle
    assert is_due(60, 14.2) is True


def test_unknown_close_time_defaults_hourly():
    assert snapshot_interval_mins(None) == 60
