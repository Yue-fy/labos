import pytest

from labos.config import CentralConfig, Enrollment
from labos.models import InstrumentSpec


@pytest.fixture
def central_config(tmp_path):
    return CentralConfig(admin_token="O" * 40, data_dir=tmp_path / "central",
                         command_timeout_s=2, agents={
        "pc-a": Enrollment(token="A" * 40, instruments=[InstrumentSpec(id="superk_01", kind="laser")]),
        "pc-b": Enrollment(token="B" * 40, instruments=[InstrumentSpec(id="rotator_01", kind="rotator"),
                                                        InstrumentSpec(id="spectrometer_01", kind="spectrometer")])})
