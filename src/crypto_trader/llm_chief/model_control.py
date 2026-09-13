"""Operator-controlled LLM model selection (switchable from the frontend).

The ChiefTrader provider's model can be switched while the runtime is live —
no .env edit, no restart. Rules enforced here:

  - only allow-listed provider models can be selected (never arbitrary ids)
  - the selection is persisted, so a restart keeps the switched model
  - every switch is audit-logged (model ids only, never credentials)
  - switching a model NEVER changes decision authority, Risk or Execution:
    the live LLM remains the only new-direction authority either way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from crypto_trader.persistence.models import RuntimeSettingORM

LLM_MODEL_SETTING_KEY = "llm_model"

#: Models this deployment may select. Mirrors the provider's published list
#: (GET /v1/models → deepseek-flash, deepseek-v4-pro).
AVAILABLE_LLM_MODELS: tuple[str, ...] = ("deepseek-flash", "deepseek-v4-pro")
DEFAULT_LLM_MODEL = "deepseek-flash"

MODEL_SOURCE_RUNTIME_OVERRIDE = "RUNTIME_OVERRIDE"
MODEL_SOURCE_PROVIDER = "PROVIDER_CONFIG"
MODEL_SOURCE_DEFAULT = "DEFAULT"


class UnknownModelError(ValueError):
    """The requested model is not in the operator allow-list."""


class ModelSwitchUnavailable(RuntimeError):
    """No live LLM provider instance exists to switch."""


class LLMModelControl:
    def __init__(
        self,
        session_factory,
        *,
        provider: Any | None = None,
        audit: Any | None = None,
        available: tuple[str, ...] = AVAILABLE_LLM_MODELS,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.audit = audit
        self.available = tuple(dict.fromkeys(str(m).strip() for m in available if str(m).strip()))

    # ------------------------------------------------------------ persistence
    async def persisted_model(self) -> str | None:
        async with self.session_factory() as session:
            row = await session.get(RuntimeSettingORM, LLM_MODEL_SETTING_KEY)
            return row.value if row is not None else None

    async def _persist(self, model: str, actor: str) -> None:
        async with self.session_factory() as session:
            row = await session.get(RuntimeSettingORM, LLM_MODEL_SETTING_KEY)
            if row is None:
                row = RuntimeSettingORM(
                    key=LLM_MODEL_SETTING_KEY,
                    value=model,
                    updated_at=datetime.now(UTC),
                    updated_by=actor,
                )
                session.add(row)
            else:
                row.value = model
                row.updated_at = datetime.now(UTC)
                row.updated_by = actor
            await session.commit()

    # ------------------------------------------------------------------ state
    def _normalize(self, model: str) -> str:
        candidate = str(model or "").strip()
        for allowed in self.available:
            if candidate.lower() == allowed.lower():
                return allowed
        raise UnknownModelError(f"unsupported LLM model: {candidate!r}")

    @property
    def live_model(self) -> str | None:
        model = getattr(self.provider, "model", None)
        return str(model) if model else None

    async def state(self) -> dict:
        persisted = await self.persisted_model()
        live = self.live_model
        if live:
            source = (
                MODEL_SOURCE_RUNTIME_OVERRIDE
                if persisted == live
                else MODEL_SOURCE_PROVIDER
            )
            current = live
        elif persisted:
            current, source = persisted, MODEL_SOURCE_RUNTIME_OVERRIDE
        else:
            current, source = DEFAULT_LLM_MODEL, MODEL_SOURCE_DEFAULT
        return {
            "provider": getattr(self.provider, "name", None),
            "model": current,
            "source": source,
            "available": list(self.available),
            "switch_supported": self.provider is not None,
            "configured": bool(getattr(self.provider, "api_key", None)),
        }

    # --------------------------------------------------------------- switching
    async def switch(self, model: str, *, actor: str = "operator") -> dict:
        allowed = self._normalize(model)
        if self.provider is None:
            raise ModelSwitchUnavailable("no live LLM provider in this runtime")
        previous = self.live_model
        self.provider.model = allowed
        await self._persist(allowed, actor)
        if self.audit is not None:
            await self.audit.log(
                "LLM_MODEL_SWITCHED",
                target=allowed,
                actor=actor,
                before={"model": previous},
                after={"model": allowed, "provider": getattr(self.provider, "name", None)},
            )
        return {
            **(await self.state()),
            "previous_model": previous,
            "changed": previous != allowed,
        }

    async def apply_persisted(self) -> str | None:
        """Apply the stored override to the live provider (startup path)."""
        persisted = await self.persisted_model()
        if persisted is None or self.provider is None:
            return None
        try:
            canonical = self._normalize(persisted)
        except UnknownModelError:
            return None  # stale/removed model id: keep the provider's own config
        self.provider.model = canonical
        return canonical
