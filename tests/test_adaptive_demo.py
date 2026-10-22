import pytest

from labos.cli import main
from labos.demo import acceptance


def test_adaptive_cli_rejects_invalid_simulator_before_creating_output(tmp_path):
    output = tmp_path / "invalid-demo"
    assert main(["adaptive-demo", "--directory", str(output), "--resonance-nm", "900"]) == 1
    assert not output.exists()


def test_adaptive_demo_rejects_invalid_seed_before_creating_output(tmp_path):
    output = tmp_path / "invalid-seed"
    with pytest.raises(ValueError):
        acceptance(output, adaptive=True, seed=-1)
    assert not output.exists()
