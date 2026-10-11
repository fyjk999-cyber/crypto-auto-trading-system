import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'evidence-v2/verification'))

from s2_contracts import (CORE, ContractError, SafeInventoryReader, digest, encode,
                       full_verdict, inventory, legacy_citation, validate_evidence,
                       validate_state_update)


def evidence(version=1):
    record = {'schema_version': 1, 'run_id': 'fixture-run', 'phase': 'S2',
              'version': version, 'receipt_id': 'receipt-' + str(version),
              'previous_sha256': None, 'review_status': 'PENDING', 'artifacts': []}
    artifacts = {}
    for kind in ('receipt', 'source', 'test_log'):
        raw = ('fixture-' + kind + str(version)).encode()
        record['artifacts'].append({'id': kind, 'kind': kind, 'sha256': digest(raw)})
        artifacts[kind] = {k: record[k] for k in ('run_id', 'phase', 'version', 'receipt_id')}
        artifacts[kind]['bytes'] = raw
    return record, artifacts


def snapshot():
    services = {label: {'loaded': True, 'running': True, 'pid': 123,
                         'start': '2026-10-11T03:06:06Z', 'executable': '/fixture/python'} for label in CORE}
    return {'services': services, 'writer_fds': [456],
            'writer': {'pid': 456, 'start': '2026-10-11T03:06:06Z', 'executable': '/fixture/python',
                       'runtime_sha': 'a' * 40},
            'target_disabled': True, 'target_loaded': False, 'target_pid': None,
            'lowrisk_disabled': True, 'lowrisk_loaded': False, 'lowrisk_pid': None,
            'port_8010': 'REFUSED'}


class GovernanceTests(unittest.TestCase):
    def test_nonadjacent_receipt_reuse_rejected(self):
        first, a1 = evidence()
        raw1 = encode(first)
        prior1 = (raw1, digest(raw1), a1, None)
        second, a2 = evidence(2)
        second['previous_sha256'] = digest(raw1)
        raw2 = encode(second)
        prior2 = (raw2, digest(raw2), a2, prior1)
        third, a3 = evidence(3)
        third['previous_sha256'] = digest(raw2)
        valid = encode(third)
        validate_evidence(valid, digest(valid), a3, prior2)
        third['receipt_id'] = first['receipt_id']
        for artifact in a3.values():
            artifact['receipt_id'] = first['receipt_id']
        bad = encode(third)
        with self.assertRaises(ContractError):
            validate_evidence(bad, digest(bad), a3, prior2)

    def test_frozen_match_and_tamper(self):
        record, artifacts = evidence()
        raw = encode(record)
        self.assertEqual(validate_evidence(raw, digest(raw), artifacts), record)
        with self.assertRaises(ContractError):
            validate_evidence(raw + b' ', digest(raw), artifacts)

    def test_legacy_mismatch_and_missing_original_preserved(self):
        result = legacy_citation(b'current', digest(b'original')[:16])
        self.assertEqual(result['citation'], 'MISMATCH')
        self.assertEqual(result['original_bytes'], 'NOT_RECOVERED')
        self.assertEqual(result['formal_historical_acceptance'], 'BLOCKED')
        self.assertEqual(legacy_citation(b'current', digest(b'original')[:16], b'wrong')['original_bytes'],
                         'NOT_RECOVERED')

    def test_missing_predecessor_and_wrong_old_sha(self):
        first, a1 = evidence()
        second, a2 = evidence(2)
        raw1 = encode(first)
        second['previous_sha256'] = digest(raw1)
        raw2 = encode(second)
        with self.assertRaises(ContractError):
            validate_evidence(raw2, digest(raw2), a2)
        prior = (raw1, digest(raw1), a1, None)
        validate_evidence(raw2, digest(raw2), a2, prior)
        second['previous_sha256'] = '0' * 64
        wrong = encode(second)
        with self.assertRaises(ContractError):
            validate_evidence(wrong, digest(wrong), a2, prior)

    def test_cross_version_and_wrong_artifact_sha(self):
        record, artifacts = evidence()
        for key, value in [('version', 2), ('version', True), ('version', 1.0),
                           ('phase', 'S1'), ('receipt_id', 'wrong'), ('bytes', b'tamper')]:
            bad = copy.deepcopy(artifacts)
            bad['receipt'][key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_evidence(encode(record), digest(encode(record)), bad)

    def test_unknown_schema_duplicate_keys_and_empty_evidence(self):
        record, artifacts = evidence()
        for version in (True, 2):
            bad = dict(record, schema_version=version)
            with self.assertRaises(ContractError):
                validate_evidence(encode(bad), digest(encode(bad)), artifacts)
        raw = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaises(ContractError):
            validate_evidence(raw, digest(raw), {})
        bad = dict(record, artifacts=[])
        with self.assertRaises(ContractError):
            validate_evidence(encode(bad), digest(encode(bad)), {})

    def test_mutable_authorized_update_never_changes_frozen_bytes(self):
        record, artifacts = evidence()
        frozen = encode(record)
        old = {'run_id': 'fixture-run', 'revision': 1, 'task_index': 1, 'pointer': 'S1',
               'blocker': '', 'monitor_status': 'STOPPED'}
        new = dict(old, revision=2, task_index=2, pointer='S2')
        auth = {'actor': 'Codex', 'directive_sha256': 'a' * 64, 'run_id': 'fixture-run',
                'old_sha256': digest(encode(old)), 'new_sha256': digest(encode(new))}
        self.assertEqual(validate_state_update(old, new, auth, digest(encode(auth))), 'PASS')
        validate_evidence(frozen, digest(frozen), artifacts)
        for change in ({'task_index': 0}, {'pointer': 'S0', 'task_index': 1}, {'revision': True}):
            bad = dict(new, **change)
            a = dict(auth, new_sha256=digest(encode(bad)))
            with self.assertRaises(ContractError):
                validate_state_update(old, bad, a, digest(encode(a)))
        with self.assertRaises(ContractError):
            validate_state_update(old, new, auth, '0' * 64)
        a = dict(auth, actor='unknown')
        with self.assertRaises(ContractError):
            validate_state_update(old, new, a, digest(encode(a)))


class InventoryTests(unittest.TestCase):
    def test_content_and_writable_lock_rejected_before_io(self):
        reader = SafeInventoryReader(['/fixture/db', '/fixture/writer.lock'])
        with patch('builtins.open', side_effect=AssertionError('content IO attempted')):
            for path, mode in [('/fixture/db', 'rb'), ('/fixture/db-wal', 'rb'),
                               ('/fixture/db-shm', 'rb'), ('/fixture/writer.lock', 'r+')]:
                with self.subTest(path=path), self.assertRaises(PermissionError):
                    reader.open_content(path, mode)
            with self.assertRaises(PermissionError):
                reader.acquire_lock('/fixture/writer.lock')

    def test_metadata_never_proves_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fake.db'
            path.write_bytes(b'old')
            reader = SafeInventoryReader([path])
            before = reader.metadata(path)
            path.write_bytes(b'new-longer')
            after = reader.metadata(path)
            self.assertNotEqual(before['size'], after['size'])
            self.assertEqual(after['content_integrity'], 'NOT_VERIFIED')
            with self.assertRaises(ContractError):
                reader.metadata(path.parent)

    def test_seven_core_and_exact_auxiliary_pass(self):
        s = snapshot()
        aux = {'com.lowrisk.acceptance': {'loaded': True, 'running': False, 'pid': None,
               'launch_identity': {'executable': '/fixture/python', 'script_sha256': 'a' * 64,
                                   'plist_sha256': 'b' * 64}}}
        s['services'].update(copy.deepcopy(aux))
        self.assertEqual(inventory(s, aux)['SAFE_INVENTORY'], 'PASS')
        s['services']['com.lowrisk.acceptance']['pid'] = 777
        with self.assertRaises(ContractError):
            inventory(s, aux)

    def test_missing_or_changed_idle_launch_identity(self):
        aux = {'com.lowrisk.acceptance': {'loaded': True, 'running': False, 'pid': None,
               'launch_identity': {'executable': '/fixture/python', 'script_sha256': 'a' * 64,
                                   'plist_sha256': 'b' * 64}}}
        for key in ('executable', 'script_sha256', 'plist_sha256'):
            s = snapshot()
            s['services'].update(copy.deepcopy(aux))
            s['services']['com.lowrisk.acceptance']['launch_identity'][key] = 'changed'
            with self.subTest(key=key), self.assertRaises(ContractError):
                inventory(s, aux)
        missing = {'com.lowrisk.acceptance': {'loaded': True, 'running': False, 'pid': None}}
        s = snapshot()
        s['services'].update(missing)
        with self.assertRaises(ContractError):
            inventory(s, missing)

    def test_strict_writer_process_identity(self):
        for key, value in [('pid', True), ('start', True), ('start', 'not-a-dateZ'),
                           ('start', '2026-10-11T03:06:06'), ('executable', True),
                           ('runtime_sha', True)]:
            s = snapshot()
            s['writer'][key] = value
            if key == 'pid':
                s['writer_fds'] = [1]
            with self.subTest(key=key), self.assertRaises(ContractError):
                inventory(s, {})

    def test_missing_core_and_unknown_service_fail(self):
        s = snapshot()
        s['services'].pop(next(iter(CORE)))
        with self.assertRaises(ContractError):
            inventory(s, {})
        s = snapshot()
        s['services']['com.lowrisk.unknown'] = {'loaded': True, 'running': False, 'pid': None}
        with self.assertRaises(ContractError):
            inventory(s, {})

    def test_distinct_pid_not_fd_count(self):
        s = snapshot()
        s['writer_fds'] = [456, 456]
        self.assertEqual(inventory(s, {})['writer_process_count'], 1)
        s['writer_fds'].append(457)
        with self.assertRaises(ContractError):
            inventory(s, {})

    def test_missing_or_invalid_identity_and_containment(self):
        for key, value in [('target_disabled', False), ('target_loaded', True),
                           ('lowrisk_loaded', True), ('port_8010', '200'), ('writer_fds', []),
                           ('writer_fds', [True])]:
            s = snapshot()
            s[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                inventory(s, {})
        s = snapshot()
        s['services'][next(iter(CORE))]['start'] = ''
        with self.assertRaises(ContractError):
            inventory(s, {})

    def test_incomplete_contract_never_full_pass(self):
        statuses = {'SAFE_INVENTORY': 'PASS', 'FACTUAL_DATA_VERIFICATION': 'NOT_RUN',
                    'IMMUTABLE_LEDGER_VALIDATION': 'FAIL'}
        self.assertEqual(full_verdict(statuses), 'BLOCKED')
        for data in ('NOT_RUN', 'BLOCKED', 'FAIL'):
            statuses.update(FACTUAL_DATA_VERIFICATION=data, IMMUTABLE_LEDGER_VALIDATION='PASS')
            self.assertEqual(full_verdict(statuses), 'BLOCKED')
        with self.assertRaises(ContractError):
            full_verdict({})
        statuses['FACTUAL_DATA_VERIFICATION'] = 'PASS'
        self.assertEqual(full_verdict(statuses), 'PASS')  # fixture logic only


if __name__ == '__main__':
    unittest.main(verbosity=2)
