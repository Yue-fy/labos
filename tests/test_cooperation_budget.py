"""Durable backend admission, aggregate deadlines and bounded provider ingestion."""
import asyncio
import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.cooperation_models import Responder
from labos.cooperation_worker import Worker
from test_cooperation_worker import Reports, bridge, connection, messages, send, task


ANSWER = {'status': 'completed', 'summary': 'Reviewed.', 'findings': [], 'questions': []}


def settings(**overrides):
    return SimpleNamespace(backend='codex', codex_command=['mock-codex'], codex_model=None,
                           model_timeout_s=180, local_url='http://127.0.0.1/v1',
                           local_model='mock-model', **overrides)


def operation(clock, stop=lambda: False):
    from labos.cooperation_budget import Operation
    return Operation(180, clock=lambda: clock[0], stopped=stop)


def test_restart_after_committed_cloud_intent_uses_local_final_slot(tmp_path, central_config, monkeypatch):
    with TestClient(create_app(central_config)) as api:
        send(api, 'budget_task', task())
        config = connection(tmp_path, central_config, 'pc')
        config.backend = 'codex'
        responder = Responder(config)
        worker = Worker(config, bridge(api), responder)
        def crash(prompt, guard, admit):
            admit('codex')
            with sqlite3.connect(worker.database) as db:
                assert db.execute('SELECT backend FROM backend_invocations').fetchall() == [('codex',)]
                assert db.execute('SELECT attempts FROM inbox').fetchone() == (1,)
            raise SystemExit('simulated interruption after intent commit')
        monkeypatch.setattr(responder, 'codex', crash)
        with pytest.raises(SystemExit):
            worker.tick()
        calls = []
        async def local(request):
            calls.append(request.content)
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(ANSWER)}}]})
        restarted = Worker(config, bridge(api), Responder(config, httpx.MockTransport(local)))
        restarted.tick()
        restarted.tick()
        assert len(calls) == 1
        reply = messages(api)[-1]['body']
        assert reply['backend'] == 'local_fallback' and reply['model_attempts'] == 2
        with restarted.db() as db:
            assert [r[0] for r in db.execute('SELECT backend FROM backend_invocations ORDER BY ordinal')] == ['codex', 'local_fallback']


def test_legacy_nonzero_pending_exhausts_allowance(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        message = send(api, 'old_task', task())
        config = connection(tmp_path, central_config, 'pc')
        worker = Worker(config, bridge(api), Reports())
        with worker.db() as db:
            db.execute("INSERT INTO inbox(id,sequence,envelope,state,attempts) VALUES(?,?,?,'pending',1)",
                       (message['id'], message['sequence'], json.dumps(message)))
        class Forbidden:
            def respond(self, *args):
                pytest.fail('legacy uncertain invocations cannot receive a new allowance')
        restarted = Worker(config, bridge(api), Forbidden())
        restarted.tick()
        assert messages(api)[-1]['body']['model_attempts'] == 2
        assert messages(api)[-1]['body']['answer']['status'] == 'failed'


def test_half_remaining_cloud_deadline_and_fallback_remainder(monkeypatch):
    clock = [0.0]
    op = operation(clock)
    clock[0] = 20
    responder = Responder(settings())
    reservations = []
    def codex(payload, guard, admit):
        deadline = admit('codex')
        assert deadline == 100 and guard.deadline == 180
        clock[0] = 103  # Includes cleanup after the fixed attempt deadline.
        from labos.cooperation_budget import BackendAttemptTimeout
        raise BackendAttemptTimeout()
    def local(payload, guard):
        assert guard.remaining() == 77
        return ANSWER
    monkeypatch.setattr(responder, 'codex', codex)
    monkeypatch.setattr(responder, 'local', local)
    result = responder.respond_budgeted({}, '', op, reservations.append, ())
    assert result['backend'] == 'local_fallback'
    assert reservations == ['codex', 'local_fallback']


@pytest.mark.parametrize('failure', ['deadline', 'stop', 'reservation'])
def test_control_failure_never_dispatches_fallback(monkeypatch, failure):
    clock, stopped, calls = [0.0], [False], []
    op = operation(clock, lambda: stopped[0])
    responder = Responder(settings())
    def reserve(backend):
        calls.append(backend)
        if failure == 'reservation':
            raise sqlite3.OperationalError('journal unavailable')
    def codex(prompt, guard, admit):
        admit('codex')
        if failure == 'deadline':
            clock[0] = 180
        else:
            stopped[0] = True
        raise RuntimeError('ordinary backend failure coincides with terminal condition')
    monkeypatch.setattr(responder, 'codex', codex)
    monkeypatch.setattr(responder, 'local', lambda *args: pytest.fail('forbidden fallback'))
    with pytest.raises((RuntimeError, sqlite3.Error)):
        responder.respond_budgeted({}, '', op, reserve, ())
    assert calls == ['codex']


def test_valid_failed_answer_does_not_trigger_fallback(monkeypatch):
    responder = Responder(settings())
    monkeypatch.setattr(responder, 'codex', lambda prompt, guard, admit: admit('codex') and {**ANSWER, 'status': 'failed'})
    reservations = []
    assert responder.respond_budgeted({}, '', operation([0]), reservations.append, ())['backend'] == 'codex'
    assert reservations == ['codex']


def test_payload_gate_checks_fallback_before_any_reservation(monkeypatch):
    from labos.cooperation_models import compile_payloads
    config = settings()
    # Nested JSON escaping makes the local representation larger than the Codex prompt.
    message = {'quote': '"' * 40000}
    with pytest.raises(ValueError, match='input'):
        compile_payloads(config, message, '')
    responder = Responder(config)
    calls = []
    with pytest.raises(ValueError, match='input'):
        responder.respond_budgeted(message, '', operation([0]), calls.append, ())
    assert calls == []


def test_exact_checked_local_body_is_sent_and_utf8_gate_is_inclusive():
    from labos.cooperation_models import compile_payloads
    config = settings()
    config.backend = 'local'
    message = {'text': '光😀"\\'}
    frozen = compile_payloads(config, message, 'snapshot')
    received = []
    async def local(request):
        received.append(request.content)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(ANSWER)}}]})
    Responder(config, httpx.MockTransport(local)).respond_budgeted(message, 'snapshot', operation([0]), lambda b: None, (), frozen)
    assert received == [frozen.local_body]
    assert json.loads(received[0])['messages'][1]['content'] == json.dumps({'message': message, 'approved_static_context': 'snapshot'})
    config.local_url = None
    config.backend = 'codex'
    empty = compile_payloads(config, {'text': ''}, '')
    fitting = {'text': 'a' * (131072 - len(empty.codex_prompt))}
    assert len(compile_payloads(config, fitting, '').codex_prompt) == 131072
    fitting['text'] += 'a'
    with pytest.raises(ValueError, match='input'):
        compile_payloads(config, fitting, '')


@pytest.mark.parametrize('failure', ['size', 'encoding', 'json'])
def test_local_stream_rejects_unsafe_envelopes_and_closes(failure):
    closed = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'x' * (2097153 if failure == 'size' else 10)
        async def aclose(self):
            closed.append(True)
    async def handler(request):
        return httpx.Response(200, stream=Stream(), headers={'content-encoding': 'gzip'} if failure == 'encoding' else {})
    config = settings()
    config.backend = 'local'
    with pytest.raises(ValueError):
        Responder(config, httpx.MockTransport(handler)).respond({}, '')
    assert closed == [True]


def test_native_http_trickle_cancels_and_joins_owned_task():
    from labos.cooperation_budget import Operation, OperationDeadlineExceeded
    closed, cancelled = [], []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                while True:
                    await asyncio.sleep(.01)
                    yield b' '
            finally:
                cancelled.append(True)
        async def aclose(self):
            closed.append(True)
    async def handler(request):
        return httpx.Response(200, stream=Stream())
    config = settings()
    config.backend = 'local'
    with pytest.raises(OperationDeadlineExceeded):
        Responder(config, httpx.MockTransport(handler)).respond_budgeted({}, '', Operation(.05), lambda b: None, ())
    assert cancelled == [True] and closed == [True]


def test_legacy_typeerror_consumes_one_and_is_never_retried_in_same_cycle(tmp_path, central_config):
    calls = []
    class Broken:
        def respond(self, message, context):
            calls.append(message)
            raise TypeError('internal failure after dispatch')
    with TestClient(create_app(central_config)) as api:
        send(api, 'type_error', task())
        worker = Worker(connection(tmp_path, central_config, 'pc'), bridge(api), Broken())
        worker.tick()
        assert len(calls) == 1
        with worker.db() as db:
            assert db.execute('SELECT attempts FROM inbox').fetchone()[0] == 1
            assert db.execute('SELECT COUNT(*) FROM backend_invocations').fetchone()[0] == 1


def test_codex_discards_diagnostics_supplies_stdin_once_and_bounds_answer(monkeypatch):
    calls, supplied = [], []
    class Process:
        pid = 123456789
        stdin = None
        returncode = None
        def __init__(self, command, **kwargs):
            assert kwargs['stdout'] == subprocess.DEVNULL and kwargs['stderr'] == subprocess.DEVNULL
            assert kwargs['stdin'] != subprocess.PIPE
            supplied.append(kwargs['stdin'].read())
            self.output = Path(command[command.index('-o') + 1])
        def communicate(self, input=None, timeout=None):
            calls.append(input)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired('mock', timeout)
            self.output.write_bytes(b' ' * 1048577)
            self.returncode = 0
        def poll(self):
            return self.returncode
    monkeypatch.setattr('labos.cooperation_models.subprocess.Popen', Process)
    config = settings()
    config.local_url = None
    with pytest.raises(RuntimeError):
        Responder(config).respond({}, '')
    assert calls == [None, None]
    assert json.loads(supplied[0])['message'] == {}


def test_two_failed_backends_remain_exhausted_after_restart(tmp_path, central_config, monkeypatch):
    with TestClient(create_app(central_config)) as api:
        send(api, 'failed_pair', task())
        cfg = connection(tmp_path, central_config, 'pc')
        cfg.backend = 'codex'
        calls = []
        responder = Responder(cfg)
        def fail(*args):
            if len(args) == 3:
                args[2]('codex')
            calls.append(True)
            raise RuntimeError('private provider details')
        monkeypatch.setattr(responder, 'codex', fail)
        monkeypatch.setattr(responder, 'local', fail)
        Worker(cfg, bridge(api), responder).tick()
        Worker(cfg, bridge(api), responder).tick()
        assert len(calls) == 2
        reply = messages(api)[-1]['body']
        assert reply['model_attempts'] == 2 and reply['answer']['status'] == 'failed'
        assert 'private provider' not in json.dumps(messages(api))


def test_failed_journal_reservation_launches_nothing(tmp_path, central_config, monkeypatch):
    with TestClient(create_app(central_config)) as api:
        send(api, 'no_commit', task())
        cfg = connection(tmp_path, central_config, 'pc')
        cfg.backend = 'codex'
        responder = Responder(cfg)
        worker = Worker(cfg, bridge(api), responder)
        def fail(*args):
            raise sqlite3.OperationalError('commit unavailable')
        monkeypatch.setattr(worker, 'reserve_backend', fail)
        def cloud(prompt, guard, admit):
            admit('codex')
            pytest.fail('uncommitted cloud dispatch')
        monkeypatch.setattr(responder, 'codex', cloud)
        monkeypatch.setattr(responder, 'local', lambda *a: pytest.fail('uncommitted local dispatch'))
        worker.tick()
        with worker.db() as db:
            assert db.execute('SELECT attempts FROM inbox').fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM backend_invocations').fetchone()[0] == 0


def test_preparation_uses_same_deadline_and_does_not_reserve_after_expiry(tmp_path, central_config, monkeypatch):
    clock = [0.0]
    op = operation(clock)
    with TestClient(create_app(central_config)) as api:
        send(api, 'slow_preparation', task())
        worker = Worker(connection(tmp_path, central_config, 'pc'), bridge(api), Reports())
        monkeypatch.setattr(worker, 'new_operation', lambda: op)
        original = worker.eligible
        def eligible(message):
            clock[0] = 181
            return original(message)
        monkeypatch.setattr(worker, 'eligible', eligible)
        worker.tick()
        assert messages(api)[-1]['body']['model_attempts'] == 0
        assert messages(api)[-1]['body']['answer']['status'] == 'failed'


def test_oversized_assembled_evidence_rejected_before_legacy_dispatch(tmp_path, central_config, monkeypatch):
    with TestClient(create_app(central_config)) as api:
        body = task()
        body['context']['source_requests'] = []
        send(api, 'over_capacity', body)
        class Forbidden:
            def respond(self, *args):
                pytest.fail('oversized assembled evidence reached injected responder')
        worker = Worker(connection(tmp_path, central_config, 'pc'), bridge(api), Forbidden())
        monkeypatch.setattr(worker.sources, 'collect', lambda requests, guard=None: [{'content': '😀' * 11000}])
        worker.tick()
        reply = messages(api)[-1]['body']
        assert reply['backend'] == 'input_capacity'
        assert reply['answer']['status'] == 'needs_input' and reply['model_attempts'] == 0


@pytest.mark.parametrize('backend', ['codex', 'local'])
def test_only_available_backend_receives_full_remaining_budget(monkeypatch, backend):
    clock = [0.0]
    op = operation(clock)
    clock[0] = 20
    config = settings()
    config.backend = backend
    if backend == 'codex':
        config.local_url = None
    responder = Responder(config)
    def codex(prompt, guard, admit):
        deadline = admit('codex')
        assert deadline == 180 and guard.remaining() == 160
        return ANSWER
    def local(body, guard):
        assert guard.remaining() == 160
        return ANSWER
    monkeypatch.setattr(responder, 'codex', codex)
    monkeypatch.setattr(responder, 'local', local)
    assert responder.respond_budgeted({}, '', op, lambda b: None, ())['backend'] == backend


def test_exact_local_body_boundary_includes_metadata_and_nested_escaping():
    from labos.cooperation_models import compile_payloads
    config = settings()
    base = compile_payloads(config, {'text': ''}, '')
    message = {'text': 'a' * (131072 - len(base.local_body))}
    payload = compile_payloads(config, message, '')
    assert len(payload.local_body) == 131072 and len(payload.codex_prompt) < 131072
    message['text'] += 'a'
    with pytest.raises(ValueError, match='input'):
        compile_payloads(config, message, '')


@pytest.mark.parametrize('stop_during', ['headers', 'body'])
def test_native_http_stop_cancels_pending_request(stop_during):
    from labos.cooperation_budget import Operation, OperationCancelled
    stopped, closed, done = [False], [], []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                stopped[0] = True
                await asyncio.sleep(10)
                yield b'never'
            finally:
                done.append('body')
        async def aclose(self):
            closed.append(True)
    async def handler(request):
        if stop_during == 'headers':
            try:
                stopped[0] = True
                await asyncio.sleep(10)
            finally:
                done.append('headers')
        return httpx.Response(200, stream=Stream())
    op = Operation(1, stopped=lambda: stopped[0])
    config = settings()
    config.backend = 'local'
    with pytest.raises(OperationCancelled):
        Responder(config, httpx.MockTransport(handler)).respond_budgeted({}, '', op, lambda b: None, ())
    assert done == [stop_during]
    assert closed == ([True] if stop_during == 'body' else [])


@pytest.mark.parametrize('extra', [0, 1])
def test_streamed_envelope_cap_is_checked_before_parse_without_trusting_content_length(extra):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            payload = json.dumps({'choices': [{'message': {'content': json.dumps(ANSWER)}}]}).encode()
            yield payload
            remaining = 2097152 + extra - len(payload)
            while remaining:
                size = min(16384, remaining)
                remaining -= size
                yield b' ' * size
    async def handler(request):
        return httpx.Response(200, stream=Stream(), headers={'Content-Length': '1'})
    config = settings()
    config.backend = 'local'
    responder = Responder(config, httpx.MockTransport(handler))
    if extra:
        with pytest.raises(ValueError, match='ingestion'):
            responder.respond({}, '')
    else:
        assert responder.respond({}, '')['answer'] == ANSWER


def test_codex_cleanup_finishes_before_local_admission(monkeypatch):
    clock, events = [0.0], []
    class Process:
        stdin = None
        returncode = None
        def __init__(self, *args, **kwargs):
            events.append('launch')
        def communicate(self, input=None, timeout=None):
            if self.returncode is not None:
                events.append('reap')
                return
            clock[0] = 91
            raise subprocess.TimeoutExpired('mock', timeout)
        def poll(self):
            return self.returncode
        def terminate(self):
            events.append('terminate')
        def kill(self):
            events.append('kill')
            self.returncode = -9
    monkeypatch.setattr('labos.cooperation_models.subprocess.Popen', Process)
    responder = Responder(settings())
    monkeypatch.setattr(responder, 'local', lambda *a: ANSWER)
    responder.respond_budgeted({}, '', operation(clock), events.append, ())
    assert events == ['codex', 'launch', 'terminate', 'kill', 'reap', 'local_fallback']


def test_failed_codex_teardown_never_falls_back(monkeypatch):
    clock = [0.0]
    class Process:
        stdin = None
        returncode = None
        def __init__(self, *args, **kwargs):
            pass
        def communicate(self, input=None, timeout=None):
            clock[0] = 91
            raise subprocess.TimeoutExpired('mock', timeout)
        def poll(self):
            return None
        def terminate(self):
            pass
        def kill(self):
            pass
    monkeypatch.setattr('labos.cooperation_models.subprocess.Popen', Process)
    responder = Responder(settings())
    monkeypatch.setattr(responder, 'local', lambda *a: pytest.fail('fallback before confirmed cleanup'))
    with pytest.raises(RuntimeError):
        responder.respond_budgeted({}, '', operation(clock), lambda b: None, ())


def test_real_harmless_owned_child_is_reaped_on_aggregate_timeout(tmp_path, monkeypatch):
    import sys
    from labos.cooperation_budget import Operation, OperationDeadlineExceeded
    script = tmp_path / 'owned_sleep.py'
    script.write_text('import time\ntime.sleep(30)\n')
    original, processes, inputs = subprocess.Popen, [], []
    def launch(*args, **kwargs):
        child = original(*args, **kwargs)
        processes.append(child)
        inputs.append(kwargs['stdin'])
        return child
    monkeypatch.setattr('labos.cooperation_models.subprocess.Popen', launch)
    config = settings()
    config.local_url = None
    config.codex_command = [sys.executable, str(script)]
    with pytest.raises(OperationDeadlineExceeded):
        Responder(config).respond_budgeted({}, '', Operation(.05), lambda b: None, ())
    assert len(processes) == 1 and processes[0].poll() is not None
    assert inputs[0].closed


@pytest.mark.parametrize('action', ['doctor', 'once', 'run'])
@pytest.mark.parametrize('failure', [None, RuntimeError, KeyboardInterrupt])
def test_cli_always_closes_constructed_correspondence_client(tmp_path, monkeypatch, action, failure):
    from labos import cooperation_worker as module
    config = SimpleNamespace(state_dir=tmp_path, poll_s=1)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    def execute():
        if failure:
            raise failure()
        (tmp_path / 'stop.request').touch()
        return {'ok': True}
    worker = SimpleNamespace(client=client, doctor=execute, tick=execute, write_status=lambda s: None)
    monkeypatch.setattr(module, 'load_worker_config', lambda p: config)
    monkeypatch.setattr(module, 'Worker', lambda config: worker)
    assert module.main([action, '--config', 'unused']) == (0 if failure is None else 130 if failure is KeyboardInterrupt else 1)
    assert client.is_closed


def test_success_before_response_cache_crash_still_consumes_cloud_intent(tmp_path, central_config, monkeypatch):
    with TestClient(create_app(central_config)) as api:
        send(api, 'cache_crash', task())
        cfg = connection(tmp_path, central_config, 'pc')
        cfg.backend = 'codex'
        responder = Responder(cfg)
        monkeypatch.setattr(responder, 'codex', lambda prompt, guard, admit: admit('codex') and ANSWER)
        worker = Worker(cfg, bridge(api), responder)
        update = worker.update
        def crash(message_id, **values):
            if values.get('state') == 'ready':
                raise SystemExit('answer not cached')
            update(message_id, **values)
        monkeypatch.setattr(worker, 'update', crash)
        with pytest.raises(SystemExit):
            worker.tick()
        calls = []
        monkeypatch.setattr(responder, 'codex', lambda *a: pytest.fail('cloud replay'))
        monkeypatch.setattr(responder, 'local', lambda *a: calls.append(True) or ANSWER)
        Worker(cfg, bridge(api), responder).tick()
        assert calls == [True]
        assert messages(api)[-1]['body']['model_attempts'] == 2


def test_legacy_cached_reply_is_delivered_unchanged_without_new_intent(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(api, 'cached_legacy', task())
        cfg = connection(tmp_path, central_config, 'pc')
        worker = Worker(cfg, bridge(api, drop=[True]), Reports())
        worker.tick()
        with worker.db() as db:
            original = db.execute('SELECT response FROM inbox').fetchone()[0]
            db.execute('DELETE FROM backend_invocations')
            db.execute('UPDATE inbox SET retry_at=0')
        class Forbidden:
            def respond(self, *args):
                pytest.fail('cached reply regenerated')
        restarted = Worker(cfg, bridge(api), Forbidden())
        restarted.tick()
        with restarted.db() as db:
            assert db.execute('SELECT response,state FROM inbox').fetchone()[:] == (original, 'sent')
            assert db.execute('SELECT COUNT(*) FROM backend_invocations').fetchone()[0] == 0
        assert len(messages(api)) == 2 and messages(api)[-1]['body']['model_attempts'] == 1


def test_failed_worker_construction_does_not_leave_correspondence_client_open(tmp_path, central_config, monkeypatch):
    cfg = connection(tmp_path, central_config, 'pc')
    first = Worker(cfg)
    first.client.close()
    config_data = json.loads(cfg.connection_config.read_text())
    config_data['server_url'] = 'http://127.0.0.1:9999'
    cfg.connection_config.write_text(json.dumps(config_data))
    original, created = httpx.Client, []
    def client(*args, **kwargs):
        instance = original(*args, **kwargs)
        created.append(instance)
        return instance
    monkeypatch.setattr('labos.cooperation_worker.httpx.Client', client)
    with pytest.raises(ValueError, match='identity'):
        Worker(cfg)
    assert all(instance.is_closed for instance in created)


@pytest.mark.parametrize('has_backend_intent', [False, True])
def test_known_deterministic_legacy_cycle_preserves_journals_and_never_replays(tmp_path, central_config, monkeypatch, has_backend_intent):
    from test_program_connector import connector, program_task
    with TestClient(create_app(central_config)) as api:
        message = send(api, 'known_program', program_task())
        worker = connector(tmp_path, central_config, transport=bridge(api))
        with worker.db() as db:
            db.execute("INSERT INTO inbox(id,sequence,envelope,state,attempts) VALUES(?,?,?,'pending',1)",
                       (message['id'], message['sequence'], json.dumps(message)))
            if has_backend_intent:
                db.execute("INSERT INTO backend_invocations VALUES(?,1,'codex')", (message['id'],))
        cached = {'backend': 'program', 'answer': ANSWER}
        with sqlite3.connect(worker.execution_database) as db:
            db.execute("INSERT INTO executions VALUES(?,'finished',?)", (message['id'], json.dumps(cached)))
        restarted = connector(tmp_path, central_config, transport=bridge(api))
        monkeypatch.setattr('labos.program_connector.subprocess.run', lambda *a, **k: pytest.fail('deterministic execution replay'))
        restarted.tick()
        assert messages(api)[-1]['body']['model_attempts'] == int(has_backend_intent)
        with restarted.db() as db:
            assert db.execute('SELECT attempts FROM inbox').fetchone()[0] == 1
            assert db.execute('SELECT COUNT(*) FROM backend_invocations').fetchone()[0] == int(has_backend_intent)
        with sqlite3.connect(restarted.execution_database) as db:
            assert db.execute('SELECT state,result FROM executions').fetchone() == ('finished', json.dumps(cached))


def test_private_prompt_is_exact_and_prepared_before_cloud_reservation(monkeypatch):
    import os
    import stat
    from labos.cooperation_models import compile_payloads
    clock, events, paths, received = [0.0], [], [], []
    cfg = settings()
    cfg.local_url = None
    payload = {'original_task': {'instruction': '光😀"\\'}, 'stored_pilot_evidence': {'summary': 'static'}}
    frozen = compile_payloads(cfg, payload, 'approved snapshot')
    class Process:
        stdin = None
        returncode = None
        def __init__(self, command, **kwargs):
            path = Path(kwargs['stdin'].name)
            paths.append(path)
            assert events == ['reserved']
            if os.name == 'posix':
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
            received.append(kwargs['stdin'].read())
            self.output = Path(command[command.index('-o') + 1])
        def communicate(self, **kwargs):
            assert set(kwargs) == {'timeout'}
            self.output.write_text(json.dumps(ANSWER))
            self.returncode = 0
        def poll(self):
            return self.returncode
    monkeypatch.setattr('labos.cooperation_models.subprocess.Popen', Process)
    def reserve(backend):
        events.append('reserved')
        # The persisted callback sees prepared input, before any owned process starts.
        assert paths == []
    result = Responder(cfg).respond_budgeted(payload, 'approved snapshot', operation(clock), reserve, (), frozen)
    assert result['answer'] == ANSWER and received == [frozen.codex_prompt]
    assert not paths[0].exists()


def test_aggregate_control_failure_survives_secondary_process_cleanup_failure(monkeypatch):
    from labos.cooperation_budget import OperationDeadlineExceeded, ProcessCleanupFailed
    clock = [0.0]
    class Process:
        def __init__(self, *a, **k):
            pass
        def communicate(self, **kwargs):
            clock[0] = 181
            raise subprocess.TimeoutExpired('mock', kwargs['timeout'])
    monkeypatch.setattr('labos.cooperation_models.subprocess.Popen', Process)
    responder = Responder(settings())
    def fail_cleanup(process):
        raise ProcessCleanupFailed('secondary cleanup error')
    monkeypatch.setattr(responder, 'cleanup_process', fail_cleanup)
    with pytest.raises(OperationDeadlineExceeded):
        responder.respond_budgeted({}, '', operation(clock), lambda b: None, ())


def test_combined_parent_source_snapshot_and_static_context_are_not_silently_dropped():
    from labos.cooperation_models import compile_payloads
    cfg = settings()
    payload = {'message': {'text': 'x' * 20000},
               'original_task': {'instruction': 'x' * 20000},
               'approved_source_evidence': [{'content': 'x' * 20000}],
               'stored_pilot_evidence': {'snapshot': 'x' * 40000}}
    with pytest.raises(ValueError, match='input'):
        compile_payloads(cfg, payload, 'x' * 32000)
    assert len(payload['stored_pilot_evidence']['snapshot']) == 40000
