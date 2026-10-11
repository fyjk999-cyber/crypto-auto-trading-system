"""Offline candidates only: no DB connector, service runner or trading capability."""
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, why):
    if not ok:
        raise ValueError(why)


def forward_manifest(version, parent, source_sha, artifacts, observed_at):
    require(type(version) is int and version > 0, "version")
    require(bool(re.fullmatch("[a-f0-9]{40}", source_sha)), "source SHA")
    require(observed_at.endswith("Z"), "UTC observation")
    datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    require(bool(artifacts) and all(type(v) is bytes for v in artifacts.values()), "artifacts")
    require(all(re.fullmatch("[a-zA-Z0-9_.-]+", k) for k in artifacts), "artifact names")
    require((version == 1 and parent is None) or
            (version > 1 and type(parent) is str and re.fullmatch("[a-f0-9]{64}", parent)),
            "parent")
    return {"schema_version": 1, "version": version, "parent_sha256": parent,
            "source_sha": source_sha, "observed_at": observed_at,
            "scope": "FORWARD_ONLY_NOT_T0", "legacy": "FAIL_MISMATCH",
            "artifacts": {name: sha(data) for name, data in artifacts.items()}}


def verify_forward(manifest, artifacts, pinned_sha, parent=None):
    require(sha(encode(manifest)) == pinned_sha, "manifest changed")
    rebuilt = forward_manifest(manifest["version"], manifest["parent_sha256"],
                               manifest["source_sha"], artifacts, manifest["observed_at"])
    require(encode(rebuilt) == encode(manifest), "manifest/schema/artifact mismatch")
    if manifest["version"] > 1:
        require(type(parent) is tuple and len(parent) == 4, "complete parent evidence required")
        prior, prior_artifacts, prior_pin, earlier = parent
        verify_forward(prior, prior_artifacts, prior_pin, earlier)
        require(prior_pin == manifest["parent_sha256"], "parent mismatch")
        require(prior["version"] + 1 == manifest["version"], "version conflict")
    else:
        require(parent is None, "unexpected parent")
    return {"FORWARD_EVIDENCE_CHAIN": "PASS_LOCAL_CONTENT_ONLY",
            "LEGACY_EVIDENCE": "FAIL_MISMATCH", "INDEPENDENT_CUSTODY": "NOT_ESTABLISHED",
            "FORMAL_EVIDENCE_GATE": "BLOCKED"}


DATA_READ_REQUIREMENTS = frozenset({
    "owner", "source_sha", "snapshot_sha256", "wal_consistency", "provenance",
    "freshness", "units", "timestamps", "max_bytes", "max_memory_bytes",
    "max_seconds", "read_only_permissions", "sidecar_policy", "writer_noninterference",
    "failure_recovery", "human_admission",
})


def data_read_contract(contract):
    require(set(contract) == DATA_READ_REQUIREMENTS, "incomplete data-read contract")
    require(all(v is not None and v != "" for v in contract.values()), "unknown contract fact")
    for key in ("max_bytes", "max_memory_bytes", "max_seconds"):
        require(type(contract[key]) is int and contract[key] > 0, "unbounded budget")
    # No caller-supplied approval string upgrades this candidate to production authority.
    return "BLOCKED_UNTIL_PRODUCTION_ADMISSION"


def check_fixture_bytes(data, expected_sha, max_bytes):
    """Budget/hash predicate on supplied fake bytes; no production file-open capability."""
    require(type(max_bytes) is int and max_bytes > 0, "budget")
    require(type(data) is bytes and len(data) <= max_bytes, "fixture too large")
    require(sha(data) == expected_sha, "fixture integrity")
    return {"fixture_integrity": "PASS", "production_admission": "BLOCKED"}


COMPARISON_FIELDS = (
    "strategy_package_hash", "factor_schema_version", "factor_snapshot_hash", "market_asof_utc",
    "decision_id", "llm_decision", "risk_decision", "paper_order_id", "fill_id", "episode_id",
    "gross_pnl", "net_pnl", "fees", "funding", "equity", "drawdown", "experiment_id",
)
MONEY = frozenset({"gross_pnl", "net_pnl", "fees", "funding", "equity", "drawdown"})


def comparison_record(facts, *, enabled=False):
    """Explicit offline serialization only; no database, endpoint or runtime hook."""
    if enabled is not True:
        raise PermissionError("comparison export disabled by default")
    require(set(facts) <= set(COMPARISON_FIELDS), "unknown/write-capability field")
    result = {}
    for field in COMPARISON_FIELDS:
        item = facts.get(field)
        if item is None:
            result[field] = {"status": "NOT_AVAILABLE", "value": None, "source": None}
            continue
        require(type(item) is dict and set(item) == {"value", "source"}, "fact schema")
        value, source = item["value"], item["source"]
        require(type(source) is str and bool(source.strip()), "unbound fact")
        require(value is not None and value != "" and type(value) is not bool, "missing fact")
        if field in MONEY:
            require(type(value) is str and Decimal(value).is_finite(), "decimal monetary string")
        elif field.endswith("_hash"):
            require(type(value) is str and re.fullmatch("[a-f0-9]{64}", value), "hash")
        elif field == "market_asof_utc":
            require(type(value) is str and value.endswith("Z"), "UTC as-of")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            require(type(value) is str and bool(value.strip()), "fact text/ID")
        result[field] = {"status": "CALLER_SUPPLIED_NOT_RUNTIME_VERIFIED",
                         "value": value, "source": source}
    if all(key in facts for key in ("gross_pnl", "fees", "funding", "net_pnl")):
        require(Decimal(facts["net_pnl"]["value"]) == Decimal(facts["gross_pnl"]["value"])
                - Decimal(facts["fees"]["value"]) + Decimal(facts["funding"]["value"]),
                "net accounting mismatch")
    return {"schema_version": 1, "mode": "OFFLINE_READ_ONLY_CANDIDATE",
            "trading_authority": "NONE", "order_authority": "NONE",
            "quant_core_connected": False, "facts": result}
