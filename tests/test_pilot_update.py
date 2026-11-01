"""Exercise update integrity, backup and worker-lock checks without device access."""

import hashlib
import json
from pathlib import Path
import runpy

import pytest

from labos.files import InstanceLock

APPLY = Path(__file__).parents[1] / "src/labos/assets/Apply-Pilot-Update.py"


def test_physical_overlay_ships_canonical_handoff_and_rehearsal(tmp_path, monkeypatch):
    import zipfile
    from scripts import build_pilot_update

    # Packaging inputs are synthetic; no dependency installation or download.
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "MANIFEST.json").write_text('{}')
    monkeypatch.setattr(build_pilot_update, "WHEELS", {})
    archive_path = build_pilot_update.build(tmp_path / "update.zip", wheels)
    root = APPLY.parents[3]
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("payload-manifest.json"))["files"]
        sources = {name: root / "docs" / name for name in (
            "PHYSICAL_AUTHORITY_EN.md", "PORTABLE_UPDATE_RECOVERY_EN.md",
            "ONSITE_COMMISSIONING_EN.md", "RELIABILITY_IMPROVEMENTS_EN.md")}
        sources["rehearse_commissioning.py"] = root / "scripts/rehearse_commissioning.py"
        sources["NETWORK_EN.md"] = root / "src/labos/assets/NETWORK_EN.md"
        for name, source in sources.items():
            assert name in manifest, f"Missing onsite payload: {name}"
            content = archive.read("overlay/" + name)
            assert content == source.read_bytes()
            assert hashlib.sha256(content).hexdigest() == manifest[name]


def test_physical_overlay_refreshes_example_without_changing_operator_approval(tmp_path, monkeypatch):
    import zipfile
    import yaml
    from scripts import build_pilot_update

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "MANIFEST.json").write_text('{}')
    monkeypatch.setattr(build_pilot_update, "WHEELS", {})
    archive_path = build_pilot_update.build(tmp_path / "update.zip", wheels)
    update = tmp_path / "extracted"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(update)
    template = yaml.safe_load((update / "overlay/pilot-worker.example.yaml").read_bytes())
    approval, adapter = template["approval"], template["adapter_config"]
    assert (approval["sample_id"],
            adapter["chopper_phase_lock_manually_confirmed"],
            adapter["chopper_phase_lock_confirmation_note"]) == ("example-sample", False, "")
    assert approval["enabled"] is False
    assert adapter["commissioned"] is False
    assert adapter["manual_route_confirmed"] is False

    target = tmp_path / "stopped-installation"
    target.mkdir()
    connection = b'agent_id: pc-a\r\ntoken: synthetic-local-test-token\r\ninstruments: []\r\n'
    profile = (
        b'# Operator-owned approval and historical observation; retain exact bytes.\r\n'
        b'agent_id: pc-a\r\nconnection_config: config.yaml\r\n'
        b'state_dir: data/physical-pilot\r\nadapter_id: cryostat_v1\r\n'
        b'approval:\r\n  enabled: true\r\n  sample_id: operator-sample\r\n'
        b'adapter_config:\r\n  commissioned: true\r\n  manual_route_confirmed: true\r\n'
        b'  chopper_phase_lock_manually_confirmed: true\r\n'
        b'  chopper_phase_lock_confirmation_note: "Synthetic historical operator record"\r\n'
    )
    (target / "config.yaml").write_bytes(connection)
    (target / "pilot-worker.yaml").write_bytes(profile)
    runpy.run_path(str(update / "Apply-Pilot-Update.py"))['apply_update'](update, target)
    assert (target / "config.yaml").read_bytes() == connection
    assert (target / "pilot-worker.yaml").read_bytes() == profile
    assert (target / "pilot-worker.example.yaml").read_bytes() == (
        update / "overlay/pilot-worker.example.yaml").read_bytes()


def fixture(tmp_path):
    update = tmp_path / "update"
    update.mkdir()
    target = tmp_path / "LabOS (existing)"
    target.mkdir()
    (target / "config.yaml").write_text("preserved-connection")
    (target / "cooperation.yaml").write_text(
        "role: pc\nagent_id: pc-a\nconnection_config: config.yaml\n"
    )
    payload = update / "overlay"
    payload.mkdir()
    (payload / "Check-Pilot-Runtime.py").write_bytes(b"# new runtime check\n")
    (target / "Check-Pilot-Runtime.py").write_bytes(b"# previous runtime check\n")
    (update / "payload-manifest.json").write_text(
        json.dumps(
            {
                "files": {
                    "Check-Pilot-Runtime.py": hashlib.sha256(
                        (payload / "Check-Pilot-Runtime.py").read_bytes()
                    ).hexdigest()
                }
            }
        )
    )
    return update, target


def test_update_preserves_connection_and_journal_and_backs_up_replaced_files(tmp_path):
    update, target = fixture(tmp_path)
    journal = target / "data/cooperation/journal.sqlite"
    journal.parent.mkdir(parents=True)
    journal.write_bytes(b"preserved-journal")
    apply_update = runpy.run_path(str(APPLY))["apply_update"]
    backup = apply_update(update, target)
    assert (target / "Check-Pilot-Runtime.py").read_text() == "# new runtime check\n"
    assert (backup / "Check-Pilot-Runtime.py").read_text() == "# previous runtime check\n"
    assert (target / "config.yaml").read_text() == "preserved-connection"
    assert journal.read_bytes() == b"preserved-journal"


@pytest.mark.parametrize("fault", ["checksum", "active_worker", "protected_path", "escape"])
def test_update_refuses_before_mutation_on_bad_payload_or_active_worker(tmp_path, fault):
    from contextlib import nullcontext

    update, target = fixture(tmp_path)
    manifest = update / "payload-manifest.json"
    if fault == "checksum":
        (update / "overlay/Check-Pilot-Runtime.py").write_text("# tampered\n")
    elif fault in ("protected_path", "escape"):
        entry = "config.yaml" if fault == "protected_path" else "../escaped.py"
        manifest.write_text(json.dumps({"files": {entry: "0" * 64}}))
    lock = InstanceLock(target / "data/cooperation") if fault == "active_worker" else nullcontext()
    with lock, pytest.raises((ValueError, RuntimeError)):
        runpy.run_path(str(APPLY))["apply_update"](update, target)
    assert (target / "Check-Pilot-Runtime.py").read_text() == "# previous runtime check\n"
    assert (target / "config.yaml").read_text() == "preserved-connection"


def test_update_locks_dark_a_worker_before_replacing_shared_code(tmp_path):
    update, target = fixture(tmp_path)
    (target / 'dark-a-worker.yaml').write_text(
        'agent_id: pc-a\nconnection_config: config.yaml\nstate_dir: data/dark-a-pilot\n')
    with InstanceLock(target / 'data/dark-a-pilot'), pytest.raises(RuntimeError):
        runpy.run_path(str(APPLY))['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_text() == '# previous runtime check\n'


@pytest.mark.parametrize('extension', ['yaml', 'json'])
@pytest.mark.parametrize('kind,state,extra', [
    ('pilot', 'data/physical-pilot', {'backend': 'pilot'}),
    ('program', 'data/program-connector', {'programs': {}}),
    ('report', 'data/cooperation', {'backend': 'codex'}),
    ('unspecified', 'custom-state', {'state_dir': 'custom-state'}),
])
def test_custom_profiles_contend_with_real_worker_locks(tmp_path, extension, kind, state, extra):
    import yaml
    update, target = fixture(tmp_path)
    values = {'agent_id': 'pc-a', 'connection_config': 'config.yaml', **extra}
    content = json.dumps(values) if extension == 'json' else yaml.safe_dump(values)
    (target / ('custom-worker.' + extension)).write_text(content)
    with InstanceLock(target / state), pytest.raises(RuntimeError):
        runpy.run_path(str(APPLY))['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


@pytest.mark.parametrize('name,content', [
    ('pilot-worker.yaml', 'agent_id: ['),
    ('program-connector.json', '{}'),
    ('custom.yaml', 'agent_id: pc-a\nconnection_config: config.yaml\n'),
    ('broken.yaml', 'agent_id: [\n'),
])
def test_malformed_or_ambiguous_profile_refuses_without_payload_changes(tmp_path, name, content):
    update, target = fixture(tmp_path)
    (target / name).write_text(content)
    with pytest.raises(ValueError):
        runpy.run_path(str(APPLY))['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_program_only_install_uses_program_default_lock(tmp_path):
    update, target = fixture(tmp_path)
    (target / 'cooperation.yaml').unlink()
    (target / 'program-connector.yaml').write_text(
        'agent_id: pc-a\nconnection_config: config.yaml\nprograms: {}\n')
    with InstanceLock(target / 'data/program-connector'), pytest.raises(RuntimeError):
        runpy.run_path(str(APPLY))['apply_update'](update, target)


def test_transaction_records_inventory_and_supports_explicit_recovery(tmp_path):
    update, target = fixture(tmp_path)
    api = runpy.run_path(str(APPLY))
    backup = api['apply_update'](update, target)
    transaction = json.loads((backup / 'transaction.json').read_text())
    assert transaction['status'] == 'committed'
    assert transaction['target'] == str(target.resolve())
    assert transaction['files']['Check-Pilot-Runtime.py'] == {
        'old': hashlib.sha256(b'# previous runtime check\n').hexdigest(),
        'new': hashlib.sha256(b'# new runtime check\n').hexdigest(),
    }
    assert transaction['profiles'][0]['state_dir'] == str((target / 'data/cooperation').resolve())
    api['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'
    assert json.loads((backup / 'transaction.json').read_text())['status'] == 'recovered'


def add_payload(update, name, content):
    path = update / 'overlay' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    manifest = update / 'payload-manifest.json'
    values = json.loads(manifest.read_text())
    values['files'][name] = hashlib.sha256(content).hexdigest()
    manifest.write_text(json.dumps(values))


def updater():
    return runpy.run_path(str(APPLY))['apply_update'].__globals__


def transaction_dir(target):
    return next((target / 'data/pilot-update-backups').iterdir())


@pytest.mark.parametrize('boundary', ['before', 'after'])
@pytest.mark.parametrize('index', [1, 2, 3])
@pytest.mark.parametrize('interruption', [False, True])
def test_replace_faults_restore_or_leave_recoverable_inventory(tmp_path, monkeypatch, boundary,
                                                             index, interruption):
    update, target = fixture(tmp_path)
    add_payload(update, 'src/labos/new_module.py', b'# introduced module\n')
    add_payload(update, 'src/labos/z_existing.py', b'# replacement\n')
    old = target / 'src/labos/z_existing.py'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'# original\n')
    api = updater()
    original = api['atomic_write']
    seen = 0

    class ProcessLoss(BaseException):
        pass

    def fault(path, content):
        nonlocal seen
        is_payload = Path(path).is_relative_to(target) and 'data' not in Path(path).relative_to(target).parts
        if is_payload:
            seen += 1
        failing = is_payload and seen == index
        if failing and boundary == 'before':
            raise ProcessLoss() if interruption else OSError('injected write failure')
        original(path, content)
        if failing and boundary == 'after':
            raise ProcessLoss() if interruption else OSError('injected write failure')

    monkeypatch.setitem(api, 'atomic_write', fault)
    with pytest.raises((ProcessLoss, OSError)):
        api['apply_update'](update, target)
    backup = transaction_dir(target)
    if interruption:
        with pytest.raises(RuntimeError, match=backup.name):
            updater()['apply_update'](update, target)
        updater()['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'
    assert old.read_bytes() == b'# original\n'
    assert not (target / 'src/labos/new_module.py').exists()
    assert json.loads((backup / 'transaction.json').read_text())['status'] == 'recovered'


def test_commit_interruption_requires_explicit_recovery(tmp_path, monkeypatch):
    update, target = fixture(tmp_path)
    api = updater()
    original = api['atomic_write']

    def fault(path, content):
        if Path(path).name == 'transaction.json' and json.loads(content)['status'] == 'committed':
            raise KeyboardInterrupt()
        original(path, content)

    monkeypatch.setitem(api, 'atomic_write', fault)
    with pytest.raises(KeyboardInterrupt):
        api['apply_update'](update, target)
    backup = transaction_dir(target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# new runtime check\n'
    with pytest.raises(RuntimeError, match=backup.name):
        updater()['apply_update'](update, target)
    updater()['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


@pytest.mark.parametrize('conflict', ['profile_change', 'new_profile', 'missing_profile',
    'user_edit', 'missing_old', 'backup_corrupt', 'backup_missing', 'symlink'])
def test_recovery_preflights_entire_inventory_without_partial_restore(tmp_path, conflict):
    update, target = fixture(tmp_path)
    add_payload(update, 'src/labos/z_last.py', b'new last')
    last = target / 'src/labos/z_last.py'
    last.parent.mkdir(parents=True)
    last.write_bytes(b'old last')
    api = updater()
    backup = api['apply_update'](update, target)
    if conflict == 'profile_change':
        (target / 'cooperation.yaml').write_text('role: pc\nagent_id: changed\nconnection_config: config.yaml\n')
    elif conflict == 'new_profile':
        (target / 'new-worker.json').write_text(json.dumps({
            'agent_id': 'pc-a', 'connection_config': 'config.yaml', 'backend': 'pilot'}))
    elif conflict == 'missing_profile':
        (target / 'cooperation.yaml').unlink()
    elif conflict == 'user_edit':
        last.write_bytes(b'user edit')
    elif conflict == 'missing_old':
        last.unlink()
    elif conflict == 'backup_corrupt':
        (backup / 'src/labos/z_last.py').write_bytes(b'corrupt backup')
    elif conflict == 'backup_missing':
        (backup / 'src/labos/z_last.py').unlink()
    else:
        last.unlink()
        last.symlink_to(target / 'Check-Pilot-Runtime.py')
    before = (target / 'Check-Pilot-Runtime.py').read_bytes()
    evidence = (backup / 'transaction.json').read_bytes()
    with pytest.raises((ValueError, RuntimeError, OSError)):
        api['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == before == b'# new runtime check\n'
    assert (backup / 'transaction.json').read_bytes() == evidence


@pytest.mark.parametrize('transaction_id', ['..', '../outside', '/tmp', '', 'a/b', 'C:\\escape'])
def test_recovery_transaction_id_cannot_escape_backup_root(tmp_path, transaction_id):
    _, target = fixture(tmp_path)
    with pytest.raises(ValueError):
        updater()['recover_update'](target, transaction_id)


def test_real_agent_connection_map_is_preserved_not_mistaken_for_worker(tmp_path):
    update, target = fixture(tmp_path)
    connection = b'agent_id: pc-a\ntoken: synthetic-local-test-token\nserver_url: https://example.invalid\ninstruments: []\n'
    (target / 'config.yaml').write_bytes(connection)
    updater()['apply_update'](update, target)
    assert (target / 'config.yaml').read_bytes() == connection


@pytest.mark.parametrize('kind,extra,state', [
    ('pilot', {'adapter_id': 'cryostat_v1'}, 'data/physical-pilot'),
    ('report', {'codex_command': ['synthetic-test-only']}, 'data/cooperation'),
    ('program', {'programs': {}}, 'data/program-connector'),
])
def test_omitted_backend_discriminators_use_worker_defaults(tmp_path, kind, extra, state):
    update, target = fixture(tmp_path)
    (target / 'cooperation.yaml').unlink()
    (target / 'custom.json').write_text(json.dumps({
        'agent_id': 'pc-a', 'connection_config': 'config.yaml', **extra}))
    with InstanceLock(target / state), pytest.raises(RuntimeError):
        updater()['apply_update'](update, target)


def test_explicit_external_profile_kind_and_canonical_state_aliases(tmp_path):
    update, target = fixture(tmp_path)
    external = tmp_path / 'external'
    external.mkdir()
    profile = external / 'custom.yaml'
    profile.write_text('agent_id: pc-b\nconnection_config: ../LabOS (existing)/config.yaml\n')
    alias = external / 'profile-alias.yaml'
    alias.symlink_to(profile)
    with InstanceLock(external / 'data/program-connector'), pytest.raises(RuntimeError):
        updater()['apply_update'](update, target, [('program', profile), ('program', alias)])
    backup = updater()['apply_update'](update, target,
                                       [('program', profile), ('program', alias)])
    transaction = json.loads((backup / 'transaction.json').read_text())
    assert len(transaction['profiles']) == 2
    assert {p['state_dir'] for p in transaction['profiles']} == {
        str(external / 'data/program-connector'), str(target / 'data/cooperation')}
    with InstanceLock(external / 'data/program-connector'), pytest.raises(RuntimeError):
        updater()['recover_update'](target, backup.name)
    updater()['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_state_aliases_are_locked_once_and_in_canonical_order(tmp_path):
    update, target = fixture(tmp_path)
    external = tmp_path / 'external-state'
    external.mkdir()
    (target / 'state-alias').symlink_to(external, target_is_directory=True)
    (target / 'a.json').write_text(json.dumps({
        'agent_id': 'pc-a', 'connection_config': 'config.yaml', 'state_dir': 'state-alias'}))
    (target / 'b.yaml').write_text(
        f'agent_id: pc-b\nconnection_config: config.yaml\nstate_dir: {external}\n')
    backup = updater()['apply_update'](update, target)
    assert (external / 'instance.lock').is_file()
    assert json.loads((backup / 'transaction.json').read_text())['status'] == 'committed'


@pytest.mark.parametrize('event', ['inventory', 'backup1', 'backup2', 'prepared', 'applying'])
@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_preparation_interruption_never_changes_payload_and_retains_evidence(
        tmp_path, monkeypatch, event, boundary):
    update, target = fixture(tmp_path)
    add_payload(update, 'src/labos/second.py', b'new second')
    second = target / 'src/labos/second.py'
    second.parent.mkdir(parents=True)
    second.write_bytes(b'old second')
    api = updater()
    original = api['atomic_write']
    backups = 0

    def fault(path, content):
        nonlocal backups
        hit = False
        path = Path(path)
        if path.name == 'transaction.json':
            status = json.loads(content)['status']
            hit = status == {'inventory': 'preparing'}.get(event, event)
        elif path.is_relative_to(target / 'data/pilot-update-backups'):
            backups += 1
            hit = event == 'backup' + str(backups)
        if hit and boundary == 'before':
            raise KeyboardInterrupt()
        original(path, content)
        if hit and boundary == 'after':
            raise KeyboardInterrupt()

    monkeypatch.setitem(api, 'atomic_write', fault)
    with pytest.raises(KeyboardInterrupt):
        api['apply_update'](update, target)
    backup = transaction_dir(target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'
    assert second.read_bytes() == b'old second'
    with pytest.raises(RuntimeError, match=backup.name):
        updater()['apply_update'](update, target)
    complete = event in {'prepared', 'applying'} or (event == 'backup2' and boundary == 'after')
    if complete:
        updater()['recover_update'](target, backup.name)
        assert json.loads((backup / 'transaction.json').read_text())['status'] == 'recovered'
    else:
        with pytest.raises((ValueError, RuntimeError)):
            updater()['recover_update'](target, backup.name)


def test_rollback_failure_retains_exact_transaction_and_allows_explicit_retry(tmp_path, monkeypatch):
    update, target = fixture(tmp_path)
    add_payload(update, 'src/labos/new.py', b'new module')
    api = updater()
    original = api['atomic_write']

    def fault(path, content):
        if Path(path) == target / 'src/labos/new.py':
            raise OSError('replacement failure')
        if Path(path) == target / 'Check-Pilot-Runtime.py' and content == b'# previous runtime check\n':
            raise OSError('restore failure')
        original(path, content)

    monkeypatch.setitem(api, 'atomic_write', fault)
    with pytest.raises(RuntimeError, match='explicitly recover transaction') as error:
        api['apply_update'](update, target)
    backup = transaction_dir(target)
    assert backup.name in str(error.value)
    assert json.loads((backup / 'transaction.json').read_text())['status'] == 'rolling_back'
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# new runtime check\n'
    updater()['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_recovery_interruption_is_idempotent_after_some_files_restored(tmp_path, monkeypatch, boundary):
    update, target = fixture(tmp_path)
    add_payload(update, 'src/labos/new.py', b'new module')
    backup = updater()['apply_update'](update, target)
    api = updater()
    original = api['atomic_write']

    def fault(path, content):
        hit = Path(path) == target / 'Check-Pilot-Runtime.py'
        if hit and boundary == 'before':
            raise KeyboardInterrupt()
        original(path, content)
        if hit and boundary == 'after':
            raise KeyboardInterrupt()

    monkeypatch.setitem(api, 'atomic_write', fault)
    with pytest.raises(KeyboardInterrupt):
        api['recover_update'](target, backup.name)
    updater()['recover_update'](target, backup.name)
    updater()['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'
    assert not (target / 'src/labos/new.py').exists()


@pytest.mark.parametrize('name', ['yaml.py', 'python/Lib/site-packages/yaml/__init__.py',
    'python/Lib/site-packages/_yaml.cp311-win_amd64.pyd',
    'python/Lib/site-packages/PyYAML-6.0.dist-info/METADATA',
    'src/labos/local.yaml', 'connection.json'])
def test_parser_and_configuration_payloads_are_protected(tmp_path, name):
    update, target = fixture(tmp_path)
    add_payload(update, name, b'synthetic parser/config payload')
    with pytest.raises(ValueError):
        updater()['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_actual_nested_json_connection_configuration_is_protected(tmp_path):
    update, target = fixture(tmp_path)
    connection = target / 'src/labos/private.json'
    connection.parent.mkdir(parents=True)
    connection.write_bytes(b'{"token":"synthetic-test-token"}')
    (target / 'cooperation.yaml').write_text(
        'role: pc\nagent_id: pc-a\nconnection_config: src/labos/private.json\n')
    add_payload(update, 'src/labos/private.json', b'{}')
    with pytest.raises(ValueError):
        updater()['apply_update'](update, target)
    assert connection.read_bytes() == b'{"token":"synthetic-test-token"}'


def test_documentation_payload_and_disabled_template_exclusions_support_recovery(tmp_path):
    update, target = fixture(tmp_path)
    add_payload(update, 'OPTICAL_READBACK_PLAN.json', b'{"document_type":"example-plan"}')
    add_payload(update, 'pilot-worker.example.yaml', b'agent_id: pc-a\napproval: null\n')
    (target / 'unrelated.json').write_bytes(b'{"notes":"preserve"}')
    backup = updater()['apply_update'](update, target)
    updater()['recover_update'](target, backup.name)
    assert not (target / 'OPTICAL_READBACK_PLAN.json').exists()
    assert not (target / 'pilot-worker.example.yaml').exists()
    assert (target / 'unrelated.json').read_bytes() == b'{"notes":"preserve"}'


def test_updater_lock_precedes_unresolved_transaction_inspection(tmp_path):
    update, target = fixture(tmp_path)
    incomplete = target / 'data/pilot-update-backups/incomplete'
    incomplete.mkdir(parents=True)
    with InstanceLock(target / 'data/pilot-update-control'), pytest.raises(RuntimeError, match='owns'):
        updater()['apply_update'](update, target)


def test_prior_backups_are_retained_and_corrupt_journals_block_apply(tmp_path):
    update, target = fixture(tmp_path)
    first = updater()['apply_update'](update, target)
    original = (first / 'Check-Pilot-Runtime.py').read_bytes()
    second = updater()['apply_update'](update, target)
    assert first != second
    assert (first / 'Check-Pilot-Runtime.py').read_bytes() == original
    (first / 'transaction.json').write_bytes(b'{broken')
    with pytest.raises(RuntimeError, match=first.name):
        updater()['apply_update'](update, target)


@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_commit_marker_write_errors_never_leave_terminal_journal_over_partial_rollback(
        tmp_path, monkeypatch, boundary):
    update, target = fixture(tmp_path)
    api = updater()
    original = api['atomic_write']

    def fault(path, content):
        hit = Path(path).name == 'transaction.json' and json.loads(content)['status'] == 'committed'
        if hit and boundary == 'before':
            raise OSError('commit replace failed')
        original(path, content)
        if hit and boundary == 'after':
            raise OSError('post-replace directory fsync failed')

    monkeypatch.setitem(api, 'atomic_write', fault)
    with pytest.raises((OSError, RuntimeError)):
        api['apply_update'](update, target)
    backup = transaction_dir(target)
    status = json.loads((backup / 'transaction.json').read_text())['status']
    if boundary == 'before':
        assert status == 'recovered'
        assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'
    else:
        assert status == 'committed'
        assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# new runtime check\n'


@pytest.mark.parametrize('status', ['rolling_back', 'recovered'])
@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_recovery_metadata_failures_preserve_truth_and_allow_retry(tmp_path, monkeypatch, status, boundary):
    update, target = fixture(tmp_path)
    backup = updater()['apply_update'](update, target)
    api = updater()
    original = api['atomic_write']

    def fault(path, content):
        hit = Path(path).name == 'transaction.json' and json.loads(content)['status'] == status
        if hit and boundary == 'before':
            raise OSError('metadata replace failed')
        original(path, content)
        if hit and boundary == 'after':
            raise OSError('metadata directory fsync failed')

    monkeypatch.setitem(api, 'atomic_write', fault)
    with pytest.raises(OSError):
        api['recover_update'](target, backup.name)
    current = json.loads((backup / 'transaction.json').read_text())['status']
    if status == 'rolling_back':
        assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# new runtime check\n'
        assert current == ('committed' if boundary == 'before' else 'rolling_back')
    else:
        assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'
        assert current == ('rolling_back' if boundary == 'before' else 'recovered')
    updater()['recover_update'](target, backup.name)
    assert json.loads((backup / 'transaction.json').read_text())['status'] == 'recovered'


def test_cli_refusal_and_recovery_never_import_overlay_or_target_code(tmp_path):
    import shutil
    import subprocess
    import sys

    update, target = fixture(tmp_path)
    marker = tmp_path / 'unexpected-import'
    sentinel = f'from pathlib import Path\nPath({str(marker)!r}).write_text("imported")\nraise RuntimeError("forbidden import")\n'
    for root in [update / 'overlay/src', target / 'src', target / 'python/Lib/site-packages']:
        package = root / 'labos'
        package.mkdir(parents=True, exist_ok=True)
        (package / '__init__.py').write_text(sentinel)
    add_payload(update, 'src/labos/__init__.py', sentinel.encode())
    shutil.copyfile(APPLY, update / 'Apply-Pilot-Update.py')
    command = [sys.executable, '-I', str(update / 'Apply-Pilot-Update.py'), '--target', str(target)]
    (update / 'overlay/Check-Pilot-Runtime.py').write_bytes(b'tampered')
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert 'checksum' in result.stderr
    assert not marker.exists()
    (update / 'overlay/Check-Pilot-Runtime.py').write_bytes(b'# new runtime check\n')
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    backup = transaction_dir(target)
    # Corrupt installed LabOS and parser files: recovery uses no target imports.
    (target / 'python/Lib/site-packages/yaml.py').write_text(sentinel)
    result = subprocess.run(command + ['--recover', backup.name], capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_fresh_process_loss_recovery_uses_no_labos_or_yaml_imports(tmp_path):
    import subprocess
    import sys

    update, target = fixture(tmp_path)
    script = '''import os, runpy, sys
from pathlib import Path
api = runpy.run_path(sys.argv[1])['apply_update'].__globals__
original = api['atomic_write']
def interrupt(path, content):
    original(path, content)
    if Path(path) == Path(sys.argv[3]) / 'Check-Pilot-Runtime.py':
        os._exit(77)
api['atomic_write'] = interrupt
api['apply_update'](sys.argv[2], sys.argv[3])
'''
    result = subprocess.run([sys.executable, '-I', '-c', script, str(APPLY), str(update), str(target)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 77, result.stderr
    backup = transaction_dir(target)
    recovery = '''import runpy, sys
class RejectControlPlaneImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'labos', 'yaml', '_yaml'}:
            raise AssertionError('Recovery attempted forbidden import: ' + fullname)
sys.meta_path.insert(0, RejectControlPlaneImports())
runpy.run_path(sys.argv[1])['recover_update'](sys.argv[2], sys.argv[3])
'''
    result = subprocess.run([sys.executable, '-I', '-c', recovery, str(APPLY), str(target), backup.name],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


@pytest.mark.parametrize('extra', [
    {'backend': []}, {'backend': 'unknown'}, {'role': []},
    {'state_dir': 123}, {'programs': []}, {'agent_id': 'invalid agent name'},
])
def test_malformed_recognized_profile_fields_fail_closed(tmp_path, extra):
    update, target = fixture(tmp_path)
    (target / 'custom.json').write_text(json.dumps({
        'agent_id': 'pc-a', 'connection_config': 'config.yaml', 'state_dir': 'data/custom', **extra}))
    with pytest.raises(ValueError):
        updater()['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_mutated_journal_lock_inventory_is_corrupt_evidence_not_authority(tmp_path):
    update, target = fixture(tmp_path)
    backup = updater()['apply_update'](update, target)
    path = backup / 'transaction.json'
    journal = json.loads(path.read_text())
    journal['profiles'][0]['state_dir'] = str(tmp_path / 'incorrect-lock')
    path.write_text(json.dumps(journal))
    with pytest.raises(RuntimeError, match=backup.name):
        updater()['recover_update'](target, backup.name)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# new runtime check\n'


@pytest.mark.parametrize('name', ['python/Lib/site-packages/custom-loader.pth',
    'python/Lib/site-packages/sitecustomize.py', 'python/Lib/site-packages/usercustomize.py'])
def test_interpreter_startup_hooks_cannot_replace_recovery_prerequisites(tmp_path, name):
    update, target = fixture(tmp_path)
    add_payload(update, name, b'raise RuntimeError("untrusted startup hook")')
    with pytest.raises(ValueError):
        updater()['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_recovery_interruption_at_introduced_file_removal_is_idempotent(tmp_path, monkeypatch, boundary):
    update, target = fixture(tmp_path)
    add_payload(update, 'src/labos/new.py', b'new module')
    backup = updater()['apply_update'](update, target)
    introduced = target / 'src/labos/new.py'
    original = Path.unlink

    def fault(path, *args, **kwargs):
        if path == introduced and boundary == 'before':
            raise KeyboardInterrupt()
        result = original(path, *args, **kwargs)
        if path == introduced and boundary == 'after':
            raise KeyboardInterrupt()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', fault)
        with pytest.raises(KeyboardInterrupt):
            updater()['recover_update'](target, backup.name)
    updater()['recover_update'](target, backup.name)
    assert not introduced.exists()
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_new_active_profile_before_recovery_refuses_without_payload_or_evidence_changes(tmp_path):
    update, target = fixture(tmp_path)
    backup = updater()['apply_update'](update, target)
    (target / 'new-worker.yaml').write_text(
        'agent_id: pc-b\nconnection_config: config.yaml\nstate_dir: data/new-worker\n')
    evidence = (backup / 'transaction.json').read_bytes()
    with InstanceLock(target / 'data/new-worker'), pytest.raises(ValueError):
        updater()['recover_update'](target, backup.name)
    assert (backup / 'transaction.json').read_bytes() == evidence
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# new runtime check\n'


def test_recovery_rechecks_destination_before_each_mutation(tmp_path, monkeypatch):
    update, target = fixture(tmp_path)
    add_payload(update, 'src/labos/z_last.py', b'new last')
    last = target / 'src/labos/z_last.py'
    last.parent.mkdir(parents=True)
    last.write_bytes(b'old last')
    backup = updater()['apply_update'](update, target)
    api = updater()
    original = api['atomic_write']

    def edit_after_first_restore(path, content):
        original(path, content)
        if Path(path) == target / 'Check-Pilot-Runtime.py':
            last.write_bytes(b'concurrent user edit')

    monkeypatch.setitem(api, 'atomic_write', edit_after_first_restore)
    with pytest.raises(ValueError, match='changed during recovery'):
        api['recover_update'](target, backup.name)
    assert last.read_bytes() == b'concurrent user edit'
    assert json.loads((backup / 'transaction.json').read_text())['status'] == 'rolling_back'


@pytest.mark.parametrize('location', ['destination', 'backup', 'control', 'root_profile'])
def test_symlink_substitution_is_not_followed(tmp_path, location):
    update, target = fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    if location == 'destination':
        (target / 'Check-Pilot-Runtime.py').unlink()
        (outside / 'previous.py').write_bytes(b'outside bytes')
        (target / 'Check-Pilot-Runtime.py').symlink_to(outside / 'previous.py')
    elif location in {'backup', 'control'}:
        (target / 'data').mkdir()
        (target / 'data' / ('pilot-update-backups' if location == 'backup'
                            else 'pilot-update-control')).symlink_to(outside, target_is_directory=True)
    else:
        (target / 'custom.yaml').symlink_to(target / 'cooperation.yaml')
    with pytest.raises(ValueError):
        updater()['apply_update'](update, target)
    assert not (outside / 'instance.lock').exists()
    if location == 'destination':
        assert (outside / 'previous.py').read_bytes() == b'outside bytes'
    else:
        assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


@pytest.mark.parametrize('name', ['python/Lib/site-packages/yaml.pyc',
    'python/Lib/site-packages/sitecustomize/__init__.py',
    'python/Lib/site-packages/usercustomize.pyc'])
def test_parser_and_startup_module_variants_cannot_replace_bootstrap(tmp_path, name):
    update, target = fixture(tmp_path)
    add_payload(update, name, b'synthetic bootstrap module')
    with pytest.raises(ValueError):
        updater()['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_shipped_pilot_template_with_explicitly_disabled_approval_is_accepted(tmp_path):
    update, target = fixture(tmp_path)
    template = (APPLY.parent / 'pilot-worker.example.yaml').read_bytes()
    add_payload(update, 'pilot-worker.example.yaml', template)
    backup = updater()['apply_update'](update, target)
    assert (target / 'pilot-worker.example.yaml').read_bytes() == template
    updater()['recover_update'](target, backup.name)
    assert not (target / 'pilot-worker.example.yaml').exists()


@pytest.mark.parametrize('approval', [{'enabled': True}, {}, 'invalid', {'enabled': 0}])
def test_template_with_enabled_or_ambiguous_approval_is_refused(tmp_path, approval):
    import yaml

    update, target = fixture(tmp_path)
    add_payload(update, 'pilot-worker.example.yaml', yaml.safe_dump({'approval': approval}).encode())
    with pytest.raises(ValueError):
        updater()['apply_update'](update, target)
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_cli_uses_base_parser_when_update_folder_contains_sibling_yaml_module(tmp_path):
    import shutil
    import subprocess
    import sys

    update, target = fixture(tmp_path)
    shutil.copyfile(APPLY, update / 'Apply-Pilot-Update.py')
    marker = tmp_path / 'shadow-parser-imported'
    (update / 'yaml.py').write_text(
        f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n'
        'raise RuntimeError("untrusted sibling parser")\n')
    (update / 'overlay/Check-Pilot-Runtime.py').write_bytes(b'tampered')
    result = subprocess.run([sys.executable, str(update / 'Apply-Pilot-Update.py'),
                             '--target', str(target)], cwd=update, capture_output=True,
                            text=True, check=False)
    assert result.returncode == 1
    assert not marker.exists()
    assert 'checksum' in result.stderr


def test_cli_refuses_nonbase_parser_package_before_executing_it(tmp_path):
    import os
    import shutil
    import subprocess
    import sys

    update, target = fixture(tmp_path)
    shutil.copyfile(APPLY, update / 'Apply-Pilot-Update.py')
    shadow = tmp_path / 'untrusted-pythonpath'
    package = shadow / 'yaml'
    package.mkdir(parents=True)
    marker = tmp_path / 'external-parser-imported'
    (package / '__init__.py').write_text(
        f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n'
        'raise RuntimeError("nonbase parser")\n')
    environment = dict(os.environ, PYTHONPATH=str(shadow))
    result = subprocess.run([sys.executable, str(update / 'Apply-Pilot-Update.py'),
                             '--target', str(target)], cwd=target, env=environment,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert not marker.exists()
    assert 'base site-packages' in result.stderr
    assert (target / 'Check-Pilot-Runtime.py').read_bytes() == b'# previous runtime check\n'


def test_apply_restores_import_search_path_after_using_trusted_base_parser(tmp_path):
    import sys

    update, target = fixture(tmp_path)
    before = sys.path[:]
    updater()['apply_update'](update, target)
    assert sys.path == before
