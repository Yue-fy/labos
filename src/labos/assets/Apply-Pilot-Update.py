"""Apply or explicitly recover an overlay while every configured worker is stopped.

The recovery control plane is standard-library-only. Never import installed or
payload LabOS code here: it may be precisely the code interrupted by an update.
"""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import sysconfig
import uuid


BACKUPS = 'data/pilot-update-backups'
CONTROL = 'data/pilot-update-control'
TERMINAL = {'committed', 'recovered'}
STATUSES = TERMINAL | {'preparing', 'prepared', 'applying', 'rolling_back'}
DEFAULT_STATES = {'pilot': 'data/physical-pilot', 'program': 'data/program-connector',
                  'report': 'data/cooperation'}
KNOWN = {'cooperation': 'report', 'pilot-worker': 'pilot', 'dark-a-worker': 'pilot',
         'optical-readback-worker': 'pilot', 'program-connector': 'program'}
# These shipped records are documentation, never worker/connection configuration.
DOCUMENT_JSON = {
    'CRYOSTAT_PILOT_PLAN.json', 'CRYOSTAT_PILOT_SOURCE_REQUESTS.json',
    'DARK_A_VOLTAGE_PLAN.json', 'OPTICAL_READBACK_PLAN.json',
    'PC_INTAKE_TEMPLATE.json', 'PM100D_SOURCE_REQUESTS.json', 'SERVER_REPLY_TEMPLATE.json',
}
PROFILE_KEYS = {'agent_id', 'connection_config', 'state_dir', 'backend', 'programs', 'role'}


def _hash(content):
    return hashlib.sha256(content).hexdigest()


def _no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlink is not permitted in update control or payload paths')


def _sync_directory(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write(path, content):
    """Flush a same-directory temporary file before atomic replacement."""
    _no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _no_symlinks(path)
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class InstanceLock:
    """The same OS advisory instance.lock protocol as labos.files.InstanceLock."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.handle = None

    def __enter__(self):
        _no_symlinks(self.directory / 'instance.lock')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.handle = (self.directory / 'instance.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                self.handle.write(b'0')
                self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            raise RuntimeError('Another process owns a worker or updater directory') from exc
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()


def _target(target):
    target = Path(target).absolute()
    _no_symlinks(target)
    target = target.resolve()
    if not target.is_dir():
        raise ValueError('Select an existing provisioned installation')
    _no_symlinks(target / BACKUPS)
    _no_symlinks(target / CONTROL)
    return target


def _snapshot(path):
    _no_symlinks(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('Expected a regular file')
    return _hash(path.read_bytes())


def _document_json(path):
    if path.name not in DOCUMENT_JSON:
        return False
    # An operator turning a documentation record into configuration is a conflict.
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Malformed documentation JSON candidate') from exc
    if isinstance(value, dict) and PROFILE_KEYS.intersection(value):
        return False
    return True


def _root_inventory(target):
    inventory = {}
    for path in sorted(target.iterdir()):
        if path.suffix.lower() not in {'.yaml', '.yml', '.json'}:
            continue
        if path.name.endswith(('.example.yaml', '.example.yml', '.example.json')):
            continue
        _no_symlinks(path)
        if _document_json(path):
            continue
        inventory[str(path)] = _snapshot(path)
    return inventory


def _profile_args(profiles, target):
    result = {}
    for entry in profiles or ():
        kind = None
        if isinstance(entry, tuple):
            kind, entry = entry
        elif isinstance(entry, str) and '=' in entry:
            kind, entry = entry.split('=', 1)
        if kind is not None and kind not in DEFAULT_STATES:
            raise ValueError('Explicit profile kind must be pilot, program or report')
        path = Path(entry)
        path = (path if path.is_absolute() else target / path).resolve()
        if str(path) in result and result[str(path)] != kind:
            raise ValueError('Conflicting explicit profile kinds')
        result[str(path)] = kind
    return result


def _trusted_yaml(update):
    """Resolve the existing interpreter's package before executing parser code."""
    untrusted = {update.resolve(), Path.cwd().resolve()}
    bases = {Path(sysconfig.get_path(key)).resolve() for key in ('purelib', 'platlib')}
    # The Windows embedded runtime uses this independently provisioned layout.
    bases.add((Path(sys.executable).resolve().parent / 'Lib/site-packages').resolve())
    previous = sys.path[:]
    try:
        sys.path[:] = [entry for entry in previous if not any(
            Path(entry or '.').resolve().is_relative_to(root) for root in untrusted)]
        spec = importlib.util.find_spec('yaml')
        if spec is None or spec.origin is None or spec.submodule_search_locations is None:
            raise ValueError('An independently trusted existing base PyYAML package is required')
        origin = Path(spec.origin).resolve()
        if (any(origin.is_relative_to(root) for root in untrusted)
                or not any(origin == base / 'yaml/__init__.py' for base in bases)):
            raise ValueError('PyYAML must come from the existing interpreter base site-packages')
        if 'yaml' not in sys.modules:
            module = importlib.util.module_from_spec(spec)
            sys.modules['yaml'] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop('yaml', None)
                raise
        return sys.modules['yaml']
    finally:
        sys.path[:] = previous


def _discover(target, profiles, yaml):
    root = _root_inventory(target)
    explicit = _profile_args(profiles, target)
    paths = sorted(set(root) | set(explicit))
    records, protected = [], set(root)
    for name in paths:
        path = Path(name)
        digest = _snapshot(path)
        if digest is None:
            raise ValueError('Configuration candidate is missing')
        text = path.read_text(encoding='utf-8-sig')
        try:
            values = json.loads(text) if path.suffix.lower() == '.json' else yaml.safe_load(text)
        except (ValueError, yaml.YAMLError) as exc:
            raise ValueError('Malformed configuration candidate: ' + path.name) from exc
        known = KNOWN.get(path.stem.lower())
        declared = explicit.get(name)
        mandatory = known is not None or name in explicit
        possible = isinstance(values, dict) and bool(
            {'connection_config', 'state_dir', 'programs', 'backend'} & values.keys())
        if not mandatory and not possible:
            continue
        if not isinstance(values, dict) or not all(
                isinstance(values.get(key), str) and values[key].strip()
                for key in ('agent_id', 'connection_config')):
            raise ValueError('Malformed worker profile: ' + path.name)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', values['agent_id']):
            raise ValueError('Malformed worker agent identity')
        if 'role' in values and values['role'] not in ('pc', 'central'):
            raise ValueError('Malformed worker role')
        if 'backend' in values and values['backend'] not in ('pilot', 'codex', 'local'):
            raise ValueError('Malformed worker backend')
        if 'programs' in values and not isinstance(values['programs'], dict):
            raise ValueError('Malformed program profile')
        kinds = set()
        if known:
            kinds.add(known)
        if declared:
            kinds.add(declared)
        backend = values.get('backend')
        if backend == 'pilot' or {'adapter_id', 'adapter_config', 'approval'} & values.keys():
            kinds.add('pilot')
        if 'programs' in values:
            kinds.add('program')
        if backend in {'codex', 'local'} or {'codex_command', 'local_url', 'local_model'} & values.keys():
            kinds.add('report')
        if len(kinds) > 1:
            raise ValueError('Conflicting worker kind declarations')
        kind = next(iter(kinds), 'explicit-state')
        state = values.get('state_dir')
        if state is None:
            if kind not in DEFAULT_STATES:
                raise ValueError('Ambiguous profile: declare its kind or explicit state_dir')
            state = DEFAULT_STATES[kind]
        if not isinstance(state, str) or not state.strip():
            raise ValueError('Malformed worker state_dir')
        state = Path(state)
        state = (state if state.is_absolute() else path.parent / state).resolve()
        connection = Path(values['connection_config'])
        connection = (connection if connection.is_absolute() else path.parent / connection).resolve()
        connection_hash = _snapshot(connection)
        if connection_hash is None:
            raise ValueError('Worker connection configuration is missing')
        protected.update((name, str(connection)))
        records.append({'path': name, 'sha256': digest, 'kind': kind,
                        'state_dir': str(state), 'connection': str(connection),
                        'connection_sha256': connection_hash})
    if not records:
        raise ValueError('No recognized worker profiles; declare nonstandard profiles explicitly')
    return root, explicit, records, protected


def _payload_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('Invalid payload path')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {'', '.', '..'} for p in name.split('/')):
        raise ValueError('Invalid payload path')
    # Windows aliases and device names must not redirect writes on a portable target.
    for part in path.parts:
        if (part.endswith(('.', ' ')) or any(c in part for c in '<>"|?*')
                or any(ord(c) < 32 for c in part)
                or re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?', part, re.I)):
            raise ValueError('Invalid portable payload path')
    if len(path.parts) == 1:
        allowed = path.suffix in {'.py', '.ps1', '.cmd', '.md', '.json'}
        if not allowed and name != 'pilot-worker.example.yaml':
            raise ValueError('Protected root payload path')
        if path.suffix == '.json' and name not in DOCUMENT_JSON:
            raise ValueError('Only shipped nonconfiguration JSON records may be updated')
    elif not (name.startswith('src/labos/') or name.startswith('python/Lib/site-packages/')):
        raise ValueError('Protected payload path')
    if path.suffix.lower() in {'.yaml', '.yml'} and name != 'pilot-worker.example.yaml':
        raise ValueError('Live YAML cannot be an update payload')
    parser_parts = [part.lower() for part in path.parts]
    if path.suffix.lower() == '.pth' or any(
            part.split('.')[0] in {'sitecustomize', 'usercustomize'} for part in parser_parts):
        raise ValueError('Interpreter startup hooks are not an update target')
    if any(part.split('.')[0] in {'yaml', '_yaml'}
           or part.startswith(('pyyaml-', 'pyyaml.')) for part in parser_parts):
        raise ValueError('The trusted base YAML parser is not an update target')
    return name


def _load_payload(update, target, protected, records, yaml):
    manifest = json.loads((update / 'payload-manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('Invalid update manifest')
    entries = manifest.get('files')
    if not isinstance(entries, dict) or not entries:
        raise ValueError('Missing update payload manifest')
    contents, aliases = {}, set()
    for name, digest in sorted(entries.items()):
        _payload_name(name)
        alias = name.casefold()
        if alias in aliases:
            raise ValueError('Payload paths alias on Windows')
        aliases.add(alias)
        source, destination = update / 'overlay' / name, target / name
        _no_symlinks(source)
        _snapshot(destination)
        if str(destination) in protected or any(
                destination.is_relative_to(Path(record['state_dir'])) for record in records):
            raise ValueError('Payload would replace live configuration or worker state')
        content = source.read_bytes()
        if not isinstance(digest, str) or _hash(content) != digest:
            raise ValueError('Update payload checksum mismatch')
        if name == 'pilot-worker.example.yaml':
            # This template must remain disabled, without local approval or executable code.
            try:
                template = yaml.safe_load(content)
            except yaml.YAMLError as exc:
                raise ValueError('Malformed pilot template') from exc
            if not isinstance(template, dict):
                raise ValueError('Malformed pilot template')
            approval = template.get('approval')
            if approval is not None and not (
                    isinstance(approval, dict) and approval.get('enabled') is False):
                raise ValueError('Pilot template must have explicitly disabled physical approval')
        if name in DOCUMENT_JSON:
            value = json.loads(content)
            if isinstance(value, dict) and PROFILE_KEYS.intersection(value):
                raise ValueError('Documentation JSON cannot carry worker configuration')
        contents[name] = content
    return contents, manifest.get('version')


def _journal_digest(journal):
    inventory = {key: value for key, value in journal.items() if key != 'journal_sha256'}
    return _hash(json.dumps(inventory, sort_keys=True, separators=(',', ':'),
                            allow_nan=False).encode())


def _save_journal(backup, journal, status):
    value = dict(journal, status=status)
    value['journal_sha256'] = _journal_digest(value)
    atomic_write(backup / 'transaction.json',
                 (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
    journal['status'] = status


def _valid_digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _load_journal(backup, target):
    try:
        _no_symlinks(backup)
        _snapshot(backup / 'transaction.json')
        journal = json.loads((backup / 'transaction.json').read_text(encoding='utf-8'))
        if (not isinstance(journal, dict)
                or journal.get('journal_sha256') != _journal_digest(journal)):
            raise ValueError('Transaction integrity checksum mismatch')
        if (journal['schema_version'] != 1 or journal['transaction_id'] != backup.name
                or journal['target'] != str(target) or journal['status'] not in STATUSES
                or not isinstance(journal['files'], dict) or not journal['files']
                or not isinstance(journal['root_candidates'], dict)
                or not isinstance(journal['explicit_profiles'], dict)
                or not isinstance(journal['profiles'], list) or not journal['profiles']):
            raise ValueError('Invalid transaction structure')
        for name, hashes in journal['files'].items():
            _payload_name(name)
            if (set(hashes) != {'old', 'new'} or not _valid_digest(hashes['new'])
                    or hashes['old'] is not None and not _valid_digest(hashes['old'])):
                raise ValueError('Invalid transaction file inventory')
        for name, digest in journal['root_candidates'].items():
            if (Path(name).parent != target or not _valid_digest(digest)):
                raise ValueError('Invalid configuration inventory')
        for profile in journal['profiles']:
            for key in ('path', 'state_dir', 'connection'):
                if not Path(profile[key]).is_absolute():
                    raise ValueError('Invalid recorded profile path')
            if not all(_valid_digest(profile[key]) for key in ('sha256', 'connection_sha256')):
                raise ValueError('Invalid profile hashes')
            if profile['kind'] not in {*DEFAULT_STATES, 'explicit-state'}:
                raise ValueError('Invalid profile kind')
        return journal
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError('Corrupt or incomplete transaction ' + backup.name) from exc


def _check_unresolved(target):
    root = target / BACKUPS
    if root.exists():
        for backup in sorted(root.iterdir()):
            if not backup.is_dir():
                raise RuntimeError('Unrecognized update backup evidence: ' + backup.name)
            journal = _load_journal(backup, target)
            if journal['status'] not in TERMINAL:
                raise RuntimeError('Unresolved update transaction ' + backup.name
                                   + '; use explicit recovery')


def _check_profiles(target, journal):
    if _root_inventory(target) != journal['root_candidates']:
        raise ValueError('Configuration candidates changed, disappeared or were added; recovery refused')
    for profile in journal['profiles']:
        if (_snapshot(Path(profile['path'])) != profile['sha256']
                or _snapshot(Path(profile['connection'])) != profile['connection_sha256']):
            raise ValueError('Recorded profile or connection configuration changed')
    for path in journal['explicit_profiles']:
        if path not in {p['path'] for p in journal['profiles']}:
            raise ValueError('Incomplete explicit profile inventory')


def _worker_locks(stack, records):
    for state in sorted({record['state_dir'] for record in records}):
        _no_symlinks(Path(state))
        stack.enter_context(InstanceLock(state))


def _preflight_restore(target, backup, journal):
    _check_profiles(target, journal)
    for name, hashes in journal['files'].items():
        current = _snapshot(target / name)
        if current not in {hashes['old'], hashes['new']}:
            raise ValueError('Unknown destination bytes or missing original: ' + name)
        if hashes['old'] is not None and _snapshot(backup / name) != hashes['old']:
            raise ValueError('Required original backup is missing or corrupt: ' + name)


def _restore(target, backup, journal):
    # Preflight every entry before publishing rollback or changing any payload.
    _preflight_restore(target, backup, journal)
    _save_journal(backup, journal, 'rolling_back')
    for name, hashes in journal['files'].items():
        destination = target / name
        current = _snapshot(destination)
        if current not in {hashes['old'], hashes['new']}:
            raise ValueError('Destination changed during recovery: ' + name)
        if current == hashes['old']:
            continue
        if hashes['old'] is None:
            destination.unlink()
            _sync_directory(destination.parent)
        else:
            content = (backup / name).read_bytes()
            if _hash(content) != hashes['old']:
                raise ValueError('Backup changed during recovery')
            atomic_write(destination, content)
    for name, hashes in journal['files'].items():
        if _snapshot(target / name) != hashes['old']:
            raise ValueError('Restored payload hash mismatch')
    _save_journal(backup, journal, 'recovered')


def apply_update(update, target, profiles=None):
    """Apply verified files; optional profiles are paths or (kind, path) pairs."""
    update, target = Path(update).resolve(), _target(target)
    with ExitStack() as locks:
        locks.enter_context(InstanceLock(target / CONTROL))
        _check_unresolved(target)
        yaml = _trusted_yaml(update)
        root, explicit, records, protected = _discover(target, profiles, yaml)
        contents, version = _load_payload(update, target, protected, records, yaml)
        _worker_locks(locks, records)
        transaction_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
        backup = target / BACKUPS / transaction_id
        journal = {'schema_version': 1, 'transaction_id': transaction_id, 'target': str(target),
                   'version': version, 'root_candidates': root, 'explicit_profiles': explicit,
                   'profiles': records, 'files': {name: {'old': _snapshot(target / name),
                   'new': _hash(content)} for name, content in contents.items()}}
        _check_profiles(target, journal)
        backup.mkdir(parents=True)
        _sync_directory(backup.parent)
        _save_journal(backup, journal, 'preparing')
        # No payload mutation is possible until all originals are flushed and verified.
        for name, hashes in journal['files'].items():
            if hashes['old'] is not None:
                content = (target / name).read_bytes()
                if _hash(content) != hashes['old']:
                    raise ValueError('Original changed during backup preparation')
                atomic_write(backup / name, content)
        _preflight_restore(target, backup, journal)
        _save_journal(backup, journal, 'prepared')
        try:
            _save_journal(backup, journal, 'applying')
            _check_profiles(target, journal)
            for name, content in contents.items():
                if _snapshot(target / name) != journal['files'][name]['old']:
                    raise ValueError('Destination changed before update replacement')
                atomic_write(target / name, content)
            for name, hashes in journal['files'].items():
                if _snapshot(target / name) != hashes['new']:
                    raise ValueError('Updated payload hash mismatch')
            _save_journal(backup, journal, 'committed')
        except Exception as exc:
            # A completed commit publication is the sole commit boundary, even if
            # a later directory flush reports failure. Do not silently undo it.
            if _load_journal(backup, target)['status'] == 'committed':
                raise RuntimeError('Commit published for transaction ' + transaction_id) from exc
            try:
                _restore(target, backup, journal)
            except Exception as rollback_error:
                raise RuntimeError('Update rollback incomplete; explicitly recover transaction '
                                   + transaction_id) from rollback_error
            raise
    return backup


def recover_update(target, transaction_id):
    """Restore one verified transaction without importing LabOS or a YAML parser."""
    if not isinstance(transaction_id, str) or not re.fullmatch(
            r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}', transaction_id):
        raise ValueError('Invalid update transaction ID')
    target = _target(target)
    with ExitStack() as locks:
        locks.enter_context(InstanceLock(target / CONTROL))
        backup = target / BACKUPS / transaction_id
        journal = _load_journal(backup, target)
        _check_profiles(target, journal)
        _worker_locks(locks, journal['profiles'])
        _restore(target, backup, journal)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--profile', action='append', default=[], metavar='[KIND=]PATH',
                        help='Additional profile; kinds: pilot, program, report')
    parser.add_argument('--recover', metavar='TRANSACTION_ID', help='Explicitly restore this transaction')
    args = parser.parse_args()
    try:
        if args.recover:
            if args.profile:
                raise ValueError('Recovery uses recorded profiles; do not supply --profile')
            backup = recover_update(args.target, args.recover)
            print('LabOS update recovered. Evidence retained at ' + str(backup))
        else:
            backup = apply_update(Path(__file__).resolve().parent, args.target, args.profile)
            print('LabOS overlay applied. Originals and transaction retained at ' + str(backup))
        print('Workers remain stopped. Physical approval remains a separate local setting.')
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print('Update refused or incomplete: ' + str(exc), file=sys.stderr)
        print('Keep all transaction evidence. Use explicit recovery only after maintenance review.',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
