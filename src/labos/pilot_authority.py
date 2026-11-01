"""Durable, non-expiring authority for one physical station per enrolled agent."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StrictBool

from .files import json_bytes
from .models import Identifier, Model

Scope = Literal['optical_transport', 'optical_readback', 'dark_a']
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
MAX_CLAIM_BYTES = 4096


class PilotClaim(Model):
    message_id: Identifier
    task_id: Identifier
    plan_sha256: Digest
    config_sha256: Digest
    experiment_scope: Scope
    attempt_nonce: str = Field(pattern=r'^[0-9a-f]{32}$')


class Commission(Model):
    config_sha256: Digest
    experiment_scope: Scope
    note: str = Field(min_length=1, max_length=2000)
    legacy_workers_retired: StrictBool
    physical_states_reconciled: StrictBool


def config_fingerprint(config):
    return hashlib.sha256(json_bytes(config.model_dump(mode='json'))).hexdigest()


def verified_completion(report):
    """Only explicit independent final protection and successful close release a gate."""
    if (report.get('status') not in {'COMPLETED', 'FAILED', 'CANCELLED'}
            or report.get('protection_verified') is not True
            or 'close_error' not in report or report['close_error'] is not None):
        return False
    cleanup = report.get('cleanup')
    if not isinstance(cleanup, list) or not cleanup:
        return False
    for record in cleanup:
        if not isinstance(record, dict) or record.get('verified') is not True:
            return False
        laser, excitation = record.get('laser_off'), record.get('protect_excitation')
        if (not isinstance(laser, dict) or not isinstance(excitation, dict)
                or laser.get('laser_off_verified') is not True
                or laser.get('emission_off_readback') is not True
                or laser.get('zero_current_setpoint_verified') is not True
                or excitation.get('minimum_excitation_verified') is not True
                or type(excitation.get('actual_v_rms')) not in (int, float)
                or excitation['actual_v_rms'] != 0.004):
            return False
    return cleanup[-1].get('scope') == 'final'


class PilotAuthority:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            required = {'pilot_authority', 'pilot_retired', 'pilot_claims'}
            present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} & required
            if present and present != required:
                raise ValueError('Incomplete physical authority history requires explicit reconciliation')
            db.execute('''CREATE TABLE IF NOT EXISTS pilot_authority (
                agent_id TEXT PRIMARY KEY, config_sha256 TEXT NOT NULL,
                experiment_scope TEXT NOT NULL, cutoff INTEGER NOT NULL, note TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS pilot_retired (
                agent_id TEXT NOT NULL, task_id TEXT NOT NULL, PRIMARY KEY(agent_id,task_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS pilot_claims (
                agent_id TEXT NOT NULL, task_id TEXT NOT NULL, message_id TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL, config_sha256 TEXT NOT NULL,
                experiment_scope TEXT NOT NULL, attempt_nonce TEXT NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY(agent_id,task_id), UNIQUE(agent_id,message_id), UNIQUE(agent_id,attempt_nonce))''')

    @staticmethod
    def _active(db, agent_id):
        return db.execute("SELECT 1 FROM pilot_claims WHERE agent_id=? AND state IN ('active','uncertain')",
                          (agent_id,)).fetchone() is not None

    @classmethod
    def _status(cls, db, agent_id):
        row = db.execute('SELECT * FROM pilot_authority WHERE agent_id=?', (agent_id,)).fetchone()
        return {'commissioned': row is not None, 'blocked': cls._active(db, agent_id),
                'config_sha256': row['config_sha256'] if row else None,
                'experiment_scope': row['experiment_scope'] if row else None,
                'cutoff': row['cutoff'] if row else None}

    def status(self, agent_id):
        with self.store.transaction() as db:
            return self._status(db, agent_id)

    def commission(self, agent_id, request):
        if not (request.legacy_workers_retired and request.physical_states_reconciled
                and request.note.strip()):
            raise ValueError('Explicit legacy retirement and physical reconciliation attestations required')
        with self.store.transaction() as db:
            if not db.execute('SELECT 1 FROM agents WHERE id=?', (agent_id,)).fetchone():
                raise KeyError('Agent not enrolled')
            if self._active(db, agent_id):
                raise ValueError('Active or uncertain physical claim requires reconciliation; selection unchanged')
            cutoff = db.execute('SELECT COALESCE(MAX(sequence),0) FROM correspondence').fetchone()[0]
            for row in db.execute("SELECT body FROM correspondence WHERE agent_id=? AND sender='central' AND sequence<=?",
                                  (agent_id, cutoff)):
                body = json.loads(row['body'])['body']
                if body.get('document_type') == 'labos_pilot_task' and isinstance(body.get('task_id'), str):
                    db.execute('INSERT OR IGNORE INTO pilot_retired VALUES(?,?)', (agent_id, body['task_id']))
            db.execute('''INSERT INTO pilot_authority VALUES(?,?,?,?,?) ON CONFLICT(agent_id)
                DO UPDATE SET config_sha256=excluded.config_sha256, experiment_scope=excluded.experiment_scope,
                cutoff=excluded.cutoff, note=excluded.note''',
                       (agent_id, request.config_sha256, request.experiment_scope, cutoff, request.note))
            self.store.event_db(db, 'PHYSICAL_AUTHORITY_COMMISSIONED', {'agent_id': agent_id,
                                'cutoff': cutoff, **request.model_dump()})
            return self._status(db, agent_id)

    def claim(self, agent_id, request):
        from .pilot import PilotPlan
        denied = {'granted': False, 'reason': 'Physical authority refused this attempt; no execution permitted.'}
        with self.store.transaction() as db:
            selection = self._status(db, agent_id)
            if (not selection['commissioned'] or selection['blocked']
                    or selection['config_sha256'] != request.config_sha256
                    or selection['experiment_scope'] != request.experiment_scope):
                return denied
            if db.execute('SELECT 1 FROM pilot_claims WHERE agent_id=? AND (task_id=? OR message_id=? OR attempt_nonce=?)',
                          (agent_id, request.task_id, request.message_id, request.attempt_nonce)).fetchone():
                return denied
            if db.execute('SELECT 1 FROM pilot_retired WHERE agent_id=? AND task_id=?',
                          (agent_id, request.task_id)).fetchone():
                return denied
            row = db.execute('SELECT * FROM correspondence WHERE agent_id=? AND id=?',
                             (agent_id, request.message_id)).fetchone()
            if row is None or row['sender'] != 'central' or row['sequence'] <= selection['cutoff']:
                return denied
            task = json.loads(row['body'])['body']
            if (task.get('protocol') != 'labos-agent-v1' or task.get('document_type') != 'labos_pilot_task'
                    or task.get('task_id') != request.task_id
                    or task.get('experiment_scope') != request.experiment_scope):
                return denied
            try:
                plan = PilotPlan.model_validate(task['pilot_plan'])
            except (ValueError, KeyError):
                return denied
            if hashlib.sha256(json_bytes(plan.model_dump(mode='json'))).hexdigest() != request.plan_sha256:
                return denied
            db.execute("INSERT INTO pilot_claims VALUES(?,?,?,?,?,?,?,'active')",
                       (agent_id, request.task_id, request.message_id, request.plan_sha256,
                        request.config_sha256, request.experiment_scope, request.attempt_nonce))
            self.store.event_db(db, 'PHYSICAL_AUTHORITY_CLAIMED', {'agent_id': agent_id, **request.model_dump()})
            return {'granted': True, 'agent_id': agent_id, **request.model_dump()}

    @staticmethod
    def finalize(db, agent_id, artifact):
        claim = db.execute('SELECT * FROM pilot_claims WHERE agent_id=? AND (message_id=? OR task_id=?)',
                           (agent_id, artifact.message_id, artifact.report.get('task_id'))).fetchone()
        if claim is None:
            if artifact.attempt_nonce is not None:
                raise ValueError('Claimed physical evidence has no authority claim')
            return  # Historical unclaimed artifacts never change authority.
        report = artifact.report
        if (claim['message_id'] != artifact.message_id or claim['task_id'] != report.get('task_id')
                or claim['plan_sha256'] != artifact.plan_sha256
                or claim['config_sha256'] != report.get('config_sha256')
                or claim['experiment_scope'] != report.get('experiment_scope')
                or claim['attempt_nonce'] != artifact.attempt_nonce):
            raise ValueError('Physical artifact does not match its authority claim')
        if claim['state'] == 'terminal':
            return  # Retrying A cannot change a later active B.
        state = 'terminal' if verified_completion(report) else 'uncertain'
        db.execute('UPDATE pilot_claims SET state=? WHERE agent_id=? AND message_id=?',
                   (state, agent_id, artifact.message_id))
