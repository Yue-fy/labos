import math

import pytest
from pydantic import ValidationError

from labos.models import Plan, intersect_limits


def test_inclusive_scan_and_fixed_wavelength():
    plan = Plan(wavelength_start_nm=500, wavelength_stop_nm=700,
                wavelength_step_nm=10, angle_start_deg=0, angle_stop_deg=180,
                angle_step_deg=10)
    assert len(plan.points()) == 399
    assert plan.points()[0] == (500, 0)
    assert plan.points()[-1] == (700, 180)
    assert len(Plan().points()) == 19


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf])
def test_invalid_step(value):
    with pytest.raises(ValidationError):
        Plan(angle_step_deg=value)


def test_reversed_and_excessive_grid():
    with pytest.raises(ValidationError):
        Plan(wavelength_start_nm=700, wavelength_stop_nm=500)
    with pytest.raises(ValidationError):
        Plan(angle_step_deg=0.0001)


def test_limits_are_intersections():
    assert intersect_limits([(-200, 200), (-20, 20), (-5, 5)]) == (-5, 5)
    with pytest.raises(ValueError, match="intersection"):
        intersect_limits([(1, 2), (3, 4)])
