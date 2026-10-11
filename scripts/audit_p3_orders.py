"""Read existing offline G2 evidence only; never issue provider requests."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/huhongjie/.codex/chatgpt-task-loop-state/lowrisk-final-landing-20261005165124")
NAMES = ("g2-provider-availability-result.json", "g2-r2-provider-availability-result.json",
         "g2-r3-provider-availability-result.json")
FIRST_SHA = "27b35213cb6bfa98c4b740bed3c93d55b301ad89163c0d803f25bdb1d7c7c592"
RECEIPT_SHA = "c67615950b50d4b90ca9e98b77acc6f15d49cbc1b1cfa1911ee1c1e346561fef"


def review(root=ROOT):
    registration_raw = (root / "g2-isolation/g2-sample-registration.json").read_bytes()
    if hashlib.sha256(registration_raw).hexdigest() != (
            "0a137d5bae695609bbb2f754fa95c56f97d195f53e963c01a2b23647253635fc"):
        raise ValueError("registration changed")
    registration = json.loads(registration_raw)
    registered = {r["sample_id"]: r["requested_open_grid"] for r in registration["samples"]}
    receipt = (root / "g2-provider-availability-receipt.md").read_bytes()
    if hashlib.sha256(receipt).hexdigest() != RECEIPT_SHA:
        raise ValueError("first receipt changed")
    reports, first_shape = [], None
    for number, name in enumerate(NAMES, 1):
        raw = (root / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if number == 1 and digest != FIRST_SHA:
            raise ValueError("first result changed")
        data = json.loads(raw)
        requests = data.get("requests")
        if requests is None:
            requests = next(c["requests"] for c in data["chapters"] if "requests" in c)
        shape = [(r["sample_id"], r["url"], r["requested_open_grid"]) for r in requests]
        if {r[0]: r[2] for r in shape} != registered:
            raise ValueError("preregistered grid mismatch")
        if len(shape) != 12 or len({r[0] for r in shape}) != 12:
            raise ValueError("request inventory")
        if first_shape is None:
            first_shape = shape
        elif first_shape != shape:
            raise ValueError("sample changed between attempts")
        assertion = data["request_assertions"]
        if assertion["retries"] != 0 or assertion["private_or_signed_urls"] != 0:
            raise ValueError("request boundary")
        reports.append({"attempt": number, "file": name, "sha256": digest,
                        "request_rows": len(requests),
                        "http": dict(Counter(str(r.get("http_status")) for r in requests)),
                        "errors": dict(Counter(str(r.get("error_class", r.get("error")))
                                              for r in requests)),
                        "confirmed_bars_recorded": sum(len(r["confirmed_open_grid"])
                                                       for r in requests)})
    return {"attempts": reports, "first_twelve_review": "PASS_BOUNDED_ZERO_DATA",
            "G2_OLD_BUDGET_COMPLIANCE": "FAIL", "provider_attempts_recorded": 36,
            "provider_reaching_recorded": 24, "new_provider_requests": 0,
            "availability_all_2519": "UNKNOWN", "G2_R_COVERAGE": "BLOCKED"}


if __name__ == "__main__":
    print(json.dumps(review(), indent=2))
