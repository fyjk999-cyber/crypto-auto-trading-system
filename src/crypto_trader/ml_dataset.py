# ruff: noqa: ASYNC240
# ML data quality, readiness and immutable freeze (LEARNING_ONLY).
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import distinct, func, select

from crypto_trader.persistence.models import ScanSnapshotLabelORM, ScanSnapshotORM

MIN_SNAPSHOTS = 200
MIN_CANDIDATES = 50
MIN_CONTROLS = 50
MIN_SYMBOLS = 10
MIN_LABELED = 50
FINAL_LABEL_VERSION = "label-v2"
LABEL_V1_EXCLUDED_REASON = "label_v1_excluded_from_final_training"


@dataclass(frozen=True)
class DataQuality:
    total: int
    candidates: int
    controls: int
    symbols: int
    first_ts: str | None
    last_ts: str | None
    duplicate_rate: float
    null_rates: dict = field(default_factory=dict)
    label_counts: dict = field(default_factory=dict)
    label_counts_by_version: dict = field(default_factory=dict)
    final_label_count: int = 0

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "candidates": self.candidates,
            "controls": self.controls,
            "symbols": self.symbols,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "duplicate_rate": self.duplicate_rate,
            "null_rates": self.null_rates,
            "label_counts": self.label_counts,
            "label_counts_by_version": self.label_counts_by_version,
            "final_label_count": self.final_label_count,
        }


async def evaluate_data_quality(session_factory) -> DataQuality:
    async with session_factory() as s:
        total = int(await s.scalar(select(func.count()).select_from(ScanSnapshotORM)) or 0)
        cand = int(
            await s.scalar(select(func.count()).where(ScanSnapshotORM.candidate.is_(True))) or 0
        )
        ctrl = int(
            await s.scalar(select(func.count()).where(ScanSnapshotORM.control.is_(True))) or 0
        )
        symbols = int(await s.scalar(select(func.count(distinct(ScanSnapshotORM.symbol)))) or 0)
        sel = select(
            ScanSnapshotORM.snapshot_id, ScanSnapshotORM.captured_at, ScanSnapshotORM.features_json
        ).order_by(ScanSnapshotORM.captured_at)
        rows = (await s.execute(sel)).all()
        lab = (
            await s.execute(
                select(ScanSnapshotLabelORM.horizon, func.count()).group_by(
                    ScanSnapshotLabelORM.horizon
                )
            )
        ).all()
        lab_v = (
            await s.execute(
                select(ScanSnapshotLabelORM.label_version, func.count()).group_by(
                    ScanSnapshotLabelORM.label_version
                )
            )
        ).all()
    ids = [r[0] for r in rows]
    first = rows[0][1].isoformat() if rows and rows[0][1] else None
    last = rows[-1][1].isoformat() if rows and rows[-1][1] else None
    keys = sorted({k for r in rows for k in (r[2] or {})})
    null_rates = {}
    for k in keys:
        missing = sum(1 for r in rows if (r[2] or {}).get(k) is None)
        null_rates[k] = round(missing / max(1, len(rows)), 4)
    dup = round(1 - (len(set(ids)) / max(1, len(ids))), 6) if ids else 0.0
    return DataQuality(
        total=total,
        candidates=cand,
        controls=ctrl,
        symbols=symbols,
        first_ts=first,
        last_ts=last,
        duplicate_rate=dup,
        null_rates=null_rates,
        label_counts={h: int(c) for h, c in lab},
        label_counts_by_version={str(v): int(c) for v, c in lab_v},
        final_label_count=sum(int(c) for v, c in lab_v if str(v) == FINAL_LABEL_VERSION),
    )


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reasons: list[str]
    quality: dict


MIN_COVERAGE_DAYS = 3
MAX_DUPLICATE_RATE = 0.05
REQUIRED_FEATURES = ("l1_imbalance", "l5_imbalance", "microprice", "cvd")
MAX_FEATURE_NULL_RATE = 0.5


async def evaluate_readiness(session_factory) -> Readiness:
    q = await evaluate_data_quality(session_factory)
    reasons: list[str] = []
    if q.total < MIN_SNAPSHOTS:
        reasons.append(f"insufficient_snapshots:{q.total}<{MIN_SNAPSHOTS}")
    if q.candidates < MIN_CANDIDATES:
        reasons.append(f"insufficient_candidates:{q.candidates}<{MIN_CANDIDATES}")
    if q.controls < MIN_CONTROLS:
        reasons.append(f"insufficient_controls:{q.controls}<{MIN_CONTROLS}")
    if q.symbols < MIN_SYMBOLS:
        reasons.append(f"insufficient_symbols:{q.symbols}<{MIN_SYMBOLS}")
    if q.final_label_count <= 0:
        reasons.append("no_label_v2")
    if q.final_label_count < MIN_LABELED:
        reasons.append(f"insufficient_label_v2:{q.final_label_count}<{MIN_LABELED}")
    if sum(v for k, v in q.label_counts_by_version.items() if k != FINAL_LABEL_VERSION) > 0:
        # label-v1 is archival only; it may never satisfy final training readiness.
        reasons.append(LABEL_V1_EXCLUDED_REASON)
    if q.duplicate_rate > MAX_DUPLICATE_RATE:
        reasons.append(f"duplicate_rate:{q.duplicate_rate}>{MAX_DUPLICATE_RATE}")
    for name in REQUIRED_FEATURES:
        rate = q.null_rates.get(name, 1.0)
        if rate > MAX_FEATURE_NULL_RATE:
            reasons.append(f"feature_incomplete:{name}:{rate}>{MAX_FEATURE_NULL_RATE}")
    if not q.first_ts or not q.last_ts:
        reasons.append("no_timestamp_coverage")
    else:
        span = (datetime.fromisoformat(q.last_ts) - datetime.fromisoformat(q.first_ts)).days
        if span < MIN_COVERAGE_DAYS:
            reasons.append(f"insufficient_time_coverage:{span}<{MIN_COVERAGE_DAYS}")
    return Readiness(ready=not reasons, reasons=reasons, quality=q.as_dict())


async def freeze_dataset(session_factory, output_dir, code_sha="") -> dict:
    q = await evaluate_data_quality(session_factory)
    async with session_factory() as s:
        snaps = (
            (
                await s.execute(
                    select(ScanSnapshotORM).order_by(
                        ScanSnapshotORM.captured_at, ScanSnapshotORM.snapshot_id
                    )
                )
            )
            .scalars()
            .all()
        )
        labs = (
            (
                await s.execute(
                    select(ScanSnapshotLabelORM)
                    .where(ScanSnapshotLabelORM.label_version == FINAL_LABEL_VERSION)
                    .order_by(ScanSnapshotLabelORM.snapshot_id, ScanSnapshotLabelORM.horizon)
                )
            )
            .scalars()
            .all()
        )
    if not labs:
        return {
            "ready": False,
            "reason": "NO_LABEL_V2",
            "label_version": FINAL_LABEL_VERSION,
            "label_v1_excluded": q.label_counts_by_version.get("label-v1", 0),
            "message": "label-v1 is archival only and cannot freeze a final scientific dataset",
        }
    payload = {
        "created_at": q.last_ts or "",
        "code_sha": code_sha,
        "feature_version": "scan-features-v1",
        "label_version": FINAL_LABEL_VERSION,
        "sample_start_ts": q.first_ts,
        "sample_end_ts": q.last_ts,
        "candidate_count": q.candidates,
        "control_count": q.controls,
        "symbol_count": q.symbols,
        "snapshot_count": q.total,
        "label_counts": q.label_counts,
        "snapshots": [
            {
                "snapshot_id": x.snapshot_id,
                "symbol": x.symbol,
                "captured_at": x.captured_at.isoformat(),
                "candidate": x.candidate,
                "control": x.control,
                "features": x.features_json,
            }
            for x in snaps
        ],
        "labels": [
            {
                "snapshot_id": lb.snapshot_id,
                "horizon": lb.horizon,
                "long_net_bps": lb.long_net_bps,
                "short_net_bps": lb.short_net_bps,
                "long_label": lb.long_label,
                "short_label": lb.short_label,
                "label_version": lb.label_version,
            }
            for lb in labs
        ],
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    digest = hashlib.sha256(blob).hexdigest()
    version = f"ds-{digest[:16]}"
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{version}.json"
    if not path.exists():
        path.write_bytes(blob)
    return {
        "dataset_version": version,
        "dataset_hash": digest,
        "path": str(path),
        "sample_start_ts": q.first_ts,
        "sample_end_ts": q.last_ts,
        "candidate_count": q.candidates,
        "control_count": q.controls,
        "symbol_count": q.symbols,
        "snapshot_count": q.total,
        "label_counts": q.label_counts,
        "immutable": path.exists(),
    }
