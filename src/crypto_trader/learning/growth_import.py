"""G05: read-only legacy inventory and isolated, rollback-safe import.

Safety contract
---------------
* ``LegacyImporter.inventory`` / ``build_plan`` only read the source through a
  read-only SQLite URI and the SQLite backup API; they never write the source.
* ``import_plan`` requires ``test_only=True`` and a target path that resolves
  under an ephemeral temp directory.  Known production worktree paths are
  refused, so this module cannot migrate a production database.
* Legacy episodes/memory are **not** upgraded to canonical factual truth.
  Without ledger/fill proof they become ``LEGACY_OBSERVATION`` or
  ``QUARANTINED`` and remain explicitly research-only.
* Exact dedup uses ``namespace = hash(source_db_sha256|table|source_id)``.
  Near duplicates (same symbol/time/PnL magnitude) are only marked
  ``DUPLICATE_SUSPECT``; they are never merged by similarity.
* Each batch has its own id/hash/plan and per-item disposition.  Rollback
  deletes only that batch's imported rows, never the source database and never
  pre-existing canonical data.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, select, text

from crypto_trader.learning.growth_contracts import canonical_json, sha256_text
from crypto_trader.learning.growth_models import (
    GrowthImportBatchORM,
    GrowthImportItemORM,
    GrowthLegacyObservationORM,
    utcnow,
)

LEGACY_OBSERVATION = "LEGACY_OBSERVATION"
QUARANTINED = "QUARANTINED"
DUPLICATE_STRONG = "DUPLICATE_STRONG"
DUPLICATE_SUSPECT = "DUPLICATE_SUSPECT"
CONTENT_CONFLICT = "CONTENT_CONFLICT"
IMPORTED = "IMPORTED"

BATCH_PLANNED = "PLANNED"
BATCH_IMPORTING = "IMPORTING"
BATCH_COMPLETED = "COMPLETED"
BATCH_FAILED = "FAILED"
BATCH_ROLLED_BACK = "ROLLED_BACK"

PRODUCTION_MARKERS = (
    "/crypto-auto-trading-system-fullmarket/",
    "/crypto-auto-trading-system-local-current/",
    "/crypto-auto-trading-system-canonical-clean/",
    "/crypto-auto-trading-system-p0p1/",
    "/crypto-auto-trading-system-canonical/",
    "/crypto-auto-trading-system-paper-local/",
)


class ImportSafetyError(RuntimeError):
    pass


class InjectedImportFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportItem:
    namespace: str
    source_table: str
    source_id: str
    content_hash: str
    disposition: str
    reason: str | None
    account_id: str
    mode: str
    symbol: str | None
    direction: str | None
    economic_closed_at: datetime | None
    proof_kind: str
    near_duplicate_fingerprint: str | None
    source_json: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "source_table": self.source_table,
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "disposition": self.disposition,
            "reason": self.reason,
            "account_id": self.account_id,
            "mode": self.mode,
            "symbol": self.symbol,
            "direction": self.direction,
            "economic_closed_at": (
                self.economic_closed_at.isoformat() if self.economic_closed_at else None
            ),
            "proof_kind": self.proof_kind,
            "near_duplicate_fingerprint": self.near_duplicate_fingerprint,
            "source_json": self.source_json,
        }


@dataclass
class ImportPlan:
    source_path: str
    source_sha256: str
    plan_hash: str
    items: list[ImportItem]
    inventory: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dispositions(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.items:
            out[item.disposition] = out.get(item.disposition, 0) + 1
        return out


@dataclass
class ImportReport:
    batch_id: str
    status: str
    imported: int = 0
    quarantined: int = 0
    duplicates: int = 0
    conflicts: int = 0
    resumed: bool = False
    idempotent: bool = False


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_snapshot(path: str) -> tuple[sqlite3.Connection, tempfile.TemporaryDirectory]:
    holder = tempfile.TemporaryDirectory(prefix="growth-import-snapshot-")
    destination = os.path.join(holder.name, "source.db")
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    source.execute("PRAGMA query_only=ON")
    target = sqlite3.connect(destination)
    source.backup(target)
    target.close()
    source.close()
    return sqlite3.connect(destination), holder


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"pragma table_info({table})")}


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "select 1 from sqlite_master where type='table' and name=?", (table,)
        ).fetchone()
        is not None
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _bounded(value: Any, limit: int = 200) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit]


def near_duplicate_fingerprint(
    *, symbol: str | None, direction: str | None, pnl: Decimal | None, closed_at: datetime | None
) -> str | None:
    """Similarity fingerprint only; never used as an automatic merge key."""
    if not symbol or pnl is None:
        return None
    day = closed_at.date().isoformat() if closed_at else "NO_DATE"
    raw = f"{symbol}|{direction or 'UNKNOWN'}|{format(pnl, 'f')[:12]}|{day}"
    return sha256_text(raw)


class LegacyImporter:
    def __init__(
        self,
        session_factory,
        *,
        target_path: str | None = None,
        test_only: bool = False,
    ) -> None:
        self.session_factory = session_factory
        self.target_path = target_path
        self.test_only = test_only
        if target_path is not None:
            # Path-shape guard only; the real connection identity is verified
            # at authorization/mutation time so nothing is written before then.
            self._assert_test_target(target_path)

    def _actual_sqlite_path(self) -> str:
        """Resolve the database actually bound to this session factory."""
        engine = None
        kw = getattr(self.session_factory, "kw", None) or {}
        engine = kw.get("bind") or getattr(self.session_factory, "bind", None)
        if engine is None:
            raise ImportSafetyError("cannot determine actual session-factory bind")
        url = getattr(engine, "url", None)
        if url is None or url.get_backend_name() != "sqlite":
            raise ImportSafetyError("legacy importer only supports a real SQLite file target")
        database = url.database
        if not database or database in {":memory:", ""}:
            raise ImportSafetyError("legacy importer target must be a real SQLite file")
        absolute = os.path.realpath(os.path.abspath(database))
        if not os.path.exists(absolute):
            raise ImportSafetyError(f"bound SQLite target does not exist: {absolute}")
        return absolute

    def _assert_actual_target(self) -> None:
        """Fail closed unless the real connection matches the approved target."""
        if self.target_path is None:
            raise ImportSafetyError("legacy importer requires an explicit target path")
        actual = self._actual_sqlite_path()
        expected = os.path.realpath(os.path.abspath(self.target_path))
        if actual != expected:
            raise ImportSafetyError(
                "legacy importer target_path does not match the actual DB connection"
            )
        self._assert_test_target(actual)
        # Strong identity where the filesystem exposes it.
        try:
            actual_stat = os.stat(actual)
            expected_stat = os.stat(expected)
        except OSError as exc:
            raise ImportSafetyError(f"cannot stat import target: {exc}") from exc
        if (actual_stat.st_dev, actual_stat.st_ino) != (
            expected_stat.st_dev,
            expected_stat.st_ino,
        ):
            raise ImportSafetyError("legacy importer target inode/device mismatch")
        kw = getattr(self.session_factory, "kw", None) or {}
        binds = kw.get("binds") or {}
        for engine in binds.values():
            url = getattr(engine, "url", None)
            if url is None or url.get_backend_name() != "sqlite":
                raise ImportSafetyError(
                    "legacy importer refuses non-SQLite mapper bind"
                )
            bound = os.path.realpath(os.path.abspath(url.database or ""))
            if bound != expected:
                raise ImportSafetyError(
                    "legacy importer has an alternate mapper bind; refusing mutation"
                )

    @staticmethod
    def _normalize_path(path: str) -> str:
        return os.path.realpath(os.path.abspath(path or ""))

    def _expected_target_path(self) -> str:
        return self._normalize_path(self.target_path or "")

    @staticmethod
    def _verify_bound_engine(engine, expected: str) -> None:
        url = getattr(engine, "url", None)
        if url is None or url.get_backend_name() != "sqlite":
            raise ImportSafetyError("legacy importer requires checked SQLite binds")
        bound = os.path.realpath(os.path.abspath(url.database or ""))
        if bound != expected:
            raise ImportSafetyError(
                "legacy importer mapper bind does not match target_path"
            )
        stat = os.stat(bound)
        expected_stat = os.stat(expected)
        if (stat.st_dev, stat.st_ino) != (
            expected_stat.st_dev,
            expected_stat.st_ino,
        ):
            raise ImportSafetyError(
                "legacy importer mapper bind inode/device mismatch"
            )

    async def _assert_actual_binds(self) -> None:
        """Resolve and verify the ACTUAL connection used by every import model.

        Engine URL equality is insufficient: a custom ``async_creator`` can
        open a different SQLite file while the labelled URL matches.  Each
        mapper route is therefore exercised with ``PRAGMA database_list`` on the
        same session that performs the mutation.
        """
        expected = self._expected_target_path()
        models = (
            GrowthImportBatchORM,
            GrowthImportItemORM,
            GrowthLegacyObservationORM,
        )
        async with self.session_factory() as session:
            for model in models:
                bind = session.get_bind(mapper=model.__mapper__)
                if bind is None:
                    raise ImportSafetyError(
                        f"cannot resolve actual bind for {model.__tablename__}"
                    )
                engine = getattr(bind, "engine", bind)
                self._verify_bound_engine(engine, expected)
                rows = (
                    await session.execute(
                        text("PRAGMA database_list"),
                        bind_arguments={"mapper": model.__mapper__},
                    )
                ).all()
                main_paths = [
                    str(row[2])
                    for row in rows
                    if len(row) > 2 and row[1] == "main"
                ]
                if not main_paths or not main_paths[0]:
                    raise ImportSafetyError(
                        "cannot resolve actual opened SQLite database"
                    )
                opened = self._normalize_path(main_paths[0])
                if opened != expected:
                    raise ImportSafetyError(
                        "legacy importer opened SQLite database does not match "
                        "target_path"
                    )
                opened_stat = os.stat(opened)
                expected_stat = os.stat(expected)
                if (opened_stat.st_dev, opened_stat.st_ino) != (
                    expected_stat.st_dev,
                    expected_stat.st_ino,
                ):
                    raise ImportSafetyError(
                        "legacy importer opened database inode/device mismatch"
                    )

    @staticmethod
    def _assert_test_target(path: str) -> None:
        absolute = os.path.realpath(os.path.abspath(path))
        temp_root = os.path.realpath(os.environ.get("TMPDIR", "/tmp"))
        allowed = {
            temp_root,
            os.path.realpath("/tmp"),
            os.path.realpath("/private/tmp"),
            os.path.realpath("/var/folders"),
            os.path.realpath("/private/var/folders"),
        }
        if not any(
            absolute == root or absolute.startswith(root + os.sep)
            for root in allowed
        ):
            raise ImportSafetyError(
                f"import target must be an ephemeral test database, got {absolute}"
            )
        if any(marker in absolute for marker in PRODUCTION_MARKERS):
            raise ImportSafetyError(f"refusing known production path: {absolute}")

    def require_import_authorization(self) -> None:
        if not self.test_only:
            raise ImportSafetyError(
                "import_plan requires explicit test_only=True; production import is not authorized"
            )
        if self.target_path is None:
            raise ImportSafetyError("import_plan requires an explicit test target path")
        self._assert_actual_target()

    # ------------------------------------------------------------------
    def inventory(self, source_path: str) -> list[dict[str, Any]]:
        connection, holder = _source_snapshot(source_path)
        try:
            out = []
            for table in sorted(
                row[0]
                for row in connection.execute(
                    "select name from sqlite_master where type='table' "
                    "and (name like '%episode%' or name like '%memory%' "
                    "or name like '%lesson%') order by name"
                )
            ):
                columns = _table_columns(connection, table)
                identity = (
                    "episode_id"
                    if "episode_id" in columns
                    else "decision_id"
                    if "decision_id" in columns
                    else "id"
                    if "id" in columns
                    else None
                )
                out.append(
                    {
                        "table": table,
                        "count": connection.execute(
                            f"select count(*) from {table}"
                        ).fetchone()[0],
                        "identity_column": identity,
                        "columns": sorted(columns),
                        "has_ledger_proof": bool(
                            {"fill_id", "order_id", "ledger_transaction_id"} & columns
                        ),
                    }
                )
            return out
        finally:
            connection.close()
            holder.cleanup()

    # ------------------------------------------------------------------
    def build_plan(
        self,
        source_path: str,
        *,
        account_id: str = "default",
        mode: str = "PAPER",
        source_sha_override: str | None = None,
        max_items: int = 10_000,
    ) -> ImportPlan:
        source_sha = source_sha_override or _sha256_file(source_path)
        connection, holder = _source_snapshot(source_path)
        items: list[ImportItem] = []
        try:
            items.extend(
                self._episode_items(
                    connection, source_sha, account_id=account_id, mode=mode
                )
            )
            items.extend(
                self._memory_items(
                    connection, source_sha, account_id=account_id, mode=mode
                )
            )
            items.extend(
                self._lesson_items(
                    connection, source_sha, account_id=account_id, mode=mode
                )
            )
            inventory = [
                {
                    "table": item_source_table,
                    "count": sum(1 for item in items if item.source_table == item_source_table),
                }
                for item_source_table in sorted({item.source_table for item in items})
            ]
        finally:
            connection.close()
            holder.cleanup()
        items = items[:max_items]
        plan_hash = sha256_text(
            canonical_json(
                [
                    {
                        "namespace": item.namespace,
                        "content_hash": item.content_hash,
                        "disposition": item.disposition,
                    }
                    for item in items
                ]
            )
        )
        return ImportPlan(
            source_path=os.path.abspath(source_path),
            source_sha256=source_sha,
            plan_hash=plan_hash,
            items=items,
            inventory=inventory,
        )

    def _episode_items(
        self, connection, source_sha: str, *, account_id: str, mode: str
    ) -> list[ImportItem]:
        if not _table_exists(connection, "ai_trade_episodes"):
            return []
        columns = _table_columns(connection, "ai_trade_episodes")
        selectable = [
            column
            for column in (
                "episode_id",
                "symbol",
                "market_regime",
                "entry_price",
                "exit_price",
                "pnl",
                "result",
                "created_at",
            )
            if column in columns
        ]
        rows = connection.execute(
            f"select {', '.join(selectable)} from ai_trade_episodes order by rowid"
        ).fetchall()
        items: list[ImportItem] = []
        for row in rows:
            data = dict(zip(selectable, row, strict=True))
            source_id = str(data.get("episode_id") or "")
            if not source_id:
                continue
            namespace = self._namespace(
                source_sha, "ai_trade_episodes", source_id, account_id, mode
            )
            payload = {
                key: _bounded(data.get(key))
                for key in ("symbol", "market_regime", "result", "entry_price", "exit_price", "pnl")
            }
            pnl = _decimal_or_none(data.get("pnl"))
            closed_at = _parse_datetime(data.get("created_at"))
            items.append(
                ImportItem(
                    namespace=namespace,
                    source_table="ai_trade_episodes",
                    source_id=source_id,
                    content_hash=sha256_text(canonical_json(payload)),
                    # No fill/ledger linkage in the legacy table: never upgraded
                    # to canonical factual truth.
                    disposition=LEGACY_OBSERVATION,
                    reason="LEGACY_AI_EPISODE_NO_LEDGER_PROOF",
                    account_id=account_id,
                    mode=mode,
                    symbol=_bounded(data.get("symbol"), 32),
                    direction=_direction_from_result(data.get("result")),
                    economic_closed_at=closed_at,
                    proof_kind="LEGACY_AI_EPISODE",
                    near_duplicate_fingerprint=near_duplicate_fingerprint(
                        symbol=_bounded(data.get("symbol"), 32),
                        direction=_direction_from_result(data.get("result")),
                        pnl=pnl,
                        closed_at=closed_at,
                    ),
                    source_json={k: v for k, v in payload.items() if v is not None},
                )
            )
        return items

    def _memory_items(
        self, connection, source_sha: str, *, account_id: str, mode: str
    ) -> list[ImportItem]:
        if not _table_exists(connection, "trade_memory_records"):
            return []
        columns = _table_columns(connection, "trade_memory_records")
        selectable = [
            column
            for column in (
                "decision_id",
                "symbol",
                "side",
                "regime",
                "realized_pnl",
                "fees",
                "funding_pnl",
                "timestamp",
            )
            if column in columns
        ]
        rows = connection.execute(
            f"select {', '.join(selectable)} from trade_memory_records order by rowid"
        ).fetchall()
        items: list[ImportItem] = []
        for row in rows:
            data = dict(zip(selectable, row, strict=True))
            source_id = str(data.get("decision_id") or "")
            if not source_id:
                continue
            namespace = self._namespace(
                source_sha, "trade_memory_records", source_id, account_id, mode
            )
            payload = {
                key: _bounded(data.get(key))
                for key in ("symbol", "side", "regime", "realized_pnl", "fees", "funding_pnl")
            }
            pnl = _decimal_or_none(data.get("realized_pnl"))
            closed_at = _parse_datetime(data.get("timestamp"))
            items.append(
                ImportItem(
                    namespace=namespace,
                    source_table="trade_memory_records",
                    source_id=source_id,
                    content_hash=sha256_text(canonical_json(payload)),
                    disposition=LEGACY_OBSERVATION,
                    reason="LEGACY_MEMORY_NO_LEDGER_PROOF",
                    account_id=account_id,
                    mode=mode,
                    symbol=_bounded(data.get("symbol"), 32),
                    direction=_bounded(data.get("side"), 8),
                    economic_closed_at=closed_at,
                    proof_kind="LEGACY_MEMORY_RECORD",
                    near_duplicate_fingerprint=near_duplicate_fingerprint(
                        symbol=_bounded(data.get("symbol"), 32),
                        direction=_bounded(data.get("side"), 8),
                        pnl=pnl,
                        closed_at=closed_at,
                    ),
                    source_json={k: v for k, v in payload.items() if v is not None},
                )
            )
        return items

    def _lesson_items(
        self, connection, source_sha: str, *, account_id: str, mode: str
    ) -> list[ImportItem]:
        if not _table_exists(connection, "learning_lessons"):
            return []
        columns = _table_columns(connection, "learning_lessons")
        identity = "id" if "id" in columns else "lesson_id" if "lesson_id" in columns else None
        if identity is None:
            return []
        text_column = (
            "lesson"
            if "lesson" in columns
            else "content"
            if "content" in columns
            else "title"
            if "title" in columns
            else None
        )
        selectable = [identity] + ([text_column] if text_column else [])
        rows = connection.execute(
            f"select {', '.join(selectable)} from learning_lessons order by rowid"
        ).fetchall()
        items: list[ImportItem] = []
        for row in rows:
            data = dict(zip(selectable, row, strict=True))
            source_id = str(data.get(identity) or "")
            if not source_id:
                continue
            payload = {"text": _bounded(data.get(text_column), 2000) if text_column else None}
            items.append(
                ImportItem(
                    namespace=self._namespace(
                        source_sha, "learning_lessons", source_id, account_id, mode
                    ),
                    source_table="learning_lessons",
                    source_id=source_id,
                    content_hash=sha256_text(canonical_json(payload)),
                    disposition=QUARANTINED,
                    reason="LEGACY_LESSON_WITHOUT_EVIDENCE_REFS",
                    account_id=account_id,
                    mode=mode,
                    symbol=None,
                    direction=None,
                    economic_closed_at=None,
                    proof_kind="LEGACY_UNPROVEN",
                    near_duplicate_fingerprint=None,
                    source_json={k: v for k, v in payload.items() if v is not None},
                )
            )
        return items

    @staticmethod
    def _namespace(
        source_sha: str, table: str, source_id: str, account_id: str, mode: str
    ) -> str:
        """Exact identity: source DB + table + source id + account/mode.

        Account/mode are part of the key so importing the same source row into
        a different account is an explicit separate observation, never a silent
        overwrite.
        """
        return sha256_text(
            f"{source_sha}|{table}|{source_id}|{account_id}|{mode}"
        )

    # ------------------------------------------------------------------
    async def import_plan(
        self,
        plan: ImportPlan,
        *,
        resume_batch_id: str | None = None,
        fail_after: int | None = None,
        batch_id: str | None = None,
        on_item: Callable[[int], None] | None = None,
    ) -> ImportReport:
        self.require_import_authorization()
        await self._assert_actual_binds()
        batch_id = batch_id or f"batch_{plan.plan_hash[:32]}"
        resolved_batch_id = resume_batch_id or batch_id

        async with self.session_factory() as session:
            bound_batch = await session.get(GrowthImportBatchORM, resolved_batch_id)
            if resume_batch_id is not None:
                if bound_batch is None:
                    raise ImportSafetyError(
                        f"resume batch not found: {resume_batch_id}"
                    )
                if (
                    bound_batch.source_db_sha256 != plan.source_sha256
                    or bound_batch.plan_hash != plan.plan_hash
                ):
                    raise ImportSafetyError(
                        "resume batch source/plan identity mismatch; refusing mutation"
                    )
                if bound_batch.status not in {BATCH_PLANNED, BATCH_IMPORTING, BATCH_FAILED}:
                    raise ImportSafetyError(
                        f"resume batch has non-resumable status {bound_batch.status}"
                    )
            elif bound_batch is None:
                session.add(
                    GrowthImportBatchORM(
                        batch_id=resolved_batch_id,
                        source_db_path=plan.source_path,
                        source_db_sha256=plan.source_sha256,
                        plan_hash=plan.plan_hash,
                        status=BATCH_PLANNED,
                    )
                )
                await session.commit()
            else:
                # Any already-existing resolved batch ID must prove the same
                # source/plan identity; ordinary batch_id reuse is not a
                # bypass around the explicit resume guard.
                if (
                    bound_batch.source_db_sha256 != plan.source_sha256
                    or bound_batch.plan_hash != plan.plan_hash
                ):
                    raise ImportSafetyError(
                        "existing batch source/plan identity mismatch; refusing mutation"
                    )
                if bound_batch.status not in {
                    BATCH_PLANNED,
                    BATCH_IMPORTING,
                    BATCH_FAILED,
                    BATCH_COMPLETED,
                }:
                    raise ImportSafetyError(
                        f"existing batch has non-resumable status {bound_batch.status}"
                    )

        if resume_batch_id is None:
            async with self.session_factory() as session:
                existing = (
                    await session.execute(
                        select(GrowthImportBatchORM).where(
                            GrowthImportBatchORM.source_db_sha256 == plan.source_sha256,
                            GrowthImportBatchORM.plan_hash == plan.plan_hash,
                            GrowthImportBatchORM.status == BATCH_COMPLETED,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return ImportReport(
                        batch_id=existing.batch_id,
                        status=BATCH_COMPLETED,
                        idempotent=True,
                    )

        imported = quarantined = duplicates = conflicts = 0
        for index, item in enumerate(plan.items):
            if on_item is not None:
                on_item(index)
            if fail_after is not None and index >= fail_after:
                await self._set_batch_status(resolved_batch_id, BATCH_FAILED)
                raise InjectedImportFailure(f"injected failure after {index} items")
            async with self.session_factory() as session:
                batch = await session.get(GrowthImportBatchORM, resolved_batch_id)
                if batch is None:
                    batch = GrowthImportBatchORM(
                        batch_id=resolved_batch_id,
                        source_db_path=plan.source_path,
                        source_db_sha256=plan.source_sha256,
                        plan_hash=plan.plan_hash,
                        status=BATCH_IMPORTING,
                    )
                    session.add(batch)
                    await session.commit()
                existing_item = (
                    await session.execute(
                        select(GrowthImportItemORM).where(
                            GrowthImportItemORM.batch_id == resolved_batch_id,
                            GrowthImportItemORM.namespace == item.namespace,
                        )
                    )
                ).scalar_one_or_none()
                if existing_item is not None:
                    if existing_item.disposition == DUPLICATE_STRONG:
                        duplicates += 1
                    elif existing_item.disposition == CONTENT_CONFLICT:
                        conflicts += 1
                    elif existing_item.disposition == QUARANTINED:
                        quarantined += 1
                    else:
                        imported += 1
                    continue

                observation = await session.get(
                    GrowthLegacyObservationORM, item.namespace
                )
                if observation is not None:
                    if observation.content_hash == item.content_hash:
                        disposition, reason, status = (
                            DUPLICATE_STRONG,
                            "EXACT_NAMESPACE_AND_CONTENT",
                            DUPLICATE_STRONG,
                        )
                        duplicates += 1
                    else:
                        disposition, reason, status = (
                            CONTENT_CONFLICT,
                            "SAME_NAMESPACE_DIFFERENT_CONTENT",
                            QUARANTINED,
                        )
                        conflicts += 1
                    target_kind, target_id = None, observation.observation_id
                else:
                    suspect = False
                    if item.near_duplicate_fingerprint:
                        suspect = (
                            await session.execute(
                                select(GrowthLegacyObservationORM.observation_id).where(
                                    GrowthLegacyObservationORM.near_duplicate_fingerprint
                                    == item.near_duplicate_fingerprint,
                                    GrowthLegacyObservationORM.batch_id != resolved_batch_id,
                                )
                            )
                        ).first() is not None
                    disposition = (
                        DUPLICATE_SUSPECT
                        if suspect
                        else item.disposition
                    )
                    reason = (
                        "NEAR_DUPLICATE_SYMBOL_TIME_PNL_NOT_MERGED"
                        if suspect
                        else item.reason
                    )
                    status = QUARANTINED if suspect else disposition
                    session.add(
                        GrowthLegacyObservationORM(
                            observation_id=item.namespace,
                            batch_id=resolved_batch_id,
                            namespace=item.namespace,
                            account_id=item.account_id,
                            mode=item.mode,
                            symbol=item.symbol,
                            direction=item.direction,
                            economic_closed_at=item.economic_closed_at,
                            imported_at=utcnow(),
                            known_at=utcnow(),
                            status=status,
                            proof_kind=item.proof_kind,
                            content_hash=item.content_hash,
                            near_duplicate_fingerprint=item.near_duplicate_fingerprint,
                            source_json_sanitized=item.source_json,
                        )
                    )
                    target_kind, target_id = "LEGACY_OBSERVATION", item.namespace
                    if status == QUARANTINED:
                        quarantined += 1
                    else:
                        imported += 1
                session.add(
                    GrowthImportItemORM(
                        batch_id=resolved_batch_id,
                        namespace=item.namespace,
                        source_table=item.source_table,
                        source_id=item.source_id,
                        content_hash=item.content_hash,
                        disposition=disposition,
                        reason=reason,
                        target_kind=target_kind,
                        target_id=target_id,
                        imported_at=utcnow(),
                    )
                )
                batch = await session.get(GrowthImportBatchORM, resolved_batch_id)
                batch.status = BATCH_IMPORTING
                batch.imported_count = (batch.imported_count or 0) + (
                    1 if status == LEGACY_OBSERVATION else 0
                )
                batch.quarantined_count = (batch.quarantined_count or 0) + (
                    1 if status == QUARANTINED else 0
                )
                batch.duplicate_count = (batch.duplicate_count or 0) + (
                    1 if disposition in {DUPLICATE_STRONG, DUPLICATE_SUSPECT} else 0
                )
                await session.commit()

        await self._set_batch_status(resolved_batch_id, BATCH_COMPLETED)
        return ImportReport(
            batch_id=resolved_batch_id,
            status=BATCH_COMPLETED,
            imported=imported,
            quarantined=quarantined,
            duplicates=duplicates,
            conflicts=conflicts,
            resumed=resume_batch_id is not None,
        )

    async def _set_batch_status(self, batch_id: str, status: str) -> None:
        async with self.session_factory() as session:
            batch = await session.get(GrowthImportBatchORM, batch_id)
            if batch is None:
                raise ImportSafetyError(
                    f"cannot set status for unknown batch identity: {batch_id}"
                )
            batch.status = status
            if status == BATCH_COMPLETED:
                batch.completed_at = utcnow()
            await session.commit()

    async def rollback(
        self,
        batch_id: str,
        *,
        expected_source_sha256: str | None = None,
        expected_plan_hash: str | None = None,
    ) -> dict[str, int]:
        """Delete only this exact batch; authorization/target identity required."""
        self.require_import_authorization()
        await self._assert_actual_binds()
        async with self.session_factory() as session:
            batch = await session.get(GrowthImportBatchORM, batch_id)
            if batch is None:
                raise ImportSafetyError(f"rollback batch not found: {batch_id}")
            if batch.source_db_sha256 in (None, "", "UNKNOWN") or batch.plan_hash in (
                None,
                "",
                "UNKNOWN",
            ):
                raise ImportSafetyError("rollback batch has no provable identity")
            if (
                expected_source_sha256 is not None
                and batch.source_db_sha256 != expected_source_sha256
            ):
                raise ImportSafetyError("rollback source identity mismatch")
            if expected_plan_hash is not None and batch.plan_hash != expected_plan_hash:
                raise ImportSafetyError("rollback plan identity mismatch")
            observations = await session.execute(
                delete(GrowthLegacyObservationORM).where(
                    GrowthLegacyObservationORM.batch_id == batch_id
                )
            )
            items = await session.execute(
                delete(GrowthImportItemORM).where(
                    GrowthImportItemORM.batch_id == batch_id
                )
            )
            batch = await session.get(GrowthImportBatchORM, batch_id)
            if batch is not None:
                batch.status = BATCH_ROLLED_BACK
                batch.rolled_back_at = utcnow()
            await session.commit()
            return {
                "observations_deleted": observations.rowcount or 0,
                "items_deleted": items.rowcount or 0,
            }


def _direction_from_result(value: Any) -> str | None:
    text = str(value or "").upper()
    if text in {"LONG", "SHORT"}:
        return text
    return None
