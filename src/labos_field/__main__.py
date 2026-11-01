from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
import uuid

import labos
from labos.config import AgentConfig, load_config as load_connection
from labos.cryostat_pilot import CryostatAdapter
from labos.files import InstanceLock, atomic_write, contains_credential, json_bytes
from labos.pilot import PilotApproval
from labos.pilot_worker import load_pilot_worker_config

from . import CORE_VERSION, __version__
from .channel import Channel
from .engine import CampaignEngine, validate_campaign
from .models import authorize, fingerprint, load_config, optical_plan
from .records import Journal, artifact_messages, reassemble
from .rpc import MagnetProcess


def optical_settings(config):
    if hashlib.sha256(config.optical_profile.read_bytes()).hexdigest() != config.optical_profile_sha256:
        raise ValueError('existing optical profile hash differs')
    profile = load_pilot_worker_config(config.optical_profile)
    if (profile.agent_id != config.agent_id or profile.adapter_id != 'cryostat_v1'
            or profile.connection_config.resolve() != config.connection_config
            or profile.approval is None or profile.approval.enabled is not False):
        raise ValueError('existing physical profile must remain disabled and match this PC/connection')
    approval = PilotApproval.model_validate({**profile.approval.model_dump(), 'enabled': True})
    approval.validate_plan(optical_plan())
    optical = CryostatAdapter(profile.adapter_config)
    if (optical.config.experiment_scope != 'optical_readback' or optical.config.aux_enabled
            or optical.config.max_laser_current_a != .0218 or optical.config.power_limit_w != 1e-6
            or optical.config.io_timeout_ms != 1000):
        raise ValueError('optical profile differs from the commissioned21.8mA/1uW/1s-I/O scope')
    if optical.config.station_config.resolve() in config.magnetic_lease_profiles:
        raise ValueError('magnetic leases must not duplicate the optical station lease')
    return optical, approval


def _event_writer(path):
    def write(event):
        with path.open('ab') as stream:
            stream.write(json_bytes({**event, 'captured_at_utc': datetime.now(timezone.utc).isoformat()}) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
    return write


def _logs(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []


def preflight(config):
    if config.enabled:
        raise ValueError('preflight requires disabled campaign configuration')
    directory = config.state_dir / ('preflight-' + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True)
    optical, _ = optical_settings(config)
    magnet = MagnetProcess(config, directory)
    result = {'document_type': 'labos_field_commissioning', 'status': 'FAILED',
              'extension_version': __version__, 'core_version': labos.__version__,
              'config_sha256': fingerprint(config), 'optical_profile_sha256': config.optical_profile_sha256,
              'writes_authorized': False, 'error': None, 'close_error': None, 'states': []}
    errors = []
    try:
        optical.open()
        result['optical_preflight'] = optical.preflight()
        if optical.number('cld', 'SOUR1:CURR:LEV:IMM:AMPL?') != 0:
            raise ValueError('disabled preflight requires existing zero laser-current setpoint')
        result['magnetic_open'] = magnet.open(writes=False)
        for i in range(12):
            result['states'].append(magnet.read())
            if i < 11:
                time.sleep(1.)
        result['status'] = 'PASSED'
    except BaseException as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['traceback'] = traceback.format_exc()
    finally:
        for name, resource in [('magnetic', magnet), ('optical', optical)]:
            try:
                value = resource.close()
                result[name + '_close'] = value or {'closed': True}
            except BaseException as exc:
                errors.append(f'{name}: {type(exc).__name__}: {exc}')
        if errors:
            result.update(status='UNKNOWN', close_error='; '.join(errors))
        result['observed_at_utc'] = datetime.now(timezone.utc).isoformat()
        result['magnetic_events'] = _logs(directory / 'magnetic-events.jsonl')
        atomic_write(directory / 'commissioning.json', json_bytes(result))
        atomic_write(config.state_dir / 'commissioning.json', json_bytes(result))
    return result


def deliver(config, result, channel):
    if contains_credential(result, [channel.secret]):
        raise ValueError('credential present in artifact; preserve locally and do not transmit')
    receipts = []
    for message in artifact_messages(config.task_id, result):
        message['in_reply_to'] = config.message_id
        receipts.append(channel.send(message))
    record = {'artifact_parts_acknowledged': len(receipts), 'task_id': config.task_id,
              'last_sequence': receipts[-1]['sequence']}
    atomic_write(config.state_dir / (config.task_id + '-delivery.json'), json_bytes(record))
    return record


def execute(config, wait_s):
    if not config.enabled:
        raise ValueError('campaign configuration is disabled')
    commissioned = json.loads((config.state_dir / 'commissioning.json').read_text())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(commissioned['observed_at_utc'])).total_seconds()
    if (commissioned.get('status') != 'PASSED' or commissioned.get('close_error') is not None
            or commissioned.get('config_sha256') != fingerprint(config)
            or not 0 <= age <= config.commissioning_max_age_s):
        raise ValueError('fresh matching passed disabled commissioning is required')
    optical, approval = optical_settings(config)
    connection = load_connection(config.connection_config, AgentConfig)
    status_path = config.state_dir / 'runner-status.json'
    with Channel(connection) as channel:
        health = channel.client.get('/health'); health.raise_for_status()
        if health.json().get('version') != CORE_VERSION:
            raise ValueError('central/core version mismatch')
        atomic_write(status_path, json_bytes({'phase': 'waiting_for_one_central_task',
            'pid': os.getpid(), 'task_id': config.task_id, 'message_id': config.message_id,
            'message_sha256': config.message_sha256, 'extension_version': __version__,
            'core_version': labos.__version__, 'hardware_opened': False}))
        end = time.monotonic() + wait_s
        message = channel.fetch(config.message_id)
        while message is None and time.monotonic() < end:
            time.sleep(min(2., max(0., end-time.monotonic())))
            message = channel.fetch(config.message_id)
        if message is None:
            raise ValueError('pinned task has not arrived; no hardware opened')
        task = authorize(message, config.message_id, config.message_sha256, config.task_id)
        # Recheck commissioning age after the wait, before intent and device access.
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(commissioned['observed_at_utc'])).total_seconds()
        if not 0 <= age <= config.commissioning_max_age_s:
            raise ValueError('commissioning expired while waiting; no hardware opened')
        journal = Journal(config.state_dir)
        journal.begin(task.task_id, config.message_sha256, fingerprint(config))
        directory = config.state_dir / task.task_id
        directory.mkdir(exist_ok=False)
        atomic_write(directory / 'task-envelope.json', json_bytes(message))
        magnet = MagnetProcess(config, directory)
        atomic_write(status_path, json_bytes({'phase': 'executing_one_central_task',
            'pid': os.getpid(), 'magnetic_pid': magnet.pid, 'task_id': task.task_id,
            'no_replay': True}))
        result = CampaignEngine(optical, magnet, config).run(task, approval,
            event_sink=_event_writer(directory / 'campaign-events.jsonl'))
        result.update(message_sha256=config.message_sha256, config_sha256=fingerprint(config),
                      magnetic_events=_logs(directory / 'magnetic-events.jsonl'),
                      campaign_events=_logs(directory / 'campaign-events.jsonl'))
        journal.finish(task.task_id, result)
        atomic_write(status_path, json_bytes({'phase': 'measurement_finished', 'status': result['status'],
            'pid': os.getpid(), 'task_id': task.task_id, 'close_error': result['close_error']}))
        delivery = deliver(config, result, channel)
    return {'status': result['status'], 'task_id': task.task_id, 'points': len(result['points']),
            'zero': result.get('zero'), 'close_error': result['close_error'], 'delivery': delivery}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Finite LabOS field extension; never runs production workflows')
    parser.add_argument('action', choices=['preflight', 'run', 'deliver', 'inspect'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--wait-s', type=float, default=0.)
    parser.add_argument('--messages', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if labos.__version__ != CORE_VERSION:
            raise ValueError('extension requires deployed LabOS core0.2.8')
        if args.action == 'inspect':
            messages = json.loads(args.messages.read_text())
            result = reassemble(messages.get('messages', []) if isinstance(messages, dict) else messages)
            validation = validate_campaign(result)
            if args.output:
                atomic_write(args.output, json_bytes(result))
            print(json.dumps(validation, indent=2))
            return 0 if validation['accepted'] else 1
        config = load_config(args.config)
        if args.action == 'run' and not config.enabled:
            raise ValueError('campaign configuration is disabled')
        if not 0 <= args.wait_s <= 1800:
            raise ValueError('task wait must be within0–1800seconds')
        with InstanceLock(config.state_dir):
            if args.action == 'preflight':
                result = preflight(config)
            elif args.action == 'run':
                result = execute(config, args.wait_s)
            else:
                connection = load_connection(config.connection_config, AgentConfig)
                with Channel(connection) as channel:
                    result = deliver(config, Journal(config.state_dir).result(config.task_id), channel)
        if args.output:
            atomic_write(args.output, json_bytes(result))
        print(json.dumps({k: v for k, v in result.items() if k not in {'magnetic_events', 'states'}}, indent=2))
        return 0 if result.get('status', 'PASSED') in {'PASSED', 'COMPLETED'} else 1
    except Exception as exc:
        print(json.dumps({'status': 'REFUSED_OR_STOPPED', 'error': f'{type(exc).__name__}: {exc}'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
