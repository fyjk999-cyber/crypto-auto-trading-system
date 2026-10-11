"""Fake checkpoint laboratory. Creates its own temporary root, no production path input."""
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('duplicate key')
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=unique)


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class FixtureCAS:
    """Synthetic protocol, not a production checkpoint implementation or admission."""
    def __init__(self, initial):
        self.temp = tempfile.TemporaryDirectory(prefix='lowrisk-p4-fixture-')
        self.root = Path(self.temp.name)
        self.path = self.root / 'fake-checkpoint.json'
        self.path.write_bytes(encode(initial))
        self.lock = self.root / 'fake-owner.lock'

    def close(self):
        self.temp.cleanup()

    def update(self, expected, desired, *, crash=None, before_compare=None):
        proposed = encode(desired)
        with self.lock.open('a+b') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if before_compare:
                before_compare()
            raw = self.path.read_bytes()
            current = decode(raw)
            if raw == proposed:
                self._sync_dir()
                return 'RETRY_ALREADY_COMMITTED_FIXTURE'
            if digest(raw) != expected:
                raise ValueError('raw CAS conflict')
            # fixture_note is synthetic metadata, NOT an authorized production exclusion.
            protected = set(current) | set(desired)
            protected -= {'fixture_note', 'fixture_revision'}
            if any(k not in current or k not in desired
                   or encode(current[k]) != encode(desired[k])
                   for k in protected):
                raise ValueError('protected/unknown/origin/control changed')
            if (type(current.get('fixture_revision')) is not int
                    or type(desired.get('fixture_revision')) is not int):
                raise ValueError('revision missing/type')
            if desired['fixture_revision'] != current['fixture_revision'] + 1:
                raise ValueError('stale revision')
            staged = self.root / 'pending.fake'
            with staged.open('wb') as handle:
                handle.write(proposed)
                handle.flush()
                os.fsync(handle.fileno())
            if crash == 'before_rename':
                raise RuntimeError('simulated crash before rename')
            # Exact reread while exclusive fake owner lock is held; no rebase.
            if self.path.read_bytes() != raw:
                raise ValueError('drift after compare')
            os.replace(staged, self.path)
            if crash == 'after_rename':
                raise RuntimeError('simulated crash after rename')
            self._sync_dir()
            if self.path.read_bytes() != proposed:
                raise ValueError('postwrite mismatch')
            return 'COMMITTED_FIXTURE_ONLY'

    def _sync_dir(self):
        fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


T1_REQUIREMENTS = frozenset({'current_inventory', 'control_schema', 'raw_provenance',
    'captured_at', 'unique_writer', 'exclusive_window', 'consumer_safety', 'stop_restore_plan',
    'full_hashes', 'no_race', 'independent_custody', 'rollback', 'first_natural_cycle',
    'measured_budget', 'separate_human_admission'})


def preflight_plan(facts):
    missing = sorted(k for k in T1_REQUIREMENTS if facts.get(k) is not True)
    return {'missing': missing, 'plan_inputs': 'COMPLETE' if not missing else 'BLOCKED',
            'execution': 'NOT_AUTHORIZED_BY_OFFLINE_CANDIDATE', 'T0': 'NOT_PROVABLE',
            'G1R': 'NOT_FORMALLY_ACCEPTED'}


def custody_candidate(producer_uid, reviewer_uid, anchor_verified=False):
    # A caller boolean and unlike UIDs are not authenticated external custody proof.
    return {'identity_separation': producer_uid != reviewer_uid,
            'reported_anchor': anchor_verified, 'custody': 'NOT_ESTABLISHED',
            'formal_gate': 'BLOCKED', 'legacy_mismatch': 'RETAINED'}


def amendment_candidate(facts):
    required = {'original_blocked', 'no_waiver', 't0_not_provable', 'real_t1',
                'authenticated_custody', 'all_gates_accepted', 'separate_production_authority'}
    missing = sorted(k for k in required if facts.get(k) is not True)
    return {'missing': missing, 'review_inputs': 'BLOCKED' if missing else 'COMPLETE',
            'adoption': 'NOT_AUTHORIZED', 'G1R': 'NOT_FORMALLY_ACCEPTED'}
