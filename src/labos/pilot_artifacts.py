"""Durable physical pilot JSON, independent of the simulated spectrum schema."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from pydantic import Field, ValidationError

from .files import atomic_write, contains_credential, json_bytes
from .models import Identifier, Model

MAX_PILOT_ARTIFACT_BYTES = 2_000_000


class PilotArtifact(Model):
    message_id: Identifier
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: dict
    attempt_nonce: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class PilotArtifacts:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pilot_artifacts (
                agent_id TEXT NOT NULL, message_id TEXT NOT NULL, sha256 TEXT NOT NULL,
                path TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(agent_id,message_id))""")

    def put(self, agent_id, content, digest, credentials):
        from .pilot import PilotPlan
        from .pilot_authority import PilotAuthority

        if len(content) > MAX_PILOT_ARTIFACT_BYTES or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Physical artifact size/checksum mismatch")
        try:
            artifact = PilotArtifact.model_validate_json(content)
            json_bytes(artifact.report)  # Reject nested NaN/Infinity too.
        except (ValueError, ValidationError):
            raise ValueError("Invalid physical pilot artifact") from None
        if contains_credential(artifact.model_dump(), credentials):
            raise ValueError("Credentials cannot be stored in physical artifacts")
        report = artifact.report
        if (
            report.get("status") not in ("COMPLETED", "FAILED", "CANCELLED", "UNKNOWN")
            or type(report.get("acquisition_complete")) is not bool
            or type(report.get("protection_verified")) is not bool
            or not isinstance(report.get("samples"), list)
            or len(report["samples"]) > 30
            or (
                report["status"] == "COMPLETED"
                and not (report["acquisition_complete"] and report["protection_verified"])
            )
        ):
            raise ValueError("Inconsistent physical pilot status or samples")
        for sample in report["samples"]:
            if (
                not isinstance(sample, dict)
                or sample.get("phase") not in (
                    "dark_baseline", "illuminated", "dark_hall_2f", "dark_a_1f", "dark_a_2f"
                )
                or not isinstance(sample.get("channels", {}), dict)
                or ("power_w" in sample and type(sample["power_w"]) not in (int, float))
            ):
                raise ValueError("Invalid physical pilot sample shape")
            for role, channel in sample.get("channels", {}).items():
                if not isinstance(role, str) or not isinstance(channel, dict):
                    raise ValueError("Invalid physical pilot channel shape")
                if any(
                    key in channel and type(channel[key]) not in (int, float)
                    for key in ("x_v", "y_v")
                ):
                    raise ValueError("Physical pilot voltages must be numeric")
        if not isinstance(report.get("rejected_samples", []), list):
            raise ValueError("Rejected physical samples must be an array")
        try:
            plan = PilotPlan.model_validate(report["plan"])
        except (KeyError, ValueError):
            raise ValueError("Physical artifact requires its validated plan") from None
        actual_plan_hash = hashlib.sha256(json_bytes(plan.model_dump(mode="json"))).hexdigest()
        if actual_plan_hash != artifact.plan_sha256:
            raise ValueError("Physical artifact plan fingerprint mismatch")
        with self.store.transaction() as db:
            parent = db.execute(
                "SELECT sender,body FROM correspondence WHERE agent_id=? AND id=?",
                (agent_id, artifact.message_id),
            ).fetchone()
            if parent is None:
                raise KeyError("Physical pilot task not found")
            task = json.loads(parent["body"])["body"]
            if (
                parent["sender"] != "central"
                or task.get("protocol") != "labos-agent-v1"
                or task.get("document_type") != "labos_pilot_task"
                or report.get("task_id") != task.get("task_id")
            ):
                raise ValueError("Physical artifact does not match a central pilot task")
            try:
                expected = PilotPlan.model_validate(task["pilot_plan"])
            except (ValueError, KeyError):
                raise ValueError("Central pilot plan is invalid") from None
            if expected != plan:
                raise ValueError("Physical artifact differs from the central pilot plan")
            PilotAuthority.finalize(db, agent_id, artifact)
            old = db.execute(
                "SELECT sha256,path FROM pilot_artifacts WHERE agent_id=? AND message_id=?",
                (agent_id, artifact.message_id),
            ).fetchone()
            path = self.store.root / "pilot-artifacts" / agent_id / (artifact.message_id + ".json")
            if old and (
                old["sha256"] != digest
                or not Path(old["path"]).is_file()
                or hashlib.sha256(Path(old["path"]).read_bytes()).hexdigest() != digest
            ):
                raise ValueError(
                    "Physical artifact already exists with different or unavailable content"
                )
            if not old:
                if path.exists() and path.read_bytes() != content:
                    raise ValueError(
                        "Unindexed physical artifact differs; local reconciliation required"
                    )
                atomic_write(path, content)
                db.execute(
                    "INSERT INTO pilot_artifacts VALUES(?,?,?,?,?)",
                    (agent_id, artifact.message_id, digest, str(path), time.time()),
                )
                self.store.event_db(
                    db,
                    "PHYSICAL_PILOT_ARTIFACT_STORED",
                    {
                        "agent_id": agent_id,
                        "message_id": artifact.message_id,
                        "sha256": digest,
                        "status": report["status"],
                        "samples": len(report["samples"]),
                    },
                )
        return {"accepted": True, "sha256": digest, "message_id": artifact.message_id}

    def get(self, agent_id, message_id):
        return json.loads(self.get_bytes(agent_id, message_id))

    def get_bytes(self, agent_id, message_id):
        """Return the verified original upload, preserving its byte digest contract."""
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT path,sha256 FROM pilot_artifacts WHERE agent_id=? AND message_id=?",
                (agent_id, message_id),
            ).fetchone()
        if row is None:
            raise KeyError("Physical pilot artifact not found")
        content = Path(row["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("Stored physical artifact checksum mismatch")
        return content



# Explicit review fields: raw traces, private identities and arbitrary nested data
# stay in the operator download. Every string, collection and section is bounded.
_REVIEW_BYTES = 32768
_IO = dict.fromkeys((
    'operation', 'role', 'command', 'state', 'outcome', 'protection', 'duration_s',
    'exception_type', 'message', 'deadline_exhausted', 'timeout_ms',
))
_PROVENANCE = dict.fromkeys((
    'measurement_plane', 'simulated', 'experiment_scope', 'sample_current_calibrated',
    'contact_polarity_verified', 'excitation_definition', 'optical_modulation_verified',
    'chopper_phase_lock_verified_by_query', 'nominal_wavelength_nm', 'wavelength_basis',
))
_CHANNEL = dict.fromkeys((
    'x_v', 'y_v', 'harmonic', 'reference_hz', 'detection_frequency_hz', 'time_constant_s',
    'lia_status_raw', 'error_status_raw', 'current_overload_status_verified',
))
_PARTIAL = {**_PROVENANCE, 'power_w': None, 'laser_current_a': None, 'laser_enabled': None,
            'elapsed_s': None, 'last_io': _IO, 'channels': 'channels',
            'excluded_readout_roles': 'list', 'excluded_device_sessions': 'list'}
_STAGE = dict.fromkeys(('stage', 'phase', 'started_elapsed_s', 'duration_s', 'outcome'))
_FAILURE = {**dict.fromkeys(('stage', 'phase', 'exception_type', 'elapsed_s')),
            'deadline': dict.fromkeys(('scope', 'run_exhausted', 'phase_exhausted',
                                       'effective_scope'))}
_PROTECTION = dict.fromkeys((
    'verified', 'scope', 'laser_off_verified', 'minimum_excitation_verified', 'actual_v_rms',
    'emission_off_readback', 'zero_current_setpoint_verified', 'measurement_harmonic_restored',
    'reference_hz', 'restore_error', 'amplitude_error', 'error',
))
_PROTECTION['errors'] = 'list'
_CLEANUP = {**_PROTECTION, 'laser_off': _PROTECTION, 'protect_excitation': _PROTECTION}
_PREFLIGHT = {
    **_PROVENANCE, **dict.fromkeys(('ready', 'laser_enabled', 'gate_output_enabled',
                                  'gate_voltage_zero_verified', 'sine_v_rms', 'contact_mapping')),
    'readout_roles': 'list', 'excluded_readout_roles': 'list',
    'cld': dict.fromkeys(('laser_enabled', 'tec_enabled', 'temperature_c',
                         'temperature_setpoint_c', 'laser_current_a', 'laser_voltage_v')),
    'pm': dict.fromkeys(('out_of_scope', 'range_w', 'wavelength_nm')),
    'chopper': dict.fromkeys(('out_of_scope', 'enable', 'input_hz', 'refout_frequency_hz',
                             'phase_lock_manually_confirmed')),
    'lockin_settings': 'channels',
}
_BUDGET = dict.fromkeys((
    'phase', 'provenance', 'baseline_max_read_s', 'sample_count', 'settle_s', 'interval_s',
    'required_s', 'remaining_run_s', 'remaining_phase_s', 'remaining_effective_s', 'admitted',
))


def _review_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


class _ReviewProjection:
    def __init__(self):
        self.omitted = {}
        self.omitted_count = 0

    def omit(self, path, count=1):
        if count <= 0:
            return
        self.omitted_count += count
        # Paths are schema names only, never arbitrary uploader field names.
        if path in self.omitted or len(self.omitted) < 48:
            self.omitted[path] = self.omitted.get(path, 0) + count

    def scalar(self, value, path):
        if value is None or type(value) is bool:
            return value
        if _review_number(value):
            return value
        if isinstance(value, str):
            encoded = value.encode('utf-8')
            if len(encoded) > 160:
                self.omit(path)
                return encoded[:160].decode('utf-8', errors='ignore')
            return value
        self.omit(path)
        return None

    def select(self, value, schema, path):
        if value is None:
            return None
        if not isinstance(value, dict):
            self.omit(path)
            return None
        self.omit(path + '.unselected_fields', len(value.keys() - schema.keys()))
        selected = {}
        for key, shape in schema.items():
            if key not in value:
                continue
            item = value[key]
            field = path + '.' + key
            if isinstance(shape, dict):
                selected[key] = self.select(item, shape, field)
            elif shape == 'channels':
                selected[key] = self.channels(item, field)
            elif shape == 'list':
                selected[key] = self.records(item, None, field, 4)
            else:
                selected[key] = self.scalar(item, field)
        return selected

    def records(self, values, schema, path, limit):
        if not isinstance(values, list):
            self.omit(path)
            return []
        self.omit(path, len(values) - limit)
        return [(self.select(item, schema, path) if schema is not None
                 else self.scalar(item, path)) for item in values[:limit]]

    def channels(self, values, path):
        if not isinstance(values, dict):
            self.omit(path)
            return {}
        # Known role spellings only; unknown channel identifiers cannot enter prompts.
        selected = {}
        for role in ('xx', 'xy', 'aux', 'pm', 'XX', 'XY', 'AUX', 'PM'):
            if role in values:
                selected[role] = self.select(values[role], _CHANNEL, path + '.role')
        self.omit(path, len(values) - len(selected))
        return selected

    def add(self, snapshot, name, value):
        snapshot[name] = value
        # Reserve ample space for the finite omission ledger.
        if len(json_bytes(snapshot)) > 28000:
            del snapshot[name]
            self.omit(name + '.byte_budget')

    def enrich(self, snapshot, target, name, value, path):
        """Admit optional fields/records after all compact required facts exist."""
        if isinstance(value, list):
            target[name] = []
            if len(json_bytes(snapshot)) > 28000:
                del target[name]
                self.omit(path + '.byte_budget', max(1, len(value)))
                return
            for record in value:
                target[name].append(record)
                if len(json_bytes(snapshot)) > 28000:
                    target[name].pop()
                    self.omit(path + '.byte_budget')
        else:
            target[name] = value
            if len(json_bytes(snapshot)) > 28000:
                del target[name]
                self.omit(path + '.byte_budget')


def review_snapshot(artifact, digest):
    """Finite allowlisted evidence, capped at 32 KiB; original bytes stay downloadable."""
    report = artifact['report']
    if (not isinstance(report.get('samples'), list) or len(report['samples']) > 30
            or any(not isinstance(sample, dict) for sample in report['samples'])
            or not isinstance(report.get('rejected_samples', []), list)
            or report.get('status') not in ('COMPLETED', 'FAILED', 'CANCELLED', 'UNKNOWN')
            or type(report.get('acquisition_complete')) is not bool
            or type(report.get('protection_verified')) is not bool):
        raise ValueError('invalid physical review evidence shape')
    projection = _ReviewProjection()
    snapshot = {
        'central_raw_artifact_verified': True, 'sha256': digest,
        'task_id': projection.scalar(report['task_id'], 'task_id'), 'status': report['status'],
        'acquisition_complete': report['acquisition_complete'],
        'protection_verified': report['protection_verified'],
        'plan': projection.select(report['plan'], dict.fromkeys((
            'sample_id', 'mode', 'reference_hz', 'laser_current_a', 'power_limit_w',
            'excitation_v_rms', 'samples_per_phase', 'interval_s', 'settle_s',
            'phase_timeout_s', 'max_run_s')), 'plan'),
        'error': projection.scalar(report.get('error'), 'error'),
        'close_error_present': 'close_error' in report,
        'interpretation': 'Numerical raw-response summary; no BVPE/nonlinear-Hall attribution or current calibration is implied. Missing readbacks are not inferred from the plan.',
    }
    if 'close_error' in report:
        snapshot['close_error'] = projection.scalar(report['close_error'], 'close_error')
    # Failure records take priority over optional summaries if the byte budget fills.
    snapshot['failure'] = projection.select(report.get('failure'), _FAILURE, 'failure')
    diagnostics = {}
    for moment in ('before_cleanup', 'after_cleanup'):
        source = report.get('device_diagnostics', {})
        if isinstance(source, dict) and moment in source:
            diagnostics[moment] = projection.select(source[moment], {
                'first_acquisition_fault': {
                    'exception_type': None, 'message': None, 'deadline_exhausted': None, 'io': _IO},
                'last_acquisition_io': _IO, 'dropped_count': None,
                'initialization_close_error': None,
            }, 'device_diagnostics.' + moment)
            if isinstance(source[moment], dict) and isinstance(source[moment].get('events'), list):
                count = len(source[moment]['events'])
                diagnostics[moment]['events_omitted_count'] = count
                projection.omit('device_diagnostics.' + moment + '.events', count)
    snapshot['device_diagnostics'] = diagnostics
    timing = report.get('timing')
    if isinstance(timing, dict):
        stages = timing.get('stages', [])
        chosen = []
        if isinstance(stages, list):
            # Preserve failed stages first, then one span per stage/phase, up to 12.
            seen = set()
            for failed in (True, False):
                for stage in stages:
                    if not isinstance(stage, dict) or (stage.get('outcome') == 'failed') != failed:
                        continue
                    key = (str(stage.get('stage'))[:80], str(stage.get('phase'))[:80])
                    if key not in seen and len(chosen) < 12:
                        chosen.append(projection.select(stage, _STAGE, 'timing.stages'))
                        seen.add(key)
            projection.omit('timing.stages', len(stages) - len(chosen))
        else:
            projection.omit('timing.stages')
        summary = projection.select(timing, {'total_elapsed_s': None, 'dropped_count': None}, 'timing')
        summary['stages'] = chosen
        projection.add(snapshot, 'timing', summary)
    optional_details = []
    rejected = report.get('rejected_samples', [])
    snapshot['rejected_sample_count'] = len(rejected)
    snapshot['rejected_samples'] = projection.records(rejected, {
        'phase': None, 'sample_index': None, 'elapsed_s': None, 'reason': None,
        'raw_error': None, 'raw': _PARTIAL,
    }, 'rejected_samples', 4)
    for record in snapshot['rejected_samples']:
        raw = record.get('raw') if isinstance(record, dict) else None
        if not isinstance(raw, dict):
            continue
        for key in tuple(raw):
            if key not in ('power_w', 'laser_current_a', 'laser_enabled', 'elapsed_s',
                           'last_io', 'channels'):
                optional_details.append((raw, key, raw.pop(key), 'rejected_samples.raw.' + key))
        for channel in raw.get('channels', {}).values():
            if not isinstance(channel, dict):
                continue
            for key in tuple(channel):
                if key not in ('x_v', 'y_v'):
                    optional_details.append((channel, key, channel.pop(key),
                                             'rejected_samples.raw.channel_settings'))

    def stats(values):
        if not values:
            return None
        scale = max(abs(value) for value in values)
        mean = (math.fsum(value / scale for value in values) / len(values) * scale
                if scale else 0.0)
        return {'count': len(values), 'mean': mean, 'min': min(values), 'max': max(values)}

    groups = {}
    samples = report['samples']
    for phase in ('dark_baseline', 'illuminated', 'dark_hall_2f', 'dark_a_1f', 'dark_a_2f'):
        phase_samples = [sample for sample in samples if sample.get('phase') == phase]
        if not phase_samples:
            continue
        group = {'sample_count': len(phase_samples), 'channels': {}}
        for key in ('power_w', 'laser_current_a', 'elapsed_s'):
            values = [sample[key] for sample in phase_samples
                      if _review_number(sample.get(key))]
            projection.omit('phase_statistics.' + key,
                            sum(key in sample and not _review_number(sample[key])
                                for sample in phase_samples))
            group[key] = stats(values)
        group['laser_enabled'] = {
            'true_count': sum(sample.get('laser_enabled') is True for sample in phase_samples),
            'false_count': sum(sample.get('laser_enabled') is False for sample in phase_samples),
            'missing_count': sum(type(sample.get('laser_enabled')) is not bool for sample in phase_samples),
        }
        provenance = []
        for sample in phase_samples:
            selected = projection.select(sample, {
                **_PROVENANCE, 'excluded_readout_roles': 'list', 'excluded_device_sessions': 'list',
            }, 'phase_statistics.provenance')
            if selected not in provenance:
                if len(provenance) < 2:
                    provenance.append(selected)
                else:
                    projection.omit('phase_statistics.provenance')
            channels = projection.channels(sample.get('channels', {}), 'phase_statistics.channels')
            for role, channel in channels.items():
                if not isinstance(channel, dict):
                    continue
                entry = group['channels'].setdefault(role, {'x_v': [], 'y_v': [], 'settings': []})
                for key in ('x_v', 'y_v'):
                    value = channel.get(key)
                    if type(value) in (int, float):
                        entry[key].append(value)
                settings = {key: value for key, value in channel.items() if key not in ('x_v', 'y_v')}
                if settings not in entry['settings']:
                    if len(entry['settings']) < 2:
                        entry['settings'].append(settings)
                    else:
                        projection.omit('phase_statistics.channel_settings')
        for channel in group['channels'].values():
            for key in ('x_v', 'y_v'):
                channel[key] = stats(channel[key])
        optional_details.append((group, 'provenance', provenance, 'phase_statistics.provenance'))
        for channel in group['channels'].values():
            optional_details.append((channel, 'settings', channel.pop('settings'),
                                     'phase_statistics.channel_settings'))
        groups[phase] = group
    # Attach every compact phase and rejection record before admitting optional
    # settings/provenance. Optional details must never displace measured facts.
    snapshot['phase_statistics'] = groups
    projection.add(snapshot, 'budget_checks', projection.records(
        report.get('budget_checks', []), _BUDGET, 'budget_checks', 4))
    for target, key, value, path in optional_details:
        projection.enrich(snapshot, target, key, value, path)
    projection.add(snapshot, 'cleanup', projection.records(report.get('cleanup', []), _CLEANUP, 'cleanup', 8))
    projection.add(snapshot, 'preflight', projection.select(report.get('preflight'), _PREFLIGHT, 'preflight'))
    # The section reserve and this ledger cap guarantee the total byte limit.
    ledger_paths_omitted = 0
    while len(json_bytes(projection.omitted)) > 4096:
        projection.omitted.popitem()
        ledger_paths_omitted += 1
    snapshot['omitted_field_paths_omitted_count'] = ledger_paths_omitted
    snapshot.update(snapshot_truncated=bool(projection.omitted_count),
                    omitted_fields=projection.omitted, omitted_count=projection.omitted_count)
    if len(json_bytes(snapshot)) > _REVIEW_BYTES:
        raise ValueError('physical review snapshot exceeds byte budget')
    return snapshot
