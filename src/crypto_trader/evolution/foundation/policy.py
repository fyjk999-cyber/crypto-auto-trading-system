"""Machine-readable protected core mutation policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvolutionMutationPolicy:
    allowed_candidate_types: tuple[str, ...] = (
        "FACTOR",
        "FACTOR_WEIGHT",
        "FACTOR_COMBINATION",
        "FACTOR_PARAMETER",
        "STRATEGY_PARAMETER",
        "STRATEGY_ROUTING",
        "PROMPT",
        "MODEL_ROUTING",
        "KNOWLEDGE",
        "RESEARCH_PROCESS",
    )
    protected_path_prefixes: tuple[str, ...] = (
        "src/crypto_trader/runtime/engine.py",
        "src/crypto_trader/risk/",
        "src/crypto_trader/execution/",
        "src/crypto_trader/ledger/",
        "src/crypto_trader/order/",
        "src/crypto_trader/exchange/",
        "src/crypto_trader/credentials",
        "src/crypto_trader/reconciliation/",
    )
    protected_config_keys: tuple[str, ...] = (
        "live_trading_enabled",
        "kill_switch",
        "max_leverage",
        "max_drawdown",
        "validation_gate",
        "promotion_policy",
    )

    def is_candidate_type_allowed(self, candidate_type: str) -> bool:
        return candidate_type in self.allowed_candidate_types

    def is_path_protected(self, path: str) -> bool:
        return any(path == p or path.startswith(p) for p in self.protected_path_prefixes)

    def validate(self, candidate) -> tuple[bool, str]:
        if not self.is_candidate_type_allowed(candidate.candidate_type):
            return False, "CANDIDATE_TYPE_FORBIDDEN"
        for path in candidate.changed_files:
            if self.is_path_protected(path):
                return False, "PROTECTED_PATH_VIOLATION"
        for key in candidate.config_diff:
            if key in self.protected_config_keys:
                return False, "PROTECTED_CONFIG_KEY"
        return True, "OK"
