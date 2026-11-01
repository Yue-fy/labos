from __future__ import annotations

from datetime import datetime, timezone
import multiprocessing
import os
from pathlib import Path
import time
import traceback
import uuid

from labos.files import atomic_write, json_bytes
from .models import LocalConfig


class RpcTimeout(TimeoutError):
    pass


def _child(connection, settings, state_dir):
    from .magnet import MagnetSession
    config = LocalConfig.model_validate(settings)
    log = Path(state_dir) / 'magnetic-events.jsonl'
    def event(value):
        with log.open('ab') as stream:
            stream.write(json_bytes({**value, 'captured_at_utc': datetime.now(timezone.utc).isoformat()}) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
    session = MagnetSession(config, event)
    try:
        while True:
            request = connection.recv()
            session.deadline = request['deadline']
            operation = request['operation']
            try:
                session.guard()
                if operation == 'open':
                    writes = request['args'].get('writes', False)
                    if type(writes) is not bool or (writes and not config.enabled):
                        raise ValueError('magnetic write commissioning is disabled')
                    value = session.open(writes=writes)
                elif operation == 'read':
                    value = session.read()
                elif operation == 'move':
                    value = session.move(request['args']['z'])
                elif operation == 'zero':
                    value = session.zero()
                elif operation == 'close':
                    value = session.close()
                else:
                    raise ValueError('unsupported magnetic operation')
                session.guard()
                connection.send({'id': request['id'], 'ok': True, 'result': value})
            except BaseException as exc:
                event({'event': 'magnetic_exception', 'operation': operation,
                       'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()})
                connection.send({'id': request['id'], 'ok': False,
                                 'error': f'{type(exc).__name__}: {exc}'})
                if time.monotonic() >= session.deadline:
                    break
            if operation == 'close':
                break
    except (EOFError, BrokenPipeError):
        event({'event': 'parent_connection_lost', 'state': 'UNKNOWN'})
    finally:
        try:
            session.close()
        except BaseException as exc:
            event({'event': 'child_final_close_error', 'error': str(exc)})
        connection.close()


class MagnetProcess:
    def __init__(self, config, state_dir, *, target=_child):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        settings = config.model_dump(mode='json') if hasattr(config, 'model_dump') else config
        self.process = context.Process(target=target, args=(child, settings, str(self.state_dir)), daemon=False)
        self.process.start()
        child.close()
        self.healthy = True
        self.pid = self.process.pid

    def call(self, operation, args=None, timeout=5.):
        if not self.healthy:
            raise ValueError('magnetic child state is uncertain; no further commands')
        ident = uuid.uuid4().hex
        try:
            self.connection.send({'id': ident, 'operation': operation, 'args': args or {},
                                  'deadline': time.monotonic() + timeout})
            if not self.connection.poll(timeout):
                raise RpcTimeout('magnetic RPC deadline exceeded; no cancellation/zero assumed')
            reply = self.connection.recv()
            if reply.get('id') != ident:
                raise RpcTimeout('late or mismatched magnetic reply')
        except (OSError, EOFError, RpcTimeout) as exc:
            self.healthy = False
            atomic_write(self.state_dir / 'magnetic-child-uncertain.json', json_bytes(
                {'pid': self.pid, 'operation': operation, 'state': 'UNKNOWN', 'error': str(exc),
                 'forced_termination': False}))
            raise
        if reply.get('ok') is not True:
            raise RuntimeError(reply.get('error', 'invalid magnetic response'))
        return reply['result']

    def open(self, writes=False): return self.call('open', {'writes': writes}, timeout=70.)
    def read(self): return self.call('read', timeout=5.)
    def move(self, z): return self.call('move', {'z': z}, timeout=900.)
    def zero(self): return self.call('zero', timeout=900.)

    def close(self):
        if not self.healthy:
            raise RuntimeError(f'magnetic child {self.pid} requires reconciliation; no forced termination')
        value = self.call('close', timeout=10.)
        self.process.join(2.)
        if self.process.is_alive() or self.process.exitcode != 0:
            raise RuntimeError('magnetic child did not exit cleanly')
        self.connection.close()
        return value
