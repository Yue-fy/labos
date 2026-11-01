"""Offline authority integration: temporary SQLite and fake instruments only."""
import hashlib
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.files import json_bytes
from labos.pilot import PilotPlan
from test_pilot_worker import approval, configuration, module, send, task, transport, SimulatedBench

ADMIN = {'Authorization': 'Bearer ' + 'O' * 40}
AGENT = {'Authorization': 'Bearer ' + 'A' * 40}
CLAIMS = '/api/agents/pc-a/pilot-claims'
OPERATOR = '/api/pilot-authority/pc-a'


def commission(api, config_hash, scope='optical_transport'):
    return api.post(OPERATOR + '/commission', headers=ADMIN, json={
        'config_sha256': config_hash, 'experiment_scope': scope,
        'note': 'Offline fixture: legacy workers retired and states reconciled.',
        'legacy_workers_retired': True, 'physical_states_reconciled': True})


def claim(message, config_hash, **changes):
    return {'message_id': message['id'], 'task_id': message['body']['task_id'],
            'plan_sha256': hashlib.sha256(json_bytes(PilotPlan.model_validate(
                message['body']['pilot_plan']).model_dump(mode='json'))).hexdigest(),
            'config_sha256': config_hash, 'experiment_scope': 'optical_transport',
            'attempt_nonce': uuid.uuid4().hex, **changes}


def physical_task(task_id='pilot_1'):
    return task(task_id, experiment_scope='optical_transport')


def test_uncommissioned_and_old_endpoint_never_construct(tmp_path, central_config):
    calls = []
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api),
                                      lambda _: calls.append(True) or SimulatedBench())
        message = send(api, 'm1', physical_task())
        result = worker.respond(message, {})
        assert calls == []
        assert result['answer']['status'] == 'needs_input'
        assert 'pilot_result' not in result
        assert not list(worker.config.state_dir.glob('artifacts/*'))
        worker.client.close()


def test_claim_consumed_once_and_cross_profile_gate(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        assert commission(api, '1' * 64).status_code == 200
        message = send(api, 'm1', physical_task())
        request = claim(message, '1' * 64)
        grant = api.post(CLAIMS, headers=AGENT, json=request)
        assert grant.status_code == 200
        assert grant.json() == {'granted': True, 'agent_id': 'pc-a', **request}
        assert api.post(CLAIMS, headers=AGENT, json=request).json()['granted'] is False
        assert commission(api, '2' * 64).status_code == 409
        other = send(api, 'm2', physical_task('pilot_2'))
        assert api.post(CLAIMS, headers=AGENT, json=claim(other, '2' * 64)).json()['granted'] is False
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is True


def test_retirement_includes_no_artifact_and_reused_task_ids(central_config):
    with TestClient(create_app(central_config)) as api:
        old = send(api, 'old', physical_task())
        assert commission(api, '1' * 64).status_code == 200
        new = send(api, 'new', physical_task())
        for message in (old, new):
            response = api.post(CLAIMS, headers=AGENT, json=claim(message, '1' * 64))
            assert response.json()['granted'] is False
        fresh = send(api, 'fresh', physical_task('fresh'))
        assert api.post(CLAIMS, headers=AGENT, json=claim(fresh, '1' * 64)).json()['granted'] is True


@pytest.mark.parametrize('token', ['O', 'B'])
def test_execution_grants_are_only_for_own_agent(central_config, token):
    with TestClient(create_app(central_config)) as api:
        for method in ('get', 'post'):
            response = getattr(api, method)(CLAIMS, headers={'Authorization': 'Bearer ' + token * 40})
            assert response.status_code == 403


def test_lost_receipt_latches_without_artifact_or_factory(tmp_path, central_config):
    calls = []
    with TestClient(create_app(central_config)) as api:
        def drop(req):
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            if req.url.path == CLAIMS and req.method == 'POST':
                raise httpx.ReadTimeout('committed grant receipt lost')
            return httpx.Response(response.status_code, content=response.content)
        config = configuration(tmp_path, approval=approval())
        worker = module().PilotWorker(config, httpx.MockTransport(drop),
                                      lambda _: calls.append(True) or SimulatedBench())
        assert commission(api, worker.config_sha256).status_code == 200
        message = send(api, 'm1', physical_task())
        result = worker.respond(message, {})
        assert result['answer']['status'] == 'needs_input'
        assert calls == [] and 'pilot_result' not in result
        worker.client.close()
        restarted = module().PilotWorker(config, transport(api), lambda _: calls.append(True))
        assert restarted.respond(message, {}) == result
        assert calls == [] and restarted.status()['physical_blocked'] is True
        assert not list(config.state_dir.glob('artifacts/*'))
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is True
        restarted.client.close()


def upload(api, worker, result):
    details = result['pilot_result']['artifact']
    content = (worker.config.state_dir / details['path']).read_bytes()
    return api.post('/api/agents/pc-a/pilot-artifacts', headers={**AGENT, 'X-SHA256': details['sha256']}, content=content)


class ProtectedBench(SimulatedBench):
    def laser_off(self):
        return {**super().laser_off(), 'emission_off_readback': True,
                'zero_current_setpoint_verified': True}


def test_two_profiles_sequential_duplicate_and_finished_retry(tmp_path, central_config):
    counts = []
    with TestClient(create_app(central_config)) as api:
        first = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api),
                                     lambda _: counts.append('first') or ProtectedBench())
        second_config = first.config.model_copy(deep=True)
        second_config.state_dir = tmp_path / 'separate-profile'
        second = module().PilotWorker(second_config, transport(api),
                                      lambda _: counts.append('second') or ProtectedBench())
        assert first.config_sha256 != second.config_sha256
        assert commission(api, first.config_sha256).status_code == 200
        message = send(api, 'm1', physical_task())
        completed = first.respond(message, {})
        denied = second.respond(message, {})
        assert denied['answer']['status'] == 'needs_input' and 'pilot_result' not in denied
        assert counts == ['first']
        assert upload(api, first, completed).status_code == 200
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is False
        assert commission(api, second.config_sha256).status_code == 200
        # Config selection does not provide a new task identity namespace.
        reused = send(api, 'reuse', physical_task())
        assert api.post(CLAIMS, headers=AGENT, json=claim(reused, second.config_sha256)).json()['granted'] is False
        assert first.respond(message, {}) == completed
        second.client.close()
        restarted = module().PilotWorker(second_config, transport(api), lambda _: counts.append('restart'))
        assert restarted.respond(message, {}) == denied
        assert counts == ['first'] and not list(second_config.state_dir.glob('artifacts/*'))
        first.client.close()
        restarted.client.close()


def test_terminal_artifact_retry_cannot_clear_later_claim(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: ProtectedBench())
        assert commission(api, worker.config_sha256).status_code == 200
        first = send(api, 'm1', physical_task())
        result = worker.respond(first, {})
        assert upload(api, worker, result).status_code == 200
        second = send(api, 'm2', physical_task('pilot_2'))
        assert api.post(CLAIMS, headers=AGENT, json=claim(second, worker.config_sha256)).json()['granted'] is True
        assert upload(api, worker, result).status_code == 200
        third = send(api, 'm3', physical_task('pilot_3'))
        assert api.post(CLAIMS, headers=AGENT, json=claim(third, worker.config_sha256)).json()['granted'] is False
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is True
        worker.client.close()


@pytest.mark.parametrize('damage', ['missing_close', 'close_error', 'empty', 'missing_final',
                                    'zero_missing', 'off_missing', 'excitation', 'truthy', 'unknown'])
def test_invalid_final_evidence_keeps_gate(tmp_path, central_config, damage):
    import json
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: ProtectedBench())
        assert commission(api, worker.config_sha256).status_code == 200
        message = send(api, 'm1', physical_task())
        result = worker.respond(message, {})
        document = json.loads((worker.config.state_dir / result['pilot_result']['artifact']['path']).read_bytes())
        report = document['report']
        if damage == 'missing_close':
            report.pop('close_error')
        elif damage == 'close_error':
            report['close_error'] = 'Close failed'
        elif damage == 'empty':
            report['cleanup'] = []
        elif damage == 'missing_final':
            report['cleanup'].pop()
        elif damage == 'zero_missing':
            report['cleanup'][-1]['laser_off'].pop('zero_current_setpoint_verified')
        elif damage == 'off_missing':
            report['cleanup'][-1]['laser_off'].pop('emission_off_readback')
        elif damage == 'excitation':
            report['cleanup'][-1]['protect_excitation']['actual_v_rms'] = '0.004'
        elif damage == 'truthy':
            report['cleanup'][-1]['verified'] = 1
        else:
            report['status'] = 'UNKNOWN'
        content = json_bytes(document)
        response = api.post('/api/agents/pc-a/pilot-artifacts', headers={**AGENT, 'X-SHA256': hashlib.sha256(content).hexdigest()}, content=content)
        assert response.status_code == 200
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is True
        assert commission(api, '2' * 64).status_code == 409
        worker.client.close()


@pytest.mark.parametrize('failure', ['404', '403', 'oversized', 'nonobject', 'wrong_nonce', 'truthy'])
def test_bad_claim_receipts_never_construct(tmp_path, central_config, failure):
    calls = []
    with TestClient(create_app(central_config)) as api:
        def corrupt(req):
            if req.method == 'POST' and req.url.path == CLAIMS:
                if failure in {'404', '403'}:
                    return httpx.Response(int(failure))
                if failure == 'oversized':
                    return httpx.Response(413)
                response = api.post(CLAIMS, headers=AGENT, content=req.content)
                receipt = response.json()
                if failure == 'nonobject':
                    receipt = []
                elif failure == 'truthy':
                    receipt['granted'] = 1
                else:
                    receipt['attempt_nonce'] = '0' * 32
                return httpx.Response(200, json=receipt)
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content)
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), httpx.MockTransport(corrupt), lambda _: calls.append(True))
        assert commission(api, worker.config_sha256).status_code == 200
        message = send(api, 'm1', physical_task())
        assert 'pilot_result' not in worker.respond(message, {})
        assert calls == []
        assert worker.status()['physical_blocked'] is True
        worker.client.close()


def test_frozen_snapshot_controls_factory_approval_and_doctor(tmp_path, central_config):
    settings = []
    config = configuration(tmp_path, approval=approval())
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(config, transport(api), lambda value: settings.append(value) or ProtectedBench())
        assert commission(api, worker.config_sha256).status_code == 200
        config.adapter_config['experiment_scope'] = 'dark_a'
        worker.config.adapter_config['experiment_scope'] = 'dark_a'
        worker.config.approval = None
        readiness = worker.doctor()
        assert readiness['authority_ready'] is True
        assert readiness['physical_enabled'] is False
        message = send(api, 'm1', physical_task())
        assert worker.respond(message, {})['pilot_result']['status'] == 'COMPLETED'
        assert settings == [{}]
        assert worker.doctor()['authority_ready'] is False
        worker.client.close()


def test_claim_schema_and_commission_acknowledgments(central_config):
    with TestClient(create_app(central_config)) as api:
        assert api.post(CLAIMS, headers=AGENT, content=b'x' * 4097).status_code == 413
        assert api.post(CLAIMS, headers=AGENT, json={}).status_code == 422
        for value in (False, 'true', 1):
            body = {'config_sha256': '1' * 64, 'experiment_scope': 'dark_a', 'note': 'Offline test',
                    'legacy_workers_retired': value, 'physical_states_reconciled': True}
            assert api.post(OPERATOR + '/commission', headers=ADMIN, json=body).status_code in {409, 422}
            assert api.post(OPERATOR + '/commission', headers=AGENT, json=body).status_code == 403


@pytest.mark.parametrize('same_task', [True, False])
def test_concurrent_claims_grant_one_attempt(central_config, same_task):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    with TestClient(create_app(central_config)) as api:
        assert commission(api, '1' * 64).status_code == 200
        a = send(api, 'a', physical_task('a'))
        b = a if same_task else send(api, 'b', physical_task('b'))
        barrier = threading.Barrier(2)
        def request(message):
            barrier.wait()
            return api.post(CLAIMS, headers=AGENT, json=claim(message, '1' * 64)).json()['granted']
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(request, [a, b]))
        assert sorted(results) == [False, True]


def test_selection_and_claim_serialize(central_config):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    with TestClient(create_app(central_config)) as api:
        assert commission(api, '1' * 64).status_code == 200
        message = send(api, 'a', physical_task('a'))
        barrier = threading.Barrier(2)
        def select():
            barrier.wait()
            return commission(api, '2' * 64).status_code
        def execute():
            barrier.wait()
            return api.post(CLAIMS, headers=AGENT, json=claim(message, '1' * 64)).json()['granted']
        with ThreadPoolExecutor(2) as pool:
            selected, claimed = pool.submit(select), pool.submit(execute)
            assert (selected.result(), claimed.result()) in {(200, False), (409, True)}


def test_unknown_from_one_profile_blocks_other_profile_task(tmp_path, central_config):
    calls = []
    with TestClient(create_app(central_config)) as api:
        first = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api),
                                     lambda _: calls.append('first') or SimulatedBench(protection_ok=False))
        other_config = first.config.model_copy(deep=True)
        other_config.state_dir = tmp_path / 'other'
        second = module().PilotWorker(other_config, transport(api), lambda _: calls.append('second'))
        assert commission(api, first.config_sha256).status_code == 200
        result = first.respond(send(api, 'a', physical_task('a')), {})
        assert result['pilot_result']['status'] == 'UNKNOWN'
        assert upload(api, first, result).status_code == 200
        denied = second.respond(send(api, 'b', physical_task('b')), {})
        assert denied['answer']['status'] == 'needs_input' and 'pilot_result' not in denied
        assert calls == ['first']
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is True
        first.client.close()
        second.client.close()


@pytest.mark.parametrize('same_task', [True, False])
def test_two_workers_racing_count_real_factories(tmp_path, central_config, same_task):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    calls = []
    with TestClient(create_app(central_config)) as api:
        config = configuration(tmp_path, approval=approval())
        first = module().PilotWorker(config, transport(api), lambda _: calls.append('first') or ProtectedBench())
        second_config = config.model_copy(deep=True)
        second_config.state_dir = tmp_path / 'other'
        second = module().PilotWorker(second_config, transport(api), lambda _: calls.append('second') or ProtectedBench())
        assert commission(api, first.config_sha256).status_code == 200
        a = send(api, 'a', physical_task('a'))
        b = a if same_task else send(api, 'b', physical_task('b'))
        barrier = threading.Barrier(2)
        def run(pair):
            worker, message = pair
            barrier.wait()
            return worker.respond(message, {})
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(run, [(first, a), (second, b)]))
        assert calls == ['first']
        assert sum('pilot_result' in result for result in results) == 1
        first.client.close()
        second.client.close()


def test_intent_and_nonce_commit_before_request_and_restart_never_claims(tmp_path, central_config):
    import sqlite3
    calls = []
    config = configuration(tmp_path, approval=approval())
    with TestClient(create_app(central_config)) as api:
        def die(req):
            if req.url.path == CLAIMS:
                with sqlite3.connect(config.state_dir / 'physical.sqlite') as db:
                    assert db.execute("SELECT state FROM executions").fetchone() == ('intent',)
                    assert len(db.execute('SELECT nonce FROM authority_attempts').fetchone()[0]) == 32
                raise KeyboardInterrupt
            raise AssertionError('unexpected request')
        worker = module().PilotWorker(config, httpx.MockTransport(die), lambda _: calls.append(True))
        assert commission(api, worker.config_sha256).status_code == 200
        message = send(api, 'a', physical_task('a'))
        with pytest.raises(KeyboardInterrupt):
            worker.respond(message, {})
        worker.client.close()
        restarted = module().PilotWorker(config, httpx.MockTransport(die), lambda _: calls.append(True))
        assert restarted.respond(message, {})['answer']['status'] == 'needs_input'
        assert calls == [] and restarted.status()['physical_blocked'] is True
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is False
        restarted.client.close()


def test_doctor_requires_exact_selection_and_no_local_latch(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: pytest.fail('Doctor factory'))
        assert worker.doctor()['authority_ready'] is False
        assert commission(api, worker.config_sha256, 'dark_a').status_code == 200
        assert worker.doctor()['authority_ready'] is False
        assert commission(api, worker.config_sha256).status_code == 200
        assert worker.doctor()['authority_ready'] is True
        with worker.physical_db() as db:
            worker._latch(db, 'old')
        result = worker.doctor()
        assert result['authority_ready'] is False and result['physical_blocked'] is True
        assert result['physical_enabled'] is False
        worker.client.close()


def test_claim_bound_artifact_identity_is_atomic(tmp_path, central_config):
    import json
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: ProtectedBench())
        assert commission(api, worker.config_sha256).status_code == 200
        result = worker.respond(send(api, 'a', physical_task('a')), {})
        raw = (worker.config.state_dir / result['pilot_result']['artifact']['path']).read_bytes()
        for field in ('attempt_nonce', 'config_sha256', 'experiment_scope'):
            doc = json.loads(raw)
            if field == 'attempt_nonce':
                doc[field] = '0' * 32
            else:
                doc['report'][field] = 'wrong'
            content = json_bytes(doc)
            response = api.post('/api/agents/pc-a/pilot-artifacts', headers={**AGENT, 'X-SHA256': hashlib.sha256(content).hexdigest()}, content=content)
            assert response.status_code == 409
            assert api.get('/api/pilot-artifacts/pc-a/a', headers=ADMIN).status_code == 404
            assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is True
        assert upload(api, worker, result).status_code == 200
        worker.client.close()


def test_operator_cli_commission_and_status_use_bounded_api(monkeypatch, tmp_path, central_config, capsys):
    from labos import cli
    config = configuration(tmp_path, approval=approval())
    path = tmp_path / 'worker.json'
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        monkeypatch.setattr(cli, 'operator_client', lambda *_: httpx.Client(
            base_url='http://localhost:8000', headers=ADMIN, transport=transport(api)))
        args = ['pilot-authority', 'commission', '--config', 'unused', '--agent-id', 'pc-a',
                '--worker-config', str(path), '--note', 'Offline test attestation',
                '--legacy-workers-retired', '--physical-states-reconciled']
        assert cli.main(args) == 0
        assert api.get(CLAIMS, headers=AGENT).json()['commissioned'] is True
        assert cli.main(['pilot-authority', 'status', '--config', 'unused', '--agent-id', 'pc-a']) == 0
        assert 'commissioned' in capsys.readouterr().out


def test_consumed_nonce_cannot_authorize_a_different_task(tmp_path, central_config):
    import json
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: ProtectedBench())
        assert commission(api, worker.config_sha256).status_code == 200
        result = worker.respond(send(api, 'a', physical_task('a')), {})
        nonce = json.loads((worker.config.state_dir / result['pilot_result']['artifact']['path']).read_bytes())['attempt_nonce']
        assert upload(api, worker, result).status_code == 200
        b = send(api, 'b', physical_task('b'))
        assert api.post(CLAIMS, headers=AGENT, json=claim(b, worker.config_sha256, attempt_nonce=nonce)).json()['granted'] is False
        worker.client.close()


@pytest.mark.parametrize('status', ['FAILED', 'CANCELLED'])
def test_failed_or_cancelled_with_independent_cleanup_and_close_release(tmp_path, central_config, status):
    import json
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), transport(api), lambda _: ProtectedBench())
        assert commission(api, worker.config_sha256).status_code == 200
        result = worker.respond(send(api, 'a', physical_task('a')), {})
        doc = json.loads((worker.config.state_dir / result['pilot_result']['artifact']['path']).read_bytes())
        doc['report'].update(status=status, acquisition_complete=False)
        content = json_bytes(doc)
        response = api.post('/api/agents/pc-a/pilot-artifacts', headers={**AGENT, 'X-SHA256': hashlib.sha256(content).hexdigest()}, content=content)
        assert response.status_code == 200
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is False
        worker.client.close()


def test_historical_unclaimed_artifact_cannot_clear_active_gate(central_config):
    from test_pilot_artifacts import fixture_payload, queue, upload as historical_upload
    with TestClient(create_app(central_config)) as api:
        plan, payload = fixture_payload()
        queue(api, plan)
        assert commission(api, '1' * 64).status_code == 200
        message = send(api, 'new', physical_task('new'))
        assert api.post(CLAIMS, headers=AGENT, json=claim(message, '1' * 64)).json()['granted'] is True
        assert historical_upload(api, payload).status_code == 200
        assert api.get('/api/pilot-artifacts/pc-a/msg_pilot_001', headers=ADMIN).json() == payload
        assert api.get(CLAIMS, headers=AGENT).json()['blocked'] is True


@pytest.mark.parametrize('change', ['scope_missing', 'scope_wrong', 'plan_wrong', 'task_wrong', 'pc_origin'])
def test_claim_requires_exact_central_task_and_scope(central_config, change):
    with TestClient(create_app(central_config)) as api:
        assert commission(api, '1' * 64).status_code == 200
        body = physical_task()
        if change == 'scope_missing':
            body.pop('experiment_scope')
        elif change == 'scope_wrong':
            body['experiment_scope'] = 'dark_a'
        if change == 'pc_origin':
            response = api.post('/api/agents/pc-a/messages', headers=AGENT,
                                json={'id': 'm', 'kind': 'note', 'body': body})
            message = response.json()['message']
        else:
            message = send(api, 'm', body)
        request = claim(message, '1' * 64)
        if change == 'plan_wrong':
            request['plan_sha256'] = '0' * 64
        elif change == 'task_wrong':
            request['task_id'] = 'other'
        assert api.post(CLAIMS, headers=AGENT, json=request).json()['granted'] is False


def test_doctor_old_endpoint_stays_not_ready_without_io(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        def old_server(req):
            if req.url.path == CLAIMS:
                return httpx.Response(404)
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content)
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), httpx.MockTransport(old_server), lambda _: pytest.fail('Doctor performed I/O'))
        assert worker.doctor()['authority_ready'] is False
        assert worker.doctor()['physical_enabled'] is False
        worker.client.close()


def test_finished_legacy_scopeless_result_delivers_without_new_claim(tmp_path):
    import json
    calls = []
    config = configuration(tmp_path, approval=approval())
    def forbidden(req):
        raise AssertionError('Recovery requested a new grant')
    worker = module().PilotWorker(config, httpx.MockTransport(forbidden), lambda _: calls.append(True))
    body = physical_task()
    body.pop('experiment_scope')
    message = {'id': 'legacy', 'body': body}
    digest = claim(message, worker.config_sha256)['plan_sha256']
    result = {'backend': 'pilot', 'pilot_result': {'status': 'COMPLETED', 'legacy': True}}
    with worker.physical_db() as db:
        db.execute("INSERT INTO executions VALUES(?,?,?,?, 'finished',?)",
                   (body['task_id'], message['id'], digest, worker.config_sha256, json.dumps(result)))
    assert worker.eligible(message) is True
    assert worker.respond(message, {}) == result
    assert calls == []
    worker.client.close()


def test_partial_authority_table_loss_cannot_recreate_clean_history(central_config):
    import sqlite3
    with TestClient(create_app(central_config)) as api:
        assert commission(api, '1' * 64).status_code == 200
        message = send(api, 'a', physical_task('a'))
        assert api.post(CLAIMS, headers=AGENT, json=claim(message, '1' * 64)).json()['granted'] is True
    with sqlite3.connect(central_config.data_dir / 'central.sqlite') as db:
        db.execute('DROP TABLE pilot_claims')
    with pytest.raises(ValueError, match='reconciliation'):
        create_app(central_config)


@pytest.mark.parametrize('selection', ['selected', 'uncommissioned', 'mismatched', 'blocked', 'old_endpoint', 'disabled'])
def test_runtime_poll_observes_authority_without_factory(tmp_path, central_config, selection):
    calls, requests = [], []
    with TestClient(create_app(central_config)) as api:
        def observe(req):
            requests.append((req.method, req.url.path))
            if selection == 'old_endpoint' and req.url.path == CLAIMS:
                return httpx.Response(404)
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content)
        worker = module().PilotWorker(configuration(tmp_path, approval=approval(enabled=selection != 'disabled')),
                                      httpx.MockTransport(observe), lambda _: calls.append(True))
        if selection not in {'uncommissioned', 'old_endpoint'}:
            digest = '0' * 64 if selection == 'mismatched' else worker.config_sha256
            assert commission(api, digest).status_code == 200
        if selection == 'blocked':
            message = send(api, 'other', physical_task('other'))
            assert api.post(CLAIMS, headers=AGENT, json=claim(message, worker.config_sha256)).json()['granted'] is True
        snapshot = worker.tick()
        assert ('GET', CLAIMS) in requests
        assert ('GET', '/api/agents/pc-a/messages') in requests
        assert snapshot['authority_ready'] is (selection == 'selected')
        assert snapshot['physical_enabled'] is (selection == 'selected')
        assert snapshot['authority_checked_at_utc'].endswith('Z')
        assert snapshot['snapshot_only'] is True
        assert calls == []
        worker.client.close()


def test_runtime_poll_invalidates_previous_selection_and_observers_do_not_fetch(tmp_path, central_config):
    requests = []
    with TestClient(create_app(central_config)) as api:
        def observe(req):
            requests.append((req.method, req.url.path))
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content)
        worker = module().PilotWorker(configuration(tmp_path, approval=approval()), httpx.MockTransport(observe),
                                      lambda _: pytest.fail('Readiness constructed adapter'))
        assert commission(api, worker.config_sha256).status_code == 200
        assert worker.tick()['physical_enabled'] is True
        assert commission(api, '0' * 64).status_code == 200
        assert worker.tick()['physical_enabled'] is False
        before = list(requests)
        worker._observe_engine({'stage': 'close', 'outcome': 'completed'})
        worker.write_status('stopped')
        assert requests == before
        worker.client.close()


def test_runtime_startup_checks_before_started_without_loading_factory(tmp_path, central_config, monkeypatch):
    import sys
    import types
    fake = types.ModuleType('labos.cryostat_pilot')
    validations = []
    fake.validate_adapter_config = lambda settings: validations.append(settings)
    fake.create_adapter = lambda settings: pytest.fail('Startup constructed adapter')
    monkeypatch.setitem(sys.modules, 'labos.cryostat_pilot', fake)
    config = configuration(tmp_path, approval=approval())
    path = tmp_path / 'worker.json'
    path.write_text(config.model_dump_json())
    with TestClient(create_app(central_config)) as api:
        worker = module().PilotWorker(config, transport(api))
        assert commission(api, worker.config_sha256).status_code == 200
        monkeypatch.setattr(module(), 'PilotWorker', lambda _: worker)
        original = worker.write_status
        started = []
        def write(phase):
            result = original(phase)
            if phase == 'started':
                started.append(result)
            return result
        monkeypatch.setattr(worker, 'write_status', write)
        assert module().main(['once', '--config', str(path)]) == 0
        assert started[0]['authority_ready'] is True
        assert started[0]['physical_enabled'] is True
        assert validations


def test_runtime_legacy_finished_delivery_survives_missing_authority(tmp_path, central_config):
    import json
    from test_pilot_artifacts import fixture_payload, queue
    requests = []
    with TestClient(create_app(central_config)) as api:
        plan, payload = fixture_payload()
        queue(api, plan)  # Historical task deliberately has no experiment_scope.
        def old_server(req):
            requests.append((req.method, req.url.path))
            if req.url.path == CLAIMS:
                return httpx.Response(404)
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content)
        worker = module().PilotWorker(configuration(tmp_path), httpx.MockTransport(old_server),
                                      lambda _: pytest.fail('Legacy delivery constructed adapter'))
        content = json_bytes(payload)
        digest = hashlib.sha256(content).hexdigest()
        relative = 'artifacts/legacy.json'
        artifact_path = worker.config.state_dir / relative
        artifact_path.parent.mkdir()
        artifact_path.write_bytes(content)
        result = {'backend': 'pilot', 'answer': {'status': 'completed', 'summary': 'Original legacy result',
                  'findings': [], 'questions': []}, 'pilot_result': {'status': 'COMPLETED',
                  'artifact': {'path': relative, 'sha256': digest, 'message_id': payload['message_id']}}}
        with worker.physical_db() as db:
            db.execute("INSERT INTO executions VALUES(?,?,?,?, 'finished',?)",
                       (payload['report']['task_id'], payload['message_id'], payload['plan_sha256'],
                        payload['report']['config_sha256'], json.dumps(result)))
        snapshot = worker.tick()
        assert snapshot['authority_ready'] is False and snapshot['physical_enabled'] is False
        assert snapshot['counts'] == {'sent': 1}
        delivered = api.get('/api/agents/pc-a/messages', headers=ADMIN).json()['messages'][-1]['body']
        assert delivered['pilot_result'] == result['pilot_result']
        assert delivered['answer'] == result['answer']
        assert api.get('/api/pilot-artifacts/pc-a/' + payload['message_id'], headers=ADMIN).content == content
        assert ('GET', CLAIMS) in requests and ('POST', CLAIMS) not in requests
        assert artifact_path.read_bytes() == content
        worker.client.close()
