import copy
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from labos_field.models import CampaignTask, authorize, default_task
from labos_field.records import Journal, artifact_messages, digest, reassemble
from labos_field.channel import Channel


def test_only_the_fixed_five_point_scope_is_accepted():
    task = default_task('field-test-001')
    assert task.targets_z_t == (-0.5, -0.25, 0.0, 0.25, 0.5)
    assert task.optical.samples_per_phase == 3
    for change in ({'targets_z_t': [0, -.25, -.5, .25, .5]},
                   {'targets_z_t': [False, -.25, 0, .25, .5]},
                   {'final_z_t': .5}, {'sample_id': 'other'},
                   {'optical': {**task.optical.model_dump(), 'laser_current_a': .0218}},
                   {'optical': {**task.optical.model_dump(), 'power_limit_w': float('nan')}}):
        with pytest.raises(ValueError):
            CampaignTask.model_validate({**task.model_dump(), **change})


def test_authority_requires_exact_sender_content_and_unexpired_task():
    task = default_task('field-test-002')
    message = {'id': 'msg_field_002', 'kind': 'note', 'in_reply_to': None,
               'body': task.model_dump(mode='json')}
    sha = digest(message)
    wire = {**message, 'sender': 'central', 'agent_id': 'cryostat-pc', 'sha256': sha}
    assert authorize(wire, 'msg_field_002', sha, 'field-test-002').task_id == task.task_id
    for altered in ({**wire, 'sender': 'pc'}, {**wire, 'agent_id': 'other'},
                    {**wire, 'body': {**wire['body'], 'task_id': 'changed'}},
                    {**wire, 'sha256': '0' * 64}):
        with pytest.raises(ValueError):
            authorize(altered, 'msg_field_002', sha, 'field-test-002')
    with pytest.raises(ValueError):
        authorize(wire, 'msg_field_002', sha, 'field-test-002',
                  now=datetime.now(timezone.utc) + timedelta(days=1))


def test_crash_intent_and_unknown_result_block_all_hardware_reentry(tmp_path):
    journal = Journal(tmp_path)
    journal.begin('first', 'a' * 64, 'b' * 64)
    with pytest.raises(ValueError, match='unresolved'):
        Journal(tmp_path).begin('second', 'c' * 64, 'd' * 64)
    journal.finish('first', {'status': 'UNKNOWN', 'samples': []})
    with pytest.raises(ValueError, match='unresolved'):
        Journal(tmp_path).begin('third', 'c' * 64, 'd' * 64)


def test_completed_or_failed_task_id_is_never_replayed(tmp_path):
    journal = Journal(tmp_path)
    journal.begin('first', 'a' * 64, 'b' * 64)
    result = {'status': 'FAILED', 'partial': [1, 2, 3]}
    journal.finish('first', result)
    assert Journal(tmp_path).result('first') == result
    with pytest.raises(ValueError):
        journal.begin('first', 'a' * 64, 'b' * 64)
    journal.begin('second', 'c' * 64, 'd' * 64)


def test_full_artifact_round_trip_and_tampering_fail_closed():
    raw = {'status': 'FAILED', 'rejected_samples': [{'raw': str(i), 'x': i / 19}
                                                 for i in range(9000)]}
    parts = artifact_messages('field-001', raw)
    assert len(parts) > 2
    assert reassemble(parts) == raw
    with pytest.raises(ValueError):
        reassemble(parts[:-2] + parts[-1:])
    altered = copy.deepcopy(parts)
    altered[0]['body']['data_b64'] = 'AAAA'
    with pytest.raises(ValueError):
        reassemble(altered)
    with pytest.raises(ValueError):
        artifact_messages('field-001', {'token': 'do-not-send'})


def test_channel_paginates_and_requires_server_envelope_hash():
    from labos.config import AgentConfig
    config = AgentConfig(agent_id='cryostat-pc', token='x' * 32,
                         server_url='https://central.invalid', instruments=[])
    task = default_task('field-test-003')
    payload = {'id': 'msg_target', 'kind': 'note', 'in_reply_to': None,
               'body': task.model_dump(mode='json')}
    message = {**payload, 'sha256': digest(payload), 'sender': 'central',
               'agent_id': 'cryostat-pc', 'sequence': 102}
    def handle(request):
        after = int(request.url.params.get('after', 0))
        if after == 0:
            return httpx.Response(200, json={'messages': [{'id': 'old', 'sequence': 101}],
                                            'next_cursor': 101})
        return httpx.Response(200, json={'messages': [message], 'next_cursor': 102})
    with Channel(config, transport=httpx.MockTransport(handle)) as channel:
        assert channel.fetch('msg_target')['body'] == task.model_dump(mode='json')
