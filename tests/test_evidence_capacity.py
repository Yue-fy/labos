"""Offline evidence capacity boundaries; no hardware or model access."""

import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.cooperation import Message
from labos.cooperation_worker import Result, Worker
from labos.files import json_bytes
from test_cooperation_worker import Reports, bridge, connection
from test_pilot_worker import (
    SimulatedBench, approval, commission_profile, configuration, messages, module, plan, send, task,
)


class ForbiddenReviewer:
    def respond(self, message, context):
        raise AssertionError('Known unavailable raw evidence must not consume inference')


def test_aggregate_oversize_raw_is_local_and_claim_stays_blocked_after_restart(tmp_path, central_config):
    class LargeBench(SimulatedBench):
        def read_sample(self, phase):
            return {**super().read_sample(phase), 'raw_trace': 'x' * 65_000}

        def preflight(self):
            return {**super().preflight(), 'raw_identity': 'p' * 60_000}

    bench = LargeBench()
    config = configuration(tmp_path, approval=approval())
    requests = []
    with TestClient(create_app(central_config)) as api:
        def request(req):
            requests.append((req.method, req.url.path))
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        commission_profile(api, config)
        send(api, 'capacity_task', task(pilot_plan=plan(samples_per_phase=10)))
        worker = module().PilotWorker(config, httpx.MockTransport(request), lambda _: bench)
        worker.tick()
        received = messages(api)
        assert len(received) == 2
        body = received[-1]['body']
        details = body['pilot_result']
        assert body['answer']['status'] == 'failed'
        assert body['model_attempts'] == 0
        assert details['artifact']['availability'] == 'local_only'
        assert details['evidence_delivery']['reason'] == 'raw_artifact_exceeds_capacity'
        assert details['evidence_delivery']['central_raw_artifact_verified'] is False
        content = (config.state_dir / details['artifact']['path']).read_bytes()
        assert len(content) > 2_000_000
        assert hashlib.sha256(content).hexdigest() == details['artifact']['sha256']
        saved = json.loads(content)
        assert len(saved['report']['samples']) == 30
        assert all(len(sample['raw_trace']) == 65_000 for sample in saved['report']['samples'])
        with worker.physical_db() as db:
            assert db.execute('SELECT state FROM executions').fetchone()[0] == 'finished'
        assert not any(method == 'POST' and path.endswith('/pilot-artifacts') for method, path in requests)

        def forbidden(_):
            raise AssertionError('Finished execution must never create a new adapter')

        restarted = module().PilotWorker(config, httpx.MockTransport(request), forbidden)
        for _ in range(3):
            restarted.tick()
        assert bench.events.count('open') == 1
        assert (config.state_dir / details['artifact']['path']).read_bytes() == content
        reviewer = Worker(connection(tmp_path, central_config, 'central'), httpx.MockTransport(request), ForbiddenReviewer())
        reviewer.tick()
        review = messages(api)[-1]['body']
        assert review['document_type'] == 'labos_auto_review'
        assert review['answer']['status'] == 'failed'
        assert review['model_attempts'] == 0
        assert not any(method == 'GET' and '/pilot-artifacts/' in path for method, path in requests)
        with reviewer.db() as db:
            assert db.execute("SELECT attempts FROM inbox WHERE state='sent'").fetchone()[0] == 0
        # A diagnostic correspondence report cannot finalize the outstanding physical claim.
        send(api, 'next_capacity_task', task(task_id='next_task'))
        restarted.tick()
        restarted.tick()
        assert messages(api)[-1]['body']['answer']['status'] == 'needs_input'
        assert api.get('/api/agents/pc-a/pilot-claims', headers={'Authorization': 'Bearer ' + 'A' * 40}).json()['blocked'] is True


@pytest.mark.parametrize('field', ['source_evidence', 'pilot_result'])
@pytest.mark.parametrize('text', ['x' * 90_000, '光\\"\n' * 18_000], ids=['ascii', 'unicode_escaped'])
def test_full_envelope_fallback_bounds_attached_evidence(tmp_path, central_config, monkeypatch, field, text):
    original = {'content': text}

    class LargeReport(Reports):
        def respond(self, message, context):
            generated = super().respond(message, context)
            if field == 'pilot_result':
                generated['pilot_result'] = {**original, 'artifact': {
                    'message_id': 'large_metadata', 'sha256': 'b' * 64, 'path': 'artifacts/local.json'},
                    'plan_sha256': 'c' * 64, 'config_sha256': 'd' * 64}
            return generated

    with TestClient(create_app(central_config)) as api:
        body = task() if field == 'pilot_result' else {
            'protocol': 'labos-agent-v1', 'document_type': 'labos_auto_task',
            'task_id': 'metadata', 'instruction': 'Review supplied evidence.',
            'context': {'source_requests': []}, 'executable': False}
        # A report-only worker may carry pilot metadata but does not execute the task.
        if field == 'pilot_result':
            body['document_type'] = 'labos_auto_task'
        send(api, 'large_metadata', body)
        worker = Worker(connection(tmp_path, central_config, 'pc'), bridge(api), LargeReport())
        monkeypatch.setattr(worker.sources, 'collect', lambda _, guard=None: [original])
        worker.tick()
        received = messages(api)
        assert len(received) == 2
        response = {key: received[-1][key] for key in ('id', 'kind', 'in_reply_to', 'body')}
        assert len(json_bytes(Message.model_validate(response).model_dump())) <= 65_536
        Result.model_validate(response['body'])
        assert response['body']['answer']['status'] == 'failed'
        assert response['body']['task_id'] == body['task_id']
        assert 'source_evidence' not in response['body']
        assert original['content'] == text
        if field == 'pilot_result':
            details = response['body']['pilot_result']
            assert details['artifact']['sha256'] == 'b' * 64
            assert details['plan_sha256'] == 'c' * 64
            assert details['config_sha256'] == 'd' * 64
            assert details['artifact']['availability'] == 'unknown'
            assert details['evidence_delivery']['central_raw_artifact_verified'] is False


@pytest.mark.parametrize('failure', ['capacity', 'transient'])
def test_remote_capacity_refusal_is_durable_but_transient_upload_retries(tmp_path, central_config, failure):
    config = configuration(tmp_path, approval=approval())
    bench = SimulatedBench()
    uploads = []
    drop_reply = [True]
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, 'remote_capacity', task())

        def request(req):
            if req.method == 'POST' and req.url.path.endswith('/pilot-artifacts'):
                uploads.append(req.content)
                if failure == 'capacity':
                    return httpx.Response(413)
                if len(uploads) == 1:
                    raise httpx.ReadTimeout('temporary artifact upload outage')
            if failure == 'capacity' and req.method == 'POST' and req.url.path.endswith('/messages') and drop_reply[0]:
                drop_reply[0] = False
                raise httpx.ReadTimeout('temporary reply outage after capacity refusal')
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        worker = module().PilotWorker(config, httpx.MockTransport(request), lambda _: bench)
        worker.tick()
        with worker.db() as db:
            row = db.execute('SELECT * FROM inbox').fetchone()
        assert row['state'] == 'ready'
        if failure == 'capacity':
            details = json.loads(row['response'])['body']['pilot_result']
            assert details['artifact']['availability'] == 'unknown'
            assert details['evidence_delivery']['reason'] == 'remote_capacity_refusal'
            assert 'max_raw_bytes' not in details['evidence_delivery']
        else:
            assert 'evidence_delivery' not in json.loads(row['response'])['body']['pilot_result']

        def forbidden(_):
            raise AssertionError('Delivery restart must not repeat physical I/O')

        restarted = module().PilotWorker(config, httpx.MockTransport(request), forbidden)
        with restarted.db() as db:
            db.execute('UPDATE inbox SET retry_at=0')
        restarted.tick()
        body = messages(api)[-1]['body']
        assert restarted.status()['counts'] == {'sent': 1}
        assert len(uploads) == (1 if failure == 'capacity' else 2)
        raw = (config.state_dir / body['pilot_result']['artifact']['path']).read_bytes()
        assert raw == uploads[0]
        assert len(raw) < 2_000_000
        assert hashlib.sha256(raw).hexdigest() == body['pilot_result']['artifact']['sha256']
        assert bench.events.count('open') == 1
        if failure == 'capacity':
            reviewer = Worker(connection(tmp_path, central_config, 'central'), httpx.MockTransport(request), ForbiddenReviewer())
            reviewer.tick()
            assert messages(api)[-1]['body']['document_type'] == 'labos_auto_review'
            assert messages(api)[-1]['body']['model_attempts'] == 0
            assert api.get('/api/agents/pc-a/pilot-claims', headers={'Authorization': 'Bearer ' + 'A' * 40}).json()['blocked'] is True


def test_pilot_metadata_fallback_keeps_binding_and_central_skips_inference(tmp_path, central_config, monkeypatch):
    config = configuration(tmp_path, approval=approval())
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, 'metadata_pilot', task())
        worker = module().PilotWorker(config, bridge(api), lambda _: SimulatedBench())
        finish = worker._finish

        def large_metadata(*args):
            generated = finish(*args)
            generated['pilot_result']['diagnostic'] = '光\\"\n' * 18_000
            return generated

        monkeypatch.setattr(worker, '_finish', large_metadata)
        worker.tick()
        body = messages(api)[-1]['body']
        assert body['answer']['status'] == 'failed'
        details = body['pilot_result']
        assert details['artifact']['message_id'] == 'metadata_pilot'
        assert details['artifact']['availability'] == 'unknown'
        files = list((config.state_dir / 'artifacts').glob('*.json'))
        assert len(files) == 1
        content = files[0].read_bytes()
        assert hashlib.sha256(content).hexdigest() == details['artifact']['sha256']
        assert json.loads(content)['plan_sha256'] == details['plan_sha256']
        reviewer = Worker(connection(tmp_path, central_config, 'central'), bridge(api), ForbiddenReviewer())
        reviewer.tick()
        review = messages(api)[-1]['body']
        assert review['document_type'] == 'labos_auto_review'
        assert review['model_attempts'] == 0
        assert api.get('/api/agents/pc-a/pilot-claims', headers={'Authorization': 'Bearer ' + 'A' * 40}).json()['blocked'] is True


def test_metadata_fallback_preserves_indexed_reference_and_still_verifies_raw(tmp_path, central_config):
    from test_cooperation_worker import pilot_review_fixture

    with TestClient(create_app(central_config)) as api:
        content = pilot_review_fixture(api)
        result = messages(api)[-1]
        response = {key: result[key] for key in ('id', 'kind', 'in_reply_to', 'body')}
        response['body']['pilot_result']['artifact']['availability'] = 'central_indexed'
        response['body']['pilot_result']['extra_metadata'] = 'x' * 90_000
        worker = Worker(connection(tmp_path, central_config, 'central'), bridge(api), ForbiddenReviewer())
        worker.bound_response(response)
        assert response['body']['pilot_result']['artifact']['availability'] == 'central_indexed'
        reviewed = worker.review_input(response)
        assert 'evidence_delivery_blocked' not in reviewed
        assert reviewed['stored_pilot_evidence']['central_raw_artifact_verified'] is True
        assert reviewed['stored_pilot_evidence']['sha256'] == hashlib.sha256(content).hexdigest()


def test_capacity_refusal_after_lost_upload_receipt_does_not_claim_central_absence(tmp_path, central_config):
    config = configuration(tmp_path, approval=approval())
    uploads = []
    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, 'lost_capacity_receipt', task())

        def request(req):
            if req.method == 'POST' and req.url.path.endswith('/pilot-artifacts'):
                uploads.append(req.content)
                if len(uploads) > 1:
                    return httpx.Response(413)
                stored = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
                assert stored.status_code == 200
                raise httpx.ReadTimeout('accepted artifact receipt was lost')
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        worker = module().PilotWorker(config, httpx.MockTransport(request), lambda _: SimulatedBench())
        worker.tick()
        assert worker.status()['counts'] == {'ready': 1}

        def forbidden(_):
            raise AssertionError('Finished physical execution cannot be repeated')

        restarted = module().PilotWorker(config, httpx.MockTransport(request), forbidden)
        with restarted.db() as db:
            db.execute('UPDATE inbox SET retry_at=0')
        restarted.tick()
        details = messages(api)[-1]['body']['pilot_result']
        assert restarted.status()['counts'] == {'sent': 1}
        assert details['artifact']['availability'] == 'unknown'
        assert details['evidence_delivery']['reason'] == 'remote_capacity_refusal'
        assert details['evidence_delivery']['central_raw_artifact_verified'] is False
        assert len(uploads) == 2
        assert uploads[0] == uploads[1]
        # The first upload really was indexed; a later 413 cannot prove its absence.
        stored = api.get('/api/pilot-artifacts/pc-a/lost_capacity_receipt',
                         headers={'Authorization': 'Bearer ' + 'O' * 40})
        assert stored.status_code == 200
        assert stored.content == uploads[0]
        restarted.tick()
        assert len(uploads) == 2
