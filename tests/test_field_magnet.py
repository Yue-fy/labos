from dataclasses import dataclass, replace
from types import SimpleNamespace
import time

import pytest

from labos_field.magnet import MagnetSession, load_reviewed_driver
from labos_field.rpc import MagnetProcess, RpcTimeout


@dataclass
class Vector:
    bx_t: float = 0.
    bz_t: float = 0.


@dataclass
class State:
    sample_temperature_k: float = 180.
    user_temperature_k: float = 180.
    vti_temperature_k: float = 170.
    field: Vector = None
    field_setpoint: Vector = None
    field_control_enabled: bool = False
    temperature_control_enabled: bool = True
    error_code: int = 0
    error_message: str = ''

    def __post_init__(self):
        self.field = self.field or Vector()
        self.field_setpoint = self.field_setpoint or Vector()


class Clock:
    value = 0.
    def __call__(self): return self.value
    def sleep(self, seconds): self.value += seconds


class Driver:
    def __init__(self):
        self.state = State()
        self.calls = []
        self.connected = False
        self.writes_authorized = False
    def connect(self, **kwargs): self.connected = True
    def read_state(self): return self.state
    def ensure_field_control(self, enabled, **kwargs):
        self.calls.append(('control', enabled))
        self.state = replace(self.state, field_control_enabled=enabled)
    def set_vector_field(self, target, **kwargs):
        assert kwargs['max_step_t'] == .5 and kwargs['transition_policy'] == 'direct'
        self.calls.append(('target', target.bz_t))
        self.state = replace(self.state, field_setpoint=target)
    def wait_for_field(self, target, **kwargs):
        self.calls.append(('qualify', target.bz_t))
        self.state = replace(self.state, field=target)
        kwargs['on_sample'](self.state, 10., 'field_stability', None)
        return self.state
    def request_zero_field(self, **kwargs):
        self.calls.append(('zero', 0.))
        self.state = replace(self.state, field=Vector(), field_setpoint=Vector())
        kwargs['on_sample'](self.state, 10., 'field_stability', None)
        return self.state
    def close(self): self.calls.append(('close', None)); self.connected = False


def settings(tmp_path):
    return SimpleNamespace(magnetic_source_dir=tmp_path / 'src', dll_path=tmp_path / 'missing.dll',
                           magnetic_lease_profiles=[], temperature_setpoint_k=180.,
                           temperature_baseline_k=180., temperature_drift_max_k=.1)


def session(tmp_path, driver=None):
    clock = Clock()
    return MagnetSession(settings(tmp_path), lambda x: None, driver=driver or Driver(),
                         vector=Vector, clock=clock, sleep=clock.sleep)


def test_native_target_then_actual_qualification_and_final_zero_mode_restore(tmp_path):
    s = session(tmp_path)
    s.open(writes=True)
    for z in [-.5, -.25, 0., .25, .5]:
        result = s.move(z)
        assert result['state']['field']['bz_t'] == z
    zero = s.zero()
    assert zero['zero_verified'] and zero['initial_control_restored']
    assert s.driver.state.field_control_enabled is False
    assert [c for c in s.driver.calls if c[0] == 'target'] == [
        ('target', -.5), ('target', -.25), ('target', 0.), ('target', .25), ('target', .5)]
    s.close()
    assert s.driver.calls[-1] == ('close', None)


def test_readonly_session_cannot_enable_or_move_and_bad_state_is_rejected(tmp_path):
    s = session(tmp_path); s.open(writes=False)
    with pytest.raises(ValueError): s.move(-.5)
    assert s.driver.calls == []
    s.driver.state = replace(s.driver.state, sample_temperature_k=181.)
    with pytest.raises(ValueError, match='temperature'): s.read()
    s.driver.state = replace(s.driver.state, sample_temperature_k=180., error_code=37)
    with pytest.raises(ValueError, match='fault'): s.read()
    s.close()


def test_unknown_initial_field_or_off_plan_target_never_writes(tmp_path):
    driver = Driver(); driver.state = replace(driver.state, field=Vector(0, 2.))
    s = session(tmp_path, driver)
    with pytest.raises(ValueError): s.open(writes=True)
    assert driver.calls == []
    s = session(tmp_path); s.open(writes=True)
    with pytest.raises(ValueError): s.move(1.)
    assert s.driver.calls == []
    s.close()


def test_unreviewed_source_is_refused_before_vendor_library_load(tmp_path):
    with pytest.raises(ValueError, match='source'):
        load_reviewed_driver(settings(tmp_path), lambda x: None)


def test_failed_zero_is_not_followed_by_disabling_field_control(tmp_path):
    driver = Driver()
    s = session(tmp_path, driver); s.open(writes=True); s.move(.5)
    driver.request_zero_field = lambda **kwargs: driver.state
    with pytest.raises(ValueError): s.zero()
    assert driver.state.field_control_enabled is True
    assert ('control', False) not in driver.calls
    s.close()


def test_driver_close_failure_is_reported_without_claiming_closed(tmp_path):
    s = session(tmp_path); s.open(writes=False)
    def fail(): raise OSError('Disconnect failed')
    s.driver.close = fail
    with pytest.raises(RuntimeError, match='Disconnect failed'): s.close()
    with pytest.raises(RuntimeError, match='Disconnect failed'): s.close()


def hanging_child(connection, config, state_dir):
    request = connection.recv()
    time.sleep(.25)
    connection.send({'id': request['id'], 'ok': True, 'result': {'late': True}})
    connection.close()


def test_real_child_timeout_latches_and_late_reply_does_not_authorize_more_commands(tmp_path):
    process = MagnetProcess({}, tmp_path, target=hanging_child)
    with pytest.raises(RpcTimeout): process.call('read', timeout=.03)
    assert not process.healthy
    with pytest.raises(ValueError, match='uncertain'): process.call('move', {'z': -.5}, timeout=1)
    process.process.join(2)
    assert not process.process.is_alive()
    assert (tmp_path / 'magnetic-child-uncertain.json').exists()
