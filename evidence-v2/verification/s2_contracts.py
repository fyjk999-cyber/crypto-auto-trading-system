"""Isolated contract predicates, not a production verifier or security sandbox."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

CORE = frozenset('com.lowrisk.' + x for x in (
    'monitor.adapter', 'growth', 'mltrainer', 'news', 'monitor.frontend',
    'mlcollector', 'final-landing-observer'))


class ContractError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise ContractError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def hash_value(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def process_identity(process):
    require(type(process['pid']) is int and process['pid'] > 0, 'invalid PID')
    start = process['start']
    require(type(start) is str and start.endswith('Z'), 'start must be UTC ISO timestamp')
    try:
        datetime.fromisoformat(start.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ContractError('invalid start timestamp') from exc
    require(type(process['executable']) is str and process['executable'].startswith('/'),
            'invalid executable identity')


def legacy_citation(current, expected_prefix, original=None):
    require(type(expected_prefix) is str and re.fullmatch('[a-f0-9]{16}', expected_prefix),
            'invalid legacy citation')
    return {
        'citation': 'MATCH' if digest(current).startswith(expected_prefix) else 'MISMATCH',
        'original_bytes': ('NOT_RECOVERED' if original is None else
                           'RECOVERED' if digest(original).startswith(expected_prefix) else
                           'NOT_RECOVERED'),
        'formal_historical_acceptance': 'BLOCKED',
    }


def validate_evidence(raw, pinned_hash, artifacts, predecessor=None):
    """Trust pin and predecessor must come from a separately approved custody record."""
    require(hash_value(pinned_hash) and digest(raw) == pinned_hash, 'immutable bytes changed')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    record = json.loads(raw, object_pairs_hook=unique)
    require(set(record) == {'schema_version', 'run_id', 'phase', 'version', 'receipt_id',
                            'previous_sha256', 'artifacts', 'review_status'}, 'record schema')
    require(type(record['schema_version']) is int and record['schema_version'] == 1,
            'unknown evidence schema')
    require(type(record['version']) is int and record['version'] >= 1, 'version')
    for key in ('run_id', 'phase', 'receipt_id'):
        require(type(record[key]) is str and bool(record[key]), 'missing binding')
    require(record['review_status'] in ('PENDING', 'PASS', 'FAIL', 'BLOCKED'), 'review status')
    if record['version'] == 1:
        require(predecessor is None and record['previous_sha256'] is None, 'unexpected predecessor')
    else:
        require(predecessor is not None, 'missing original historical version')
        prior_raw, prior_pin, prior_artifacts, prior_predecessor = predecessor
        prior = validate_evidence(prior_raw, prior_pin, prior_artifacts, prior_predecessor)
        require(record['previous_sha256'] == prior_pin, 'wrong predecessor SHA')
        require(record['run_id'] == prior['run_id'] and record['version'] == prior['version'] + 1,
                'cross-run/version chain')
        require(record['receipt_id'] != prior['receipt_id'], 'reused receipt ID')
        ancestor = predecessor
        while ancestor is not None:
            require(record['receipt_id'] != json.loads(ancestor[0])['receipt_id'],
                    'reused historical receipt ID')
            ancestor = ancestor[3]
    refs = record['artifacts']
    require(type(refs) is list and len(refs) >= 3, 'vacuous evidence')
    require({ref['kind'] for ref in refs} >= {'receipt', 'test_log', 'source'}, 'missing evidence kind')
    require(len({ref['id'] for ref in refs}) == len(refs), 'duplicate artifact ID')
    require(set(artifacts) == {ref['id'] for ref in refs}, 'artifact inventory mismatch')
    for ref in refs:
        require(set(ref) == {'id', 'kind', 'sha256'}, 'artifact schema')
        actual = artifacts[ref['id']]
        require(type(actual['version']) is int and actual['version'] > 0,
                'invalid artifact version type')
        require(actual['run_id'] == record['run_id'] and actual['phase'] == record['phase']
                and actual['version'] == record['version'] and actual['receipt_id'] == record['receipt_id'],
                'cross-version artifact binding')
        require(hash_value(ref['sha256']) and digest(actual['bytes']) == ref['sha256'],
                'artifact SHA mismatch')
    return record


def validate_state_update(old, new, authorization, authorization_pin):
    """Pin binds exact proposed bytes; a caller-supplied actor name alone is not authority."""
    require(hash_value(authorization_pin) and digest(encode(authorization)) == authorization_pin,
            'BLOCKED: unknown update source')
    require(set(authorization) == {'actor', 'directive_sha256', 'run_id', 'old_sha256', 'new_sha256'},
            'authorization schema')
    require(authorization['actor'] == 'Codex' and hash_value(authorization['directive_sha256']),
            'BLOCKED: unauthorized actor/directive')
    require(authorization['old_sha256'] == digest(encode(old)) and
            authorization['new_sha256'] == digest(encode(new)), 'state CAS/binding')
    fields = {'run_id', 'revision', 'task_index', 'pointer', 'blocker', 'monitor_status'}
    require(set(old) == fields and set(new) == fields, 'mutable state schema')
    require(old['run_id'] == new['run_id'] == authorization['run_id'], 'state run mismatch')
    require(all(type(s[k]) is int and s[k] >= 0 for s in (old, new)
                for k in ('revision', 'task_index')), 'state counters')
    require(new['revision'] == old['revision'] + 1 and new['task_index'] >= old['task_index'],
            'illegal pointer rollback')
    require(all(type(s[k]) is str for s in (old, new)
                for k in ('pointer', 'blocker', 'monitor_status')), 'state strings')
    require(new['task_index'] != old['task_index'] or new['pointer'] == old['pointer'],
            'pointer changed without progression')
    return 'PASS'


class SafeInventoryReader:
    """Only lstat of exact approved metadata paths. No content or lock API capability."""
    def __init__(self, metadata_paths):
        self.paths = frozenset(str(Path(p).absolute()) for p in metadata_paths)

    def metadata(self, path):
        path = Path(path).absolute()
        require(str(path) in self.paths, 'unapproved metadata path')
        st = path.lstat()
        return {'device': st.st_dev, 'inode': st.st_ino, 'mode': st.st_mode,
                'uid': st.st_uid, 'gid': st.st_gid, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
                'content_integrity': 'NOT_VERIFIED'}

    def open_content(self, path, mode='rb'):
        raise PermissionError('SAFE_INVENTORY_ONLY forbids all content opens including locks')

    def acquire_lock(self, path):
        raise PermissionError('SAFE_INVENTORY_ONLY forbids lock acquisition')


def inventory(snapshot, auxiliary):
    services = snapshot['services']
    require(CORE <= set(services), 'missing core service')
    require(not (set(services) - CORE - set(auxiliary)), 'unauthorized LaunchAgent')
    require(not (CORE & set(auxiliary)), 'auxiliary cannot redefine core')
    for label, service in services.items():
        require(service['loaded'] is True and type(service['running']) is bool, 'service state unknown')
        if service['running']:
            process_identity(service)
        else:
            require(service['pid'] is None and label not in CORE, 'idle/PID mismatch')
        if label in auxiliary:
            identity = service.get('launch_identity')
            require(type(identity) is dict and set(identity) ==
                    {'executable', 'script_sha256', 'plist_sha256'}, 'missing launch identity')
            require(type(identity['executable']) is str and identity['executable'].startswith('/')
                    and hash_value(identity['script_sha256']) and hash_value(identity['plist_sha256']),
                    'invalid launch identity')
            require(service == auxiliary[label], 'auxiliary identity/state changed')
    fds = snapshot['writer_fds']
    require(type(fds) is list and fds and all(type(pid) is int and pid > 0 for pid in fds),
            'missing writer evidence')
    pids = set(fds)
    require(len(pids) == 1 and snapshot['writer']['pid'] in pids, 'nonunique writer process')
    process_identity(snapshot['writer'])
    require(type(snapshot['writer']['runtime_sha']) is str and
            re.fullmatch('[a-f0-9]{40}', snapshot['writer']['runtime_sha']), 'writer SHA')
    require(snapshot['target_disabled'] is True and snapshot['target_loaded'] is False
            and snapshot['target_pid'] is None, 'target containment')
    require(snapshot['lowrisk_disabled'] is True and snapshot['lowrisk_loaded'] is False
            and snapshot['lowrisk_pid'] is None and snapshot['port_8010'] == 'REFUSED',
            'LowRisk not safely stopped')
    return {'SAFE_INVENTORY': 'PASS', 'writer_process_count': len(pids),
            'lock_exclusivity': 'NOT_VERIFIED_NO_LOCK_PROBE',
            'FACTUAL_DATA_VERIFICATION': 'NOT_RUN', 'database_integrity': 'NOT_VERIFIED',
            'PAPER_QUALIFICATION': 'NOT_STARTED', 'SOAK_CREDIT': 0}


def full_verdict(statuses):
    require(set(statuses) == {'SAFE_INVENTORY', 'FACTUAL_DATA_VERIFICATION',
                             'IMMUTABLE_LEDGER_VALIDATION'}, 'missing required contract')
    return 'PASS' if all(v == 'PASS' for v in statuses.values()) else 'BLOCKED'
