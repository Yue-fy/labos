from __future__ import annotations

from datetime import datetime, timezone
import math
import time
from types import SimpleNamespace

from labos.cryostat_pilot import ReadingFault
from labos.files import json_bytes
from labos.pilot import PilotEngine
from . import __version__, CORE_VERSION
from .magnet import validate_state
from .models import CampaignTask, TARGETS
from .records import digest


def accept_point(point, config):
    z = point['target_z_t']
    validate_state(point['field']['state'], config, target=z, require_control=True)
    if point['field'].get('qualified') is not True:
        raise ValueError('field point lacks qualification')
    result = point['optical']
    if (result.get('status') != 'COMPLETED' or result.get('acquisition_complete') is not True
            or result.get('protection_verified') is not True or result.get('close_error') is not None
            or result.get('rejected_samples') or not result.get('cleanup')
            or not all(c.get('verified') is True for c in result['cleanup'])):
        raise ValueError('optical point failed completeness or protection requirements')
    samples = result['samples']
    if len(samples) != 6:
        raise ValueError('point must retain exactly six raw samples')
    for phase in ('dark_baseline', 'illuminated'):
        selected = [s for s in samples if s.get('phase') == phase]
        if len(selected) != 3 or [s.get('sample_index') for s in selected] != [0, 1, 2]:
            raise ValueError('missing, duplicated or misordered phase samples')
    for sample in samples:
        if sample.get('simulated') is not False or sample.get('excitation_v_rms') != .004:
            raise ValueError('invalid physical sample identity/excitation')
        if sample.get('laser_enabled') is not (sample['phase'] == 'illuminated'):
            raise ValueError('sample laser/phase mismatch')
        power = sample.get('power_w')
        if type(power) not in (float, int) or not math.isfinite(power) or not 0 <= power <= 1e-6:
            raise ValueError('invalid power sample')
        for role in ('xx', 'xy'):
            channel = sample['channels'][role]
            if (channel.get('harmonic') != 1 or channel.get('lia_status_raw') != 0
                    or channel.get('error_status_raw') != 0):
                raise ValueError('invalid lock-in settings or status')
            for key in ('x_v', 'y_v'):
                if type(channel.get(key)) not in (float, int) or not math.isfinite(channel[key]):
                    raise ValueError('missing finite lock-in channel')
        for when in ('magnetic_before', 'magnetic_after'):
            validate_state(sample[when]['state'], config, target=z, require_control=True)
    return True


class PointView:
    """Borrow campaign sessions; close releases only the point view."""
    def __init__(self, optical, magnet, config, z, deadline):
        self.optical, self.magnet, self.config, self.z = optical, magnet, config, z
        self.deadline = deadline

    def set_guard(self, deadline, cancel):
        deadline = min(deadline, self.deadline)
        self.optical.set_guard(deadline, cancel)
        guard = getattr(self.magnet, 'set_guard', None)
        if guard:
            guard(deadline)

    def open(self):
        pass

    def preflight(self):
        validate_state(self.magnet.read()['state'], self.config, self.z, True)
        return self.optical.preflight()

    def configure(self, phase, plan): self.optical.configure(phase, plan)
    def laser_on(self, current): self.optical.laser_on(current)
    def laser_off(self): return self.optical.laser_off()
    def protect_excitation(self): return self.optical.protect_excitation()
    def close(self): pass

    def read_sample(self, phase):
        raw = {}
        before = None
        try:
            before = self.magnet.read()
            validate_state(before['state'], self.config, self.z, True)
            raw = self.optical.read_sample(phase)
            raw['magnetic_before'] = before
            after = self.magnet.read()
            raw['magnetic_after'] = after
            validate_state(after['state'], self.config, self.z, True)
            return raw
        except Exception as exc:
            rejected = getattr(exc, 'raw_sample', raw)
            if isinstance(rejected, dict):
                rejected = {**rejected, 'magnetic_before': before, 'field_target_z_t': self.z}
            raise ReadingFault(f'{type(exc).__name__}: {exc}', rejected) from exc


class CampaignEngine:
    def __init__(self, optical, magnet, config, clock=time.monotonic, sleep=time.sleep):
        self.optical, self.magnet, self.config = optical, magnet, config
        self.clock, self.sleep = clock, sleep

    def run(self, task, approval, event_sink=lambda event: None):
        task = CampaignTask.model_validate_json(json_bytes(task.model_dump(mode='json')))
        approval.validate_plan(task.optical)
        result = {'status': 'FAILED', 'task': task.model_dump(mode='json'), 'task_sha256': digest(task.model_dump(mode='json')),
                  'extension_version': __version__, 'core_version': CORE_VERSION,
                  'started_at_utc': datetime.now(timezone.utc).isoformat(), 'points': [],
                  'error': None, 'protection': [], 'zero': None, 'close_error': None,
                  'evidence_errors': [],
                  'temperature_baseline_k': self.config.temperature_baseline_k,
                  'temperature_setpoint_k': self.config.temperature_setpoint_k,
                  'temperature_drift_max_k': self.config.temperature_drift_max_k,
                  'ramp_rate': 'unknown_preserved_by_native_controller',
                  'quality_flags': ['sdk_values_server_cached_no_device_timestamp',
                                    'pm_pickoff_not_calibrated_sample_power',
                                    'sample_current_uncalibrated', 'single_ordered_sweep',
                                    'optical_modulation_unverified']}
        deadline = self.clock() + self.config.max_campaign_s - self.config.cleanup_timeout_s - 30.
        optical_opened = magnetic_opened = owned = False
        close_errors = []
        def emit(event):
            try:
                event_sink(event)
            except Exception as exc:
                result['evidence_errors'].append(f'{type(exc).__name__}: {exc}')
        def guard():
            if result['evidence_errors']:
                raise ValueError('raw evidence persistence failed; stop acquisition')
            if self.clock() >= deadline:
                raise TimeoutError('campaign acquisition deadline exceeded')
        def magnetic_guard(value):
            method = getattr(self.magnet, 'set_guard', None)
            if method:
                method(value)
        def protect(where):
            record = PilotEngine(self.optical, self.clock, self.sleep)._protect(where, .004)
            result['protection'].append(record)
            emit({'event': 'output_protection', 'record': record})
            return record['verified']
        try:
            guard()
            self.optical.set_guard(deadline, None)
            optical_opened = True
            self.optical.open()
            result['preflight'] = self.optical.preflight()
            if result['preflight'].get('ready') is not True or result['preflight'].get('laser_enabled') is not False:
                raise ValueError('campaign does not own a laser-OFF preflighted station')
            owned = True
            if not protect('before_magnetic_open'):
                raise ValueError('initial optical protection failed')
            magnetic_guard(deadline)
            magnetic_opened = True
            result['magnetic_initial'] = self.magnet.open(writes=True)
            for index, z in enumerate(task.targets_z_t):
                guard()
                if not protect('before_field_' + str(index)):
                    raise ValueError('optical protection failed before changing field')
                magnetic_guard(deadline)
                field = self.magnet.move(z)
                guard()
                validate_state(field['state'], self.config, z, True)
                point = {'point_index': index, 'target_z_t': z, 'field': field,
                         'session_close_semantics': 'point_view_released_campaign_retains_hardware'}
                result['points'].append(point)
                emit({'event': 'field_qualified', 'point': dict(point)})
                guard()
                view = PointView(self.optical, self.magnet, self.config, z, deadline)
                point['optical'] = PilotEngine(view, self.clock, self.sleep).run(task.optical, approval)
                emit({'event': 'optical_point_finished', 'point': point})
                guard()
                accept_point(point, self.config)
            result['status'] = 'COMPLETED'
        except BaseException as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'
            emit({'event': 'campaign_error', 'error': result['error']})
        finally:
            cleanup_deadline = self.clock() + self.config.cleanup_timeout_s
            magnetic_guard(cleanup_deadline)
            if owned and not protect('campaign_final'):
                result['status'] = 'UNKNOWN'
            if magnetic_opened:
                try:
                    if not getattr(self.magnet, 'healthy', True):
                        raise ValueError('uncertain SDK child; no blind zero command')
                    result['zero'] = self.magnet.zero()
                    if (result['zero'].get('zero_verified') is not True
                            or result['zero'].get('initial_control_restored') is not True):
                        raise ValueError('final zero or initial control mode is unverified')
                    validate_state(result['zero']['state'], self.config, target=0.)
                except BaseException as exc:
                    result['status'] = 'UNKNOWN'
                    result['zero_error'] = f'{type(exc).__name__}: {exc}'
                try:
                    result['magnetic_close'] = self.magnet.close()
                except BaseException as exc:
                    close_errors.append('magnetic: ' + f'{type(exc).__name__}: {exc}')
            if optical_opened:
                try:
                    self.optical.close()
                except BaseException as exc:
                    close_errors.append('optical: ' + f'{type(exc).__name__}: {exc}')
            if close_errors:
                result['close_error'] = '; '.join(close_errors)
                result['status'] = 'UNKNOWN'
            result['ended_at_utc'] = datetime.now(timezone.utc).isoformat()
            emit({'event': 'campaign_finished', 'status': result['status'], 'zero': result['zero'],
                  'close_error': result['close_error']})
            if result['evidence_errors']:
                result['status'] = 'UNKNOWN'
        return result


def validate_campaign(result):
    if result.get('status') != 'COMPLETED':
        return {'accepted': False, 'status': result.get('status'), 'reason': 'campaign incomplete/failed/unknown'}
    task = CampaignTask.model_validate_json(json_bytes(result['task']))
    if digest(task.model_dump(mode='json')) != result['task_sha256']:
        raise ValueError('campaign task hash mismatch')
    if (result.get('close_error') is not None or not result.get('protection')
            or not all(p.get('verified') is True for p in result['protection'])
            or result.get('magnetic_close', {}).get('closed') is not True):
        raise ValueError('campaign closure/protection failed')
    config = SimpleNamespace(temperature_baseline_k=result['temperature_baseline_k'],
                             temperature_setpoint_k=180., temperature_drift_max_k=.1)
    points = result['points']
    if [p['target_z_t'] for p in points] != list(TARGETS):
        raise ValueError('campaign field order or point count differs')
    for index, point in enumerate(points):
        if point.get('point_index') != index:
            raise ValueError('point index mismatch')
        accept_point(point, config)
    zero = result['zero']
    if zero.get('zero_verified') is not True or zero.get('initial_control_restored') is not True:
        raise ValueError('final zero or initial mode restoration failed')
    initial_mode = result['magnetic_initial']['initial_state']['field_control_enabled']
    validate_state(zero['state'], config, target=0., require_control=initial_mode)
    return {'accepted': True, 'points': 5, 'samples': 30, 'actual_zero_verified': True,
            'close_error': None}
