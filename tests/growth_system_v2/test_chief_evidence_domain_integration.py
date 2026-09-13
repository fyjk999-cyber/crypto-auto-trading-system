"""B1A: default evidence-domain isolation for Chief card retrieval."""
from __future__ import annotations

from crypto_trader.learning.growth_card_retrieval import (
    CardRankingPolicy,
    ExperienceCardRetriever,
)
from crypto_trader.learning.growth_v2_contracts import AdaptiveExperienceCard


def _card(rule_id, mode, account_id="default"):
    return AdaptiveExperienceCard(
        rule_id=rule_id, title=rule_id, content=rule_id,
        account_id=account_id, mode=mode, status="ACTIVE",
    )


def _reject(card, *, account_id="default", mode):
    return ExperienceCardRetriever(None, policy=CardRankingPolicy())._scope_rejection(
        card, account_id, mode
    )


def test_paper_default_rejects_live_and_backtest_cards():
    assert _reject(_card("card-paper", "PAPER"), mode="PAPER") == []
    assert _reject(_card("card-live", "LIVE"), mode="PAPER")
    assert _reject(_card("card-backtest", "BACKTEST"), mode="PAPER")


def test_live_default_rejects_paper_and_backtest_cards():
    assert _reject(_card("card-live", "LIVE"), mode="LIVE") == []
    assert _reject(_card("card-paper", "PAPER"), mode="LIVE")
    assert _reject(_card("card-backtest", "BACKTEST"), mode="LIVE")


def test_backtest_default_is_own_domain_and_account_isolated():
    assert _reject(_card("card-backtest", "BACKTEST"), mode="BACKTEST") == []
    assert _reject(_card("card-paper", "PAPER"), mode="BACKTEST")
    other = _card("card-paper-other", "PAPER", account_id="acct-b")
    assert _reject(other, account_id="acct-a", mode="PAPER") == [
        "ACCOUNT_MISMATCH"
    ]
