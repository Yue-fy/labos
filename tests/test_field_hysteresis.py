"""Preserve both legs at repeated fields under exact central authority."""

import copy

import pytest

from labos_field.engine import validate_campaign
from labos_field.models import CampaignTask, default_task
from test_field_engine import Magnet, Optical, run
from test_field_evidence import complete_evidence

PATH = (-0.5, -0.25, 0.0, 0.25, 0.5, 0.25, 0.0, -0.25, -0.5)


def loop_task():
    return CampaignTask.model_validate(
        {**default_task("new-hysteresis-task").model_dump(), "targets_z_t": PATH}
    )


def test_only_exact_complete_hysteresis_path_is_added_to_existing_authority():
    assert loop_task().targets_z_t == PATH
    for wrong in (
        PATH[:-1],
        PATH + (0.0,),
        PATH[:5] + (-0.25, 0.0, 0.25, -0.5),
        (-0.6,) + PATH[1:],
        (False,) + PATH[1:],
    ):
        with pytest.raises(ValueError):
            CampaignTask.model_validate({**loop_task().model_dump(), "targets_z_t": wrong})


def test_nine_points_keep_fifty_four_samples_and_separate_repeated_field_events():
    events = []
    result, optical, magnet = run(task=loop_task(), event_sink=events.append)
    assert result["status"] == "COMPLETED"
    assert magnet.targets == list(PATH)
    assert [p["point_index"] for p in result["points"]] == list(range(9))
    assert sum(len(p["optical"]["samples"]) for p in result["points"]) == 54
    raw_events = [e for e in events if e["event"] == "sample_raw_captured"]
    assert len(raw_events) == 54
    assert len({(e["point_index"], e["record_index"]) for e in raw_events}) == 54
    assert [e["point_index"] for e in raw_events if e["target_z_t"] == -0.25] == [1] * 6 + [7] * 6
    assert optical.open_count == optical.close_count == 1 and optical.on_count == 9
    assert not optical.emission and magnet.zero_count == magnet.close_count == 1
    assert validate_campaign(result) == {
        "accepted": True,
        "points": 9,
        "samples": 54,
        "actual_zero_verified": True,
        "close_error": None,
    }


def test_first_reverse_transition_failure_stops_remaining_acquisition():
    optical = Optical()

    class ReverseFailure(Magnet):
        def move(self, z):
            if len(self.targets) == 5:
                self.targets.append(z)
                raise OSError("first descending transition failed")
            return super().move(z)

    result, optical, magnet = run(optical, ReverseFailure(optical), task=loop_task())
    assert result["status"] == "FAILED"
    assert magnet.targets == list(PATH[:6]) and optical.on_count == 5
    assert len(result["points"]) == 5 and not optical.emission
    assert magnet.zero_count == magnet.close_count == 1
    assert validate_campaign(result)["accepted"] is False


def test_complete_loop_wire_evidence_is_accepted_and_missing_reverse_point_rejected():
    task = loop_task()
    result = complete_evidence(task=task)
    assert validate_campaign(result, expected_task=task, require_raw=True)["samples"] == 54
    damaged = copy.deepcopy(result)
    del damaged["points"][7]
    with pytest.raises(ValueError):
        validate_campaign(damaged, require_raw=True)


def test_reverse_samples_cannot_borrow_forward_getter_evidence_at_same_field():
    result = complete_evidence(task=loop_task())
    result["points"][7]["optical"]["samples"][0]["magnetic_before"] = copy.deepcopy(
        result["points"][1]["optical"]["samples"][0]["magnetic_before"]
    )
    with pytest.raises(ValueError, match="interval|hold|sample"):
        validate_campaign(result, require_raw=True)
