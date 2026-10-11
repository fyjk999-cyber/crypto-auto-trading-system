import fcntl
import importlib.util
from pathlib import Path

import pytest


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ROOT = Path(__file__).resolve().parents[1]
p4 = module(ROOT / 'evidence-v2/verification/p4_fixture.py', 'p4')
audit = module(ROOT / 'scripts/audit_checkpoint_source.py', 'p4audit')


@pytest.fixture
def lab():
    obj = p4.FixtureCAS({'fixture_revision': 1, 'fixture_note': 'old', 'completed': True,
        'status': 'IN_PROGRESS', 'forward_cursor': 4, 'next_cursor': 3, 'origin': 'FAKE',
        'pause_reason': 'stop requested', 'restored_reason': 'FAKE', 'unknown': {'x': 1}})
    yield obj
    obj.close()


def proposal(lab):
    old = lab.path.read_bytes()
    desired = p4.decode(old)
    desired.update(fixture_revision=2, fixture_note='new')
    return old, desired


def test_success_retry_preserves_full_controls(lab):
    old, desired = proposal(lab)
    assert lab.update(p4.digest(old), desired) == 'COMMITTED_FIXTURE_ONLY'
    assert p4.decode(lab.path.read_bytes()) == desired
    assert lab.update(p4.digest(old), desired) == 'RETRY_ALREADY_COMMITTED_FIXTURE'
    assert p4.decode(lab.path.read_bytes())['fixture_revision'] == 2


@pytest.mark.parametrize('field', ['completed', 'status', 'forward_cursor', 'next_cursor',
    'origin', 'pause_reason', 'restored_reason', 'unknown', 'new_key',
    'forward_bridge_start_ms', 'newest_fetched', 'restored_completed_at', 'lease_owner',
    'last_success_at', 'updated_at'])
def test_control_unknown_origin_changes_rejected(lab, field):
    old, desired = proposal(lab)
    desired[field] = 'CORRUPTED'
    with pytest.raises(ValueError):
        lab.update(p4.digest(old), desired)
    assert lab.path.read_bytes() == old


@pytest.mark.parametrize('field,value', [('completed', 1), ('next_cursor', 3.0),
                                      ('unknown', {'x': True}), ('unknown', {'x': 1.0})])
def test_json_type_drift_rejected(lab, field, value):
    old, desired = proposal(lab)
    desired[field] = value
    with pytest.raises(ValueError):
        lab.update(p4.digest(old), desired)
    assert lab.path.read_bytes() == old


def test_competing_owner_aborts(lab):
    old, desired = proposal(lab)
    with lab.lock.open('a+b') as second:
        fcntl.flock(second.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            lab.update(p4.digest(old), desired)
        assert lab.path.read_bytes() == old


def test_drift_aborts_without_overwriting_competitor(lab):
    old, desired = proposal(lab)
    changed = p4.encode({**p4.decode(old), 'forward_cursor': 5})
    with pytest.raises(ValueError):
        lab.update(p4.digest(old), desired, before_compare=lambda: lab.path.write_bytes(changed))
    assert lab.path.read_bytes() == changed


@pytest.mark.parametrize('point', ['before_rename', 'after_rename'])
def test_crash_retry_atomic_no_cursor_loss(lab, point):
    old, desired = proposal(lab)
    with pytest.raises(RuntimeError):
        lab.update(p4.digest(old), desired, crash=point)
    assert lab.path.read_bytes() == (old if point == 'before_rename' else p4.encode(desired))
    lab.update(p4.digest(old), desired)
    assert p4.decode(lab.path.read_bytes()) == desired


def test_stale_revision_and_duplicate_json_rejected(lab):
    old, desired = proposal(lab)
    desired['fixture_revision'] = 0
    with pytest.raises(ValueError):
        lab.update(p4.digest(old), desired)
    assert lab.path.read_bytes() == old
    with pytest.raises(ValueError):
        p4.decode(b'{"status":1,"status":2}')


def test_t1_missing_each_requirement_and_no_self_admission():
    full = {k: True for k in p4.T1_REQUIREMENTS}
    assert p4.preflight_plan(full)['execution'] == 'NOT_AUTHORIZED_BY_OFFLINE_CANDIDATE'
    for key in full:
        assert p4.preflight_plan({**full, key: False})['plan_inputs'] == 'BLOCKED'
    assert p4.preflight_plan({'old_manifest_493': True})['plan_inputs'] == 'BLOCKED'


def test_no_same_uid_or_self_report_anchor_custody_pass():
    for uids in [(501, 501), (501, 502)]:
        assert p4.custody_candidate(*uids, anchor_verified=True)['custody'] == 'NOT_ESTABLISHED'


def test_ast_literal_catalog_not_semantic_proof():
    rows, calls = audit.inspect_text('def f(cp):\n cp["status"] = "IN_PROGRESS"\n cb(cp)\n')
    assert rows[0]['field'] == 'status'
    assert rows[0]['classification'].startswith('LITERAL_REFERENCE')
    assert calls[0]['dispatch'] == 'UNRESOLVED_STATIC_CANDIDATE'


def test_directory_sync_failure_is_not_success(lab, monkeypatch):
    old, desired = proposal(lab)
    def fail():
        raise OSError('fixture directory fsync unavailable')
    monkeypatch.setattr(lab, '_sync_dir', fail)
    with pytest.raises(OSError):
        lab.update(p4.digest(old), desired)
    assert lab.path.read_bytes() == p4.encode(desired)
    with pytest.raises(OSError):
        lab.update(p4.digest(old), desired)


def test_amendment_cannot_skip_gates_or_self_adopt():
    keys = {'original_blocked', 'no_waiver', 't0_not_provable', 'real_t1',
            'authenticated_custody', 'all_gates_accepted', 'separate_production_authority'}
    full = dict.fromkeys(keys, True)
    for key in keys:
        assert p4.amendment_candidate({**full, key: False})['review_inputs'] == 'BLOCKED'
    assert p4.amendment_candidate(full)['adoption'] == 'NOT_AUTHORIZED'
