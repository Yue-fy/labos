"""Real HTTP boundaries for physical time-series delivery, separate from spectra."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.files import json_bytes


def auth(character):
    return {"Authorization": "Bearer " + character * 40}


def fixture_payload():
    plan = {
        "sample_id": "CrSBr 1",
        "mode": "dark_hall",
        "reference_hz": 8,
        "laser_current_a": None,
        "power_limit_w": None,
        "excitation_v_rms": 0.004,
        "samples_per_phase": 1,
        "interval_s": 0,
        "settle_s": 0,
        "phase_timeout_s": 30,
        "max_run_s": 120,
    }
    # Match canonical model normalization, without importing the store under test.
    for key in [
        "reference_hz",
        "excitation_v_rms",
        "interval_s",
        "settle_s",
        "phase_timeout_s",
        "max_run_s",
    ]:
        plan[key] = float(plan[key])
    digest = hashlib.sha256(json_bytes(plan)).hexdigest()
    report = {
        "status": "COMPLETED",
        "samples": [
            {
                "phase": "dark_hall_2f",
                "channels": {"xy": {"x_v": 1e-8, "y_v": -2e-9, "harmonic": 2}},
            }
        ],
        "cleanup": [
            {"laser_off_verified": True, "minimum_excitation_verified": True, "actual_v_rms": 0.004}
        ],
        "acquisition_complete": True,
        "protection_verified": True,
        "task_id": "pilot-001",
        "plan": plan,
        "config_sha256": "c" * 64,
        "adapter_id": "cryostat_v1",
    }
    return plan, {"message_id": "msg_pilot_001", "plan_sha256": digest, "report": report}


def queue(api, plan):
    r = api.post(
        "/api/agents/pc-a/messages",
        headers=auth("O"),
        json={
            "id": "msg_pilot_001",
            "kind": "note",
            "body": {
                "protocol": "labos-agent-v1",
                "document_type": "labos_pilot_task",
                "task_id": "pilot-001",
                "instruction": "Finite test",
                "pilot_plan": plan,
                "executable": False,
            },
        },
    )
    assert r.status_code == 200


def upload(api, payload, **kwargs):
    data = json_bytes(payload)
    return api.post(
        "/api/agents/pc-a/pilot-artifacts",
        content=data,
        headers={
            **auth("A"),
            "Content-Type": "application/json",
            "X-SHA256": hashlib.sha256(data).hexdigest(),
            **kwargs,
        },
    )


def test_raw_physical_artifact_is_durable_idempotent_and_operator_readable(central_config):
    plan, payload = fixture_payload()
    with TestClient(create_app(central_config)) as api:
        queue(api, plan)
        first = upload(api, payload)
        assert first.status_code == 200, first.text
        assert first.json()["sha256"] == hashlib.sha256(json_bytes(payload)).hexdigest()
        assert upload(api, payload).json() == first.json()
        assert (
            api.get("/api/pilot-artifacts/pc-a/msg_pilot_001", headers=auth("A")).status_code == 403
        )
        assert not api.app.state.store.runs()
    with TestClient(create_app(central_config)) as api:
        loaded = api.get("/api/pilot-artifacts/pc-a/msg_pilot_001", headers=auth("O"))
        assert loaded.status_code == 200
        assert loaded.json() == payload
        assert loaded.json()["report"]["samples"][0]["channels"]["xy"]["harmonic"] == 2
        payload["report"]["samples"][0]["channels"]["xy"]["x_v"] = 0.1
        assert upload(api, payload).status_code == 409
        original = api.get("/api/pilot-artifacts/pc-a/msg_pilot_001", headers=auth("O")).json()
        assert original["report"]["samples"][0]["channels"]["xy"]["x_v"] == 1e-8


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_parent",
        "wrong_plan",
        "wrong_task",
        "wrong_status",
        "credential",
        "nonfinite",
        "not_pilot_task",
        "non_object_sample",
        "non_object_channels",
        "non_object_channel",
        "non_numeric_voltage",
        "non_object_phase",
    ],
)
def test_invalid_artifacts_do_not_become_measurements(central_config, mutation):
    plan, payload = fixture_payload()
    with TestClient(create_app(central_config)) as api:
        queue(api, plan)
        if mutation == "unknown_parent":
            payload["message_id"] = "missing"
        elif mutation == "wrong_plan":
            payload["plan_sha256"] = "d" * 64
        elif mutation == "wrong_task":
            payload["report"]["task_id"] = "other"
        elif mutation == "wrong_status":
            payload["report"]["protection_verified"] = False
        elif mutation == "credential":
            payload["report"]["error"] = "A" * 40
        elif mutation == "nonfinite":
            payload["report"]["samples"][0]["channels"]["xy"]["x_v"] = float("nan")
        elif mutation == "not_pilot_task":
            payload["message_id"] = "ordinary"
            api.post(
                "/api/agents/pc-a/messages",
                headers=auth("O"),
                json={"id": "ordinary", "kind": "note", "body": {"text": "hello"}},
            )
        elif mutation == "non_object_sample":
            payload["report"]["samples"] = [1]
        elif mutation == "non_object_channels":
            payload["report"]["samples"][0]["channels"] = []
        elif mutation == "non_object_channel":
            payload["report"]["samples"][0]["channels"]["xy"] = 1
        elif mutation == "non_numeric_voltage":
            payload["report"]["samples"][0]["channels"]["xy"]["x_v"] = "bad"
        elif mutation == "non_object_phase":
            payload["report"]["samples"][0]["phase"] = []
        data = json.dumps(payload, allow_nan=True).encode()
        r = api.post(
            "/api/agents/pc-a/pilot-artifacts",
            content=data,
            headers={**auth("A"), "X-SHA256": hashlib.sha256(data).hexdigest()},
        )
        expected = 404 if mutation == "unknown_parent" else 409
        assert r.status_code == expected, r.text
        assert not list((central_config.data_dir / "pilot-artifacts").rglob("*.json"))


def test_artifact_auth_and_checksum_limits(central_config):
    plan, payload = fixture_payload()
    data = json_bytes(payload)
    with TestClient(create_app(central_config)) as api:
        queue(api, plan)
        for character, expected in [("B", 403), ("O", 403)]:
            r = api.post(
                "/api/agents/pc-a/pilot-artifacts",
                content=data,
                headers={**auth(character), "X-SHA256": hashlib.sha256(data).hexdigest()},
            )
            assert r.status_code == expected
        assert upload(api, payload, **{"X-SHA256": "0" * 64}).status_code == 409
        r = api.post(
            "/api/agents/pc-a/pilot-artifacts",
            content=b"x" * 2_000_001,
            headers={**auth("A"), "X-SHA256": "0" * 64},
        )
        assert r.status_code == 413


def test_raw_get_preserves_noncanonical_utf8_bytes_and_detects_corruption(central_config):
    from labos.pilot_artifacts import PilotArtifacts

    plan, payload = fixture_payload()
    payload['report']['note'] = 'Mätning 光'
    content = (' \n' + json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode()
    digest = hashlib.sha256(content).hexdigest()
    with TestClient(create_app(central_config)) as api:
        queue(api, plan)
        uploaded = api.post('/api/agents/pc-a/pilot-artifacts', content=content,
                            headers={**auth('A'), 'X-SHA256': digest})
        assert uploaded.status_code == 200
        loaded = api.get('/api/pilot-artifacts/pc-a/msg_pilot_001', headers=auth('O'))
        assert loaded.content == content
        artifacts = PilotArtifacts(api.app.state.store)
        assert artifacts.get('pc-a', 'msg_pilot_001') == payload
        assert artifacts.get_bytes('pc-a', 'msg_pilot_001') == content
        path = central_config.data_dir / 'pilot-artifacts/pc-a/msg_pilot_001.json'
        path.write_bytes(content + b' ')
        assert api.get('/api/pilot-artifacts/pc-a/msg_pilot_001', headers=auth('O')).status_code == 409


@pytest.mark.parametrize('close_error', [None, 'RuntimeError: close failed', 'missing'])
def test_snapshot_retains_actual_current_rejection_first_fault_and_close(close_error):
    from labos.pilot_artifacts import review_snapshot

    _, artifact = fixture_payload()
    report = artifact['report']
    report.update(status='FAILED', acquisition_complete=False,
                  timing={'total_elapsed_s': 4.2, 'stages': [
                      {'stage': 'sample', 'phase': 'illuminated', 'duration_s': 2.0,
                       'outcome': 'failed'}]},
                  failure={'stage': 'sample', 'phase': 'illuminated',
                           'exception_type': 'TimeoutError', 'elapsed_s': 4.0},
                  budget_checks=[{'phase': 'illuminated', 'admitted': True, 'required_s': 2.0}])
    report['samples'] = [{'phase': 'illuminated', 'laser_current_a': 0.0209,
                          'laser_enabled': True, 'elapsed_s': 1.2, 'channels': {},
                          'measurement_plane': 'PM pickoff before sample', 'simulated': False,
                          'sample_current_calibrated': False}]
    io = {'role': 'pm', 'command': 'READ?', 'state': 'requested'}
    report['rejected_samples'] = [{'phase': 'illuminated', 'sample_index': 1,
                                  'reason': 'TimeoutError: PM read timed out', 'elapsed_s': 4.0,
                                  'raw': {'last_io': io, 'channels': {}, 'simulated': False}}]
    report['device_diagnostics'] = {'before_cleanup': {
        'first_acquisition_fault': {'exception_type': 'TimeoutError', 'io': io},
        'last_acquisition_io': io, 'events': [io] * 100}}
    if close_error != 'missing':
        report['close_error'] = close_error
    snapshot = review_snapshot(artifact, 'd' * 64)
    phase = snapshot['phase_statistics']['illuminated']
    assert phase['laser_current_a']['mean'] == 0.0209
    assert phase['laser_enabled'] == {'true_count': 1, 'false_count': 0, 'missing_count': 0}
    assert phase['elapsed_s']['max'] == 1.2
    assert phase['provenance'][0]['sample_current_calibrated'] is False
    assert snapshot['rejected_samples'][0]['raw']['last_io'] == io
    assert snapshot['timing']['total_elapsed_s'] == 4.2
    assert snapshot['failure']['stage'] == 'sample'
    assert snapshot['budget_checks'][0]['admitted'] is True
    assert snapshot['device_diagnostics']['before_cleanup']['first_acquisition_fault']['io'] == io
    assert 'events' not in snapshot['device_diagnostics']['before_cleanup']
    assert snapshot['device_diagnostics']['before_cleanup']['events_omitted_count'] == 100
    assert snapshot['close_error_present'] is (close_error != 'missing')
    if close_error != 'missing':
        assert snapshot['close_error'] == close_error


def test_snapshot_bounds_hostile_nested_evidence_and_extreme_finite_statistics():
    from labos.pilot_artifacts import review_snapshot

    _, artifact = fixture_payload()
    report = artifact['report']
    nested = {'unexpected': '光' * 100000}
    for _ in range(100):
        nested = {'nested': nested}
    report.update(preflight=nested, error='光' * 100000,
                  cleanup=[nested] * 1000, device_diagnostics={'before_cleanup': nested},
                  timing={'stages': [{'stage': 'sample', 'outcome': 'completed'}] * 250 + [
                      {'stage': 'close', 'outcome': 'failed', 'duration_s': 2}],
                      'total_elapsed_s': 10})
    report['samples'] = [{'phase': 'illuminated', 'power_w': 1.7e308,
                          'channels': {'role' + str(i): {'x_v': 1.7e308} for i in range(500)}}
                         for _ in range(2)]
    snapshot = review_snapshot(artifact, 'd' * 64)
    assert len(json_bytes(snapshot)) <= 32768
    assert snapshot == review_snapshot(artifact, 'd' * 64)
    assert snapshot['snapshot_truncated'] is True
    assert snapshot['omitted_fields'] and snapshot['omitted_count'] > 0
    assert snapshot['sha256'] == 'd' * 64
    assert snapshot['status'] == 'COMPLETED' and snapshot['protection_verified'] is True
    assert snapshot['phase_statistics']['illuminated']['power_w']['mean'] == 1.7e308
    assert any(stage['stage'] == 'close' for stage in snapshot['timing']['stages'])


def test_snapshot_omits_integers_outside_finite_statistical_range():
    from labos.pilot_artifacts import review_snapshot

    _, artifact = fixture_payload()
    artifact['report']['samples'][0]['power_w'] = 10 ** 1000
    artifact['report']['error'] = 10 ** 1000
    snapshot = review_snapshot(artifact, 'd' * 64)
    assert snapshot['phase_statistics']['dark_hall_2f']['power_w'] is None
    assert snapshot['error'] is None
    assert snapshot['snapshot_truncated'] is True and snapshot['omitted_count'] >= 2
    assert len(json_bytes(snapshot)) <= 32768


@pytest.mark.parametrize('pressure', ['phase', 'rejected', 'combined'])
def test_snapshot_preserves_compact_required_evidence_under_optional_detail_pressure(pressure):
    from labos.pilot_artifacts import review_snapshot

    _, artifact = fixture_payload()
    report = artifact['report']
    roles = ('xx', 'xy', 'aux', 'pm', 'XX', 'XY', 'AUX', 'PM')
    phases = ('dark_baseline', 'illuminated', 'dark_hall_2f')
    # The upload contract permits bounded status/settings strings. None of these
    # optional fields should displace measured current, power or voltage facts.
    samples = []
    for phase in phases:
        for index in range(2):
            channels = {
                role: {'x_v': 1e-8, 'y_v': -2e-9, **{
                    key: (str(index) + 's' * 159) for key in (
                        'harmonic', 'reference_hz', 'detection_frequency_hz',
                        'time_constant_s', 'lia_status_raw', 'error_status_raw',
                        'current_overload_status_verified',
                    )}}
                for role in roles
            }
            samples.append({
                'phase': phase, 'laser_current_a': 0.0209 if phase == 'illuminated' else 0,
                'laser_enabled': phase == 'illuminated', 'power_w': 4e-7,
                'elapsed_s': 1.25 + index, 'channels': channels,
                'measurement_plane': 'PM pickoff before sample', 'simulated': False,
                'sample_current_calibrated': False,
            })
    report['samples'] = samples if pressure in ('phase', 'combined') else []
    report['timing'] = {'total_elapsed_s': 4.2, 'stages': [
        {'stage': 'sample', 'phase': 'illuminated', 'duration_s': 2, 'outcome': 'failed'}]}
    io = {'role': 'pm', 'command': 'READ?', 'state': 'requested'}
    if pressure in ('rejected', 'combined'):
        report.update(status='FAILED', acquisition_complete=False)
        report['rejected_samples'] = [
            {'phase': 'illuminated', 'sample_index': index, 'elapsed_s': 3.5,
             'reason': 'TimeoutError: PM read timed out',
             'raw': {**samples[index], 'last_io': io}}
            for index in range(4)
        ]
    snapshot = review_snapshot(artifact, 'd' * 64)
    assert len(json_bytes(snapshot)) <= 32768
    assert snapshot['snapshot_truncated'] is True and snapshot['omitted_count'] > 0
    assert snapshot['sha256'] == 'd' * 64 and snapshot['protection_verified'] is True
    assert snapshot['timing']['total_elapsed_s'] == 4.2
    assert snapshot['timing']['stages'][0]['stage'] == 'sample'
    if pressure in ('phase', 'combined'):
        assert set(snapshot['phase_statistics']) == set(phases)
        for phase in phases:
            group = snapshot['phase_statistics'][phase]
            assert group['laser_current_a']['mean'] == (0.0209 if phase == 'illuminated' else 0)
            assert group['laser_enabled']['true_count'] == (2 if phase == 'illuminated' else 0)
            assert group['power_w']['mean'] == 4e-7
            assert group['elapsed_s']['max'] == 2.25
            for role in roles:
                assert group['channels'][role]['x_v']['mean'] == 1e-8
                assert group['channels'][role]['y_v']['mean'] == -2e-9
    if pressure in ('rejected', 'combined'):
        assert len(snapshot['rejected_samples']) == 4
        for index, rejected in enumerate(snapshot['rejected_samples']):
            assert rejected['phase'] == 'illuminated' and rejected['sample_index'] == index
            assert rejected['reason'] == 'TimeoutError: PM read timed out'
            assert rejected['raw']['last_io'] == io
            assert rejected['raw']['channels']['xx']['x_v'] == 1e-8
