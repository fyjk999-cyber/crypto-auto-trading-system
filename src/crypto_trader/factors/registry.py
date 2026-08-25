"""Factor registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FactorDefinition:
    factor_id: str
    name: str
    version: str = "1.0"
    status: str = "ACTIVE"
    description: str = ""


class FactorRegistry:
    def __init__(self) -> None:
        self.factors: dict[str, FactorDefinition] = {}
        self._register_builtin()

    def _register_builtin(self) -> None:
        builtins = [
            ("trend", "Trend", "Market direction"),
            ("momentum", "Momentum", "Price momentum"),
            ("volatility", "Volatility", "Market risk"),
            ("volume", "Volume", "Volume confirmation"),
            ("orderflow", "OrderFlow", "Buy/sell imbalance"),
            ("funding", "Funding", "Funding pressure"),
            ("open_interest", "Open Interest", "OI change/divergence"),
        ]
        for factor_id, name, description in builtins:
            self.register(FactorDefinition(factor_id, name, description=description))

    def register(self, definition: FactorDefinition) -> None:
        self.factors[definition.factor_id] = definition

    def get(self, factor_id: str) -> FactorDefinition | None:
        return self.factors.get(factor_id)

    def list(self) -> list[dict]:
        return [
            {
                "factor_id": f.factor_id,
                "name": f.name,
                "version": f.version,
                "status": f.status,
                "description": f.description,
            }
            for f in self.factors.values()
        ]
