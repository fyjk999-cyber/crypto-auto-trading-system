"""Validate deliberate RED evidence, not convert unsafe implementations to PASS."""

import xml.etree.ElementTree as ET
from pathlib import Path

from tests.test_p41_real_checkpoint_source import VERSIONS


def test_fail_first_baseline_has_six_real_failures_without_xfail_or_errors():
    root = Path(__file__).resolve().parents[1] / "docs"
    cases = ET.parse(root / "P43G0_FAIL_FIRST_RESULTS.xml").getroot().findall(".//testcase")
    expected = {
        f"{name}[{sha}]" for sha in VERSIONS for name in (
            "test_corrupt_load_contract_is_not_met",
            "test_full_object_cas_contract_is_not_met",
            "test_directory_open_durability_contract_is_not_met",
        )
    }
    assert {c.get("name") for c in cases} == expected
    assert len(cases) == 6
    assert all(c.find("failure") is not None for c in cases)
    assert all(c.find("error") is None and c.find("skipped") is None for c in cases)
    assert all("DID NOT RAISE" in c.find("failure").get("message", "") for c in cases)


def test_route_reproduction_log_is_not_a_safety_fix():
    root = Path(__file__).resolve().parents[1] / "docs"
    cases = ET.parse(root / "P43G0_ROUTE_BASELINE_RESULTS_R2.xml").getroot().findall(".//testcase")
    assert len(cases) == 16
    assert all(c.find("failure") is None and c.find("error") is None for c in cases)
    assert all(c.find("skipped") is None for c in cases)
