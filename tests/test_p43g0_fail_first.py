"""Deliberately RED baseline: do not mark xfail or implement a real source fix."""

from tests import test_p41_real_checkpoint_source as baseline
from tests.test_p41_real_checkpoint_source import actual as actual


def test_corrupt_load_contract_is_not_met(actual):
    baseline.test_required_corrupt_input_rejected(actual)


def test_full_object_cas_contract_is_not_met(actual):
    baseline.test_required_stale_state_rejected(actual)


def test_directory_open_durability_contract_is_not_met(actual):
    baseline.test_required_directory_open_failure_rejected(actual)
