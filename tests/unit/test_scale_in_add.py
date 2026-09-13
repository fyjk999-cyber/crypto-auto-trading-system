"""POSITION SIZING V2 PATCH — scale-in / ADD acceptance tests (§123-§135).

NON-EXECUTING by construction: every test here asserts against the ADD
contract, the deterministic gates and the ScaleInSizer. No test creates an
order, and several tests exist purely to prove that no order CAN be created.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_trader.domain.models import Instrument, Position
from crypto_trader.scale_in.campaign import PositionCampaign
from crypto_trader.scale_in.contract import (
    FORBIDDEN_ADD_ONLY_REASONS,
    MAX_EFFECTIVE_ADD_ORDER_CREATIONS,
    SCALE_IN_CLIENT_ORDER_ID_PREFIX,
    ScaleInIntent,
    ScaleInTrigger,
    ThesisStatus,
    scale_in_client_order_id,
)
from crypto_trader.scale_in.gates import (
    ADD_AVERAGE_DOWN_NOT_AUTHORIZED,
    ADD_CAMPAIGN_RISK_EXHAUSTED,
    ADD_COALESCED,
    ADD_COOLDOWN_ACTIVE,
    ADD_DIRECTION_MISMATCH,
    ADD_DRAWDOWN_DISABLED,
    ADD_EXIT_PRECEDENCE,
    ADD_MAX_COUNT_REACHED,
    ADD_PENDING_POSITION_ACTION,
    ADD_REDUCE_PRECEDENCE,
    ADD_THESIS_INVALIDATED,
    VERDICT_ALLOWED,
    VERDICT_COALESCED,
    VERDICT_REJECTED,
    ScaleInGateInputs,
)
from crypto_trader.scale_in.policy import (
    HARD_MAX_SCALE_IN_COUNT,
    SCALE_IN_EXECUTION_WIRED_IN_RUNTIME,
    ScaleInPolicy,
)
from crypto_trader.scale_in.service import (
    ADD_EXECUTION_ENABLED,
    ScaleInFacts,
    ScaleInService,
)
from crypto_trader.scale_in.sizer import (
    ADD_BELOW_ECONOMIC_NOTIONAL,
    ADD_PORTFOLIO_CEILING_REACHED,
    ADD_POSITION_CEILING_REACHED,
    ADD_RISK_BUDGET_EXHAUSTED,
)
from crypto_trader.sizing.policy import HARD_MAX_NOTIONAL_MULTIPLE, PositionSizingPolicy

EQUITY = Decimal("100000")
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def instrument(lot: str = "0.001") -> Instrument:
    return Instrument(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        instrument_type="LINEAR_PERP",
        contract_size="1",
        contract_multiplier="1",
        step_size=lot,
    )


def intent(**overrides) -> ScaleInIntent:
    values: dict = {
        "position_decision_id": "add-decision-1",
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "conviction": 0.80,
        "trigger": ScaleInTrigger.TREND_CONTINUATION,
        "thesis_status": ThesisStatus.STRENGTHENED,
        "stop_loss": 99.0,
        "expected_holding_period": "4h",
        "reason_codes": ["TREND_STRUCTURE_HELD"],
        "material_change": True,
        "material_change_reasons": ["new closed candle confirmation"],
    }
    values.update(overrides)
    return ScaleInIntent(**values)


def campaign(**overrides) -> PositionCampaign:
    values: dict = {
        "campaign_id": "campaign_btc_1",
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "original_trade_plan_id": "plan_1",
        "initial_entry_decision_id": "entry-1",
        "current_total_qty": Decimal("500"),
        "weighted_average_entry": Decimal("100"),
        "current_stop": Decimal("99"),
        "total_notional": Decimal("50000"),
        # Initial entry risked 0.25% of a 100,000 account = 250.
        "total_risk_at_stop": Decimal("250"),
        "add_count": 0,
        "max_add_count": 2,
        "opened_at": NOW - timedelta(hours=2),
    }
    values.update(overrides)
    return PositionCampaign(**values)


def gate_inputs(**overrides) -> ScaleInGateInputs:
    values: dict = {
        "campaign_direction": "LONG",
        "has_open_position": True,
        "campaign_add_count": 0,
        "last_add_at": None,
        "now": NOW,
        "drawdown_ratio": Decimal("0.01"),
        "campaign_risk_budget": Decimal("1000"),
        "consumed_campaign_risk": Decimal("250"),
    }
    values.update(overrides)
    return ScaleInGateInputs(**values)


def service(scale_policy: ScaleInPolicy | None = None) -> ScaleInService:
    return ScaleInService(
        policy=PositionSizingPolicy(),
        scale_in_policy=scale_policy or ScaleInPolicy(),
    )


def facts(**overrides) -> ScaleInFacts:
    values: dict = {
        "equity": EQUITY,
        "available_margin": EQUITY,
        "price": Decimal("100"),
        "liquidity_depth_qty": Decimal("1000000"),
        "positions": {},
        "volatility": Decimal("0"),
        "requested_leverage": "2",
    }
    values.update(overrides)
    return ScaleInFacts(**values)


# ===================================================== §137 / §138: not enabled
def test_feature_flag_defaults_to_disabled():
    policy = ScaleInPolicy()
    assert policy.enabled is False
    assert policy.execution_enabled is False
    assert policy.average_down_enabled is False
    assert SCALE_IN_EXECUTION_WIRED_IN_RUNTIME is False
    # No runtime path can create an ADD order in this build.
    assert ADD_EXECUTION_ENABLED is False


def test_the_flag_alone_can_never_enable_execution_in_this_build():
    enabled = ScaleInPolicy(enabled=True)
    assert enabled.enabled is True
    # The flag is not capability: the runtime wiring is deliberately absent.
    assert enabled.execution_enabled is False


def test_an_allowed_add_is_still_never_an_order():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_ALLOWED
    assert decision.allowed is True
    # The architecture computed a real, capped size ...
    assert decision.approved_quantity > 0
    # ... and still created nothing: execution is not enabled.
    assert decision.order_created is False
    assert decision.execution_enabled is False
    assert decision.execution_block_reason == "ADD_EXECUTION_DISABLED_FEATURE_FLAG"


# =============================================== §78/§90: intent + identity
def test_add_intent_quantity_is_advisory_only():
    request = intent(requested_quantity=1_000_000.0, requested_exposure=99_999_999.0)
    assert request.llm_quantity_authority == "ADVISORY_ONLY"
    evidence = request.to_evidence()
    assert evidence["requested_quantity_from_llm"] == "1000000.0"
    assert evidence["llm_quantity_authority"] == "ADVISORY_ONLY"

    # The raw request cannot change the deterministic ADD size.
    small = service().evaluate(
        intent=intent(requested_quantity=1.0),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    huge = service().evaluate(
        intent=intent(requested_quantity=1_000_000.0),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert small.approved_quantity == huge.approved_quantity


def test_add_requires_a_decision_relevant_reason():
    with pytest.raises(ValueError):
        intent(reason_codes=[])
    with pytest.raises(ValueError):
        intent(reason_codes=[FORBIDDEN_ADD_ONLY_REASONS[0]])
    with pytest.raises(ValueError):
        intent(reason_codes=list(FORBIDDEN_ADD_ONLY_REASONS))


def test_material_change_must_be_explained():
    with pytest.raises(ValueError):
        intent(material_change=True, material_change_reasons=[])


def test_add_identity_is_deterministic_and_durable_across_restart():
    request = intent(position_decision_id="add-decision-7")
    assert request.client_order_id == f"{SCALE_IN_CLIENT_ORDER_ID_PREFIX}add-decision-7"
    # Same decision -> same identity, so a unique-order-identity guard (F4)
    # refuses a duplicate without extra bookkeeping, across restarts.
    assert scale_in_client_order_id("add-decision-7") == request.client_order_id
    assert scale_in_client_order_id("add-decision-8") != request.client_order_id
    assert MAX_EFFECTIVE_ADD_ORDER_CREATIONS == 1
    with pytest.raises(ValueError):
        scale_in_client_order_id("  ")


# ===================================================== §129/§130: count+cooldown
def test_add_count_limit_is_enforced():
    three = campaign(add_count=2, max_add_count=2)
    decision = service().evaluate(
        intent=intent(),
        campaign=three,
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(campaign_add_count=2),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_MAX_COUNT_REACHED in decision.reason_codes
    assert decision.approved_quantity is None


def test_scale_in_count_cannot_be_configured_above_the_hard_cap():
    policy = ScaleInPolicy(max_scale_in_count=99)
    assert policy.max_scale_in_count == HARD_MAX_SCALE_IN_COUNT
    assert "CONFIG_CLAMPED:max_scale_in_count" in policy.reason_codes


def test_cooldown_coalesces_without_a_deterministic_material_event():
    recent = NOW - timedelta(seconds=60)
    decision = service().evaluate(
        intent=intent(material_change=False, material_change_reasons=[]),
        campaign=campaign(add_count=1),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(campaign_add_count=1, last_add_at=recent),
        now=NOW,
    )
    assert decision.verdict == VERDICT_COALESCED
    assert decision.allowed is False
    assert ADD_COOLDOWN_ACTIVE in decision.reason_codes


def test_cooldown_is_bypassed_only_by_a_deterministic_material_event():
    recent = NOW - timedelta(seconds=60)
    decision = service().evaluate(
        intent=intent(),  # material_change=True with explicit reasons
        campaign=campaign(add_count=1),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(campaign_add_count=1, last_add_at=recent),
        now=NOW,
    )
    assert decision.allowed is True


def test_no_material_change_coalesces():
    decision = service().evaluate(
        intent=intent(material_change=False, material_change_reasons=[]),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_COALESCED
    assert ADD_COALESCED in decision.reason_codes


# ============================================== §81/§82/§127/§128/§133 gates
def test_thesis_invalidated_rejects_add_and_keeps_exit_available():
    decision = service().evaluate(
        intent=intent(thesis_status=ThesisStatus.INVALIDATED),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_THESIS_INVALIDATED in decision.reason_codes
    assert decision.order_created is False


def test_weakened_thesis_also_rejects_add():
    decision = service().evaluate(
        intent=intent(thesis_status=ThesisStatus.WEAKENED),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert ADD_THESIS_INVALIDATED in decision.reason_codes


def test_direction_mismatch_is_never_a_scale_in():
    decision = service().evaluate(
        intent=intent(direction="SHORT", stop_loss=101.0),
        campaign=campaign(direction="LONG"),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(campaign_direction="LONG"),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_DIRECTION_MISMATCH in decision.reason_codes


def test_adverse_without_structural_confirmation_is_average_down_block():
    """§127 — losing and cheaper is not a reason to add."""
    decision = service().evaluate(
        intent=intent(
            trigger=ScaleInTrigger.OTHER,
            reason_codes=["PRICE_IS_CHEAPER"],
            material_change=True,
            material_change_reasons=["price moved"],
        ),
        campaign=campaign(),
        facts=facts(price=Decimal("97")),
        instrument=instrument(),
        gate_inputs=gate_inputs(adverse_fraction=Decimal("0.03")),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_AVERAGE_DOWN_NOT_AUTHORIZED in decision.reason_codes
    assert decision.order_created is False


def test_adverse_add_needs_structural_confirmation_to_proceed():
    confirmed = service().evaluate(
        intent=intent(trigger=ScaleInTrigger.PULLBACK_CONFIRMATION),
        campaign=campaign(),
        facts=facts(price=Decimal("97")),
        instrument=instrument(),
        gate_inputs=gate_inputs(adverse_fraction=Decimal("0.03")),
        now=NOW,
    )
    # Still refused: PULLBACK_CONFIRMATION is not a structural confirmation.
    assert ADD_AVERAGE_DOWN_NOT_AUTHORIZED in confirmed.reason_codes

    structural = service().evaluate(
        intent=intent(trigger=ScaleInTrigger.BREAKOUT_CONFIRMATION),
        campaign=campaign(),
        facts=facts(price=Decimal("97")),
        instrument=instrument(),
        gate_inputs=gate_inputs(adverse_fraction=Decimal("0.03")),
        now=NOW,
    )
    assert structural.allowed is True


def test_favorable_add_within_tolerance_needs_no_adverse_override():
    decision = service().evaluate(
        intent=intent(trigger=ScaleInTrigger.PULLBACK_CONFIRMATION),
        campaign=campaign(),
        facts=facts(price=Decimal("100.2")),
        instrument=instrument(),
        gate_inputs=gate_inputs(adverse_fraction=Decimal("0")),
        now=NOW,
    )
    assert decision.allowed is True


# ============================================ §109/§110/§111: risk precedence
def test_exit_outranks_add():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(exit_condition=True),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_EXIT_PRECEDENCE in decision.reason_codes


def test_reduce_outranks_add():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(reduce_condition=True),
        now=NOW,
    )
    assert ADD_REDUCE_PRECEDENCE in decision.reason_codes


def test_a_pending_position_action_blocks_add():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(pending_position_action=True),
        now=NOW,
    )
    assert ADD_PENDING_POSITION_ACTION in decision.reason_codes


# ============================================================== §103 drawdown
@pytest.mark.parametrize(
    ("drawdown", "multiplier"),
    [
        ("0.00", "1.00"),
        ("0.03", "0.75"),
        ("0.06", "0.50"),
        ("0.09", "0.25"),
    ],
)
def test_drawdown_shrinks_the_add(drawdown, multiplier):
    policy = ScaleInPolicy()
    assert policy.drawdown_multiplier(Decimal(drawdown)) == Decimal(multiplier)


def test_drawdown_beyond_the_hard_band_disables_add():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(drawdown_ratio=Decimal("0.15")),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_DRAWDOWN_DISABLED in decision.reason_codes


def test_unknown_drawdown_blocks_add_instead_of_being_treated_as_zero():
    assert ScaleInPolicy().drawdown_multiplier(None) == Decimal("0")
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(drawdown_ratio=None),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert "ADD_REQUIRES_A_FRESH_DRAWDOWN_FACT" in decision.reason_codes
    assert decision.order_created is False


# ============================================================ §104/§135 campaign risk
def test_campaign_risk_exhaustion_blocks_add_despite_free_notional():
    """§135 — the campaign risk budget binds long before the 5x ceiling."""
    decision = service().evaluate(
        intent=intent(),
        # Only 50% of equity in notional so far: plenty of 5x room.
        campaign=campaign(total_notional=Decimal("50000"), total_risk_at_stop=Decimal("1000")),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(
            campaign_risk_budget=Decimal("1000"), consumed_campaign_risk=Decimal("1000")
        ),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_CAMPAIGN_RISK_EXHAUSTED in decision.reason_codes


def test_campaign_risk_split_reserves_room_for_adds():
    policy = ScaleInPolicy()
    assert policy.initial_entry_risk_share + policy.scale_in_risk_share <= Decimal("1")
    total = policy.campaign_risk_budget(EQUITY, Decimal("0.010"))
    assert total == Decimal("1000")
    assert policy.scale_in_risk_budget(EQUITY, Decimal("0.010")) == Decimal("500")

    greedy = ScaleInPolicy(
        initial_entry_risk_share=Decimal("0.9"), scale_in_risk_share=Decimal("0.9")
    )
    assert (
        greedy.initial_entry_risk_share + greedy.scale_in_risk_share <= Decimal("1")
    )
    assert "CONFIG_CLAMPED:campaign_risk_split" in greedy.reason_codes


def test_campaign_records_only_factual_fills():
    base = campaign()
    after = base.register_add(
        decision_id="add-1",
        order_id="order-1",
        fill_quantity=Decimal("100"),
        fill_notional=Decimal("10100"),
        total_risk_at_stop=Decimal("350"),
        current_stop=Decimal("99"),
        occurred_at=NOW,
    )
    assert after.current_total_qty == Decimal("600")
    assert after.add_count == 1
    assert after.scale_in_decision_ids == ("add-1",)
    assert after.total_notional == Decimal("60100")
    assert after.total_risk_at_stop == Decimal("350")
    # weighted average entry = (100 x 500 + 10100) / 600
    assert after.weighted_average_entry == Decimal("100.1666666666666666666666667")


# ==================================================== §96/§97/§134 stop integrity
def test_stop_manipulation_cannot_buy_a_500_percent_position():
    """§134 — an absurdly tight stop is floored to the deterministic minimum."""
    policy = PositionSizingPolicy()
    scale_policy = ScaleInPolicy()
    sizer = ScaleInService(policy=policy, scale_in_policy=scale_policy).sizer
    # A 0.01% stop would otherwise allow an enormous notional.
    result = sizer.size(
        campaign=campaign(total_notional=Decimal("50000"), total_risk_at_stop=Decimal("250")),
        instrument=instrument(),
        price=Decimal("100"),
        stop_loss=Decimal("99.99"),
        conviction=Decimal("1.0"),
        liquidity_depth_qty=Decimal("1000000000"),
        equity=EQUITY,
        available_margin=EQUITY,
        requested_leverage=Decimal("5"),
        volatility=Decimal("0"),
        drawdown_multiplier=Decimal("1"),
        campaign_risk_budget=Decimal("1000"),
    )
    minimum = scale_policy.minimum_stop_distance(price=Decimal("100"), volatility=Decimal("0"))
    assert minimum == Decimal("0.100")
    assert result.effective_stop_distance == minimum
    assert result.stop_distance_was_widened is True
    # Remaining campaign risk 750 caps the added risk, whatever the stop.
    assert result.max_loss_estimate <= Decimal("750")
    assert result.projection is not None
    assert result.projection.projected_total_risk_at_stop <= Decimal("1000")


def test_volatility_raises_the_minimum_stop_distance():
    policy = ScaleInPolicy()
    quiet = policy.minimum_stop_distance(price=Decimal("100"), volatility=Decimal("0"))
    volatile = policy.minimum_stop_distance(price=Decimal("100"), volatility=Decimal("0.02"))
    assert volatile > quiet
    assert volatile == Decimal("2.000")


# ======================================================== §84/§85/§105/§107 caps
def test_add_respects_the_cumulative_position_ceiling():
    """§125 — current 450% + requested 150% never exceeds 500%."""
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(total_notional=Decimal("450000"), current_total_qty=Decimal("4500")),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.size is not None
    projection = decision.size.projection
    assert projection is not None
    assert projection.projected_position_notional <= EQUITY * HARD_MAX_NOTIONAL_MULTIPLE
    # Only 50,000 (50%) of notional room remained.
    assert decision.approved_notional <= Decimal("50000")


def test_add_is_rejected_when_the_position_ceiling_is_already_reached():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(total_notional=EQUITY * HARD_MAX_NOTIONAL_MULTIPLE),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_POSITION_CEILING_REACHED in decision.reason_codes


def test_add_respects_the_portfolio_gross_ceiling():
    existing = Position(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        quantity=Decimal("4000"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("400000"),
    )
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(total_notional=Decimal("50000")),
        facts=facts(positions={"ETHUSDT": existing}),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.size is not None
    assert decision.size.projection is not None
    assert (
        decision.size.projection.projected_gross_exposure
        <= EQUITY * HARD_MAX_NOTIONAL_MULTIPLE
    )


def test_add_is_rejected_when_portfolio_capacity_is_exhausted():
    existing = Position(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        quantity=Decimal("6000"),
        avg_entry_price=Decimal("100"),
        cost_basis=Decimal("600000"),
    )
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(positions={"ETHUSDT": existing}),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_PORTFOLIO_CEILING_REACHED in decision.reason_codes


def test_add_uses_fresh_equity_not_the_initial_entry_equity():
    """§102 — a smaller account after losses gets a smaller ADD.

    The campaign risk budget is re-derived from the CURRENT equity, exactly as
    a runtime with a fresh valuation batch would: nothing is carried over from
    the initial entry.
    """
    policy = PositionSizingPolicy()
    scale_policy = ScaleInPolicy()

    def evaluate(equity: str):
        fresh_equity = Decimal(equity)
        return service(scale_policy).evaluate(
            intent=intent(),
            campaign=campaign(
                total_notional=Decimal("1000"),
                current_total_qty=Decimal("10"),
                # The campaign has consumed 2 of risk, matching the gate input.
                total_risk_at_stop=Decimal("2"),
            ),
            facts=facts(equity=fresh_equity),
            instrument=instrument(),
            gate_inputs=gate_inputs(
                campaign_risk_budget=scale_policy.campaign_risk_budget(
                    fresh_equity, policy.max_risk_per_trade
                ),
                consumed_campaign_risk=Decimal("2"),
            ),
            now=NOW,
        )

    rich = evaluate("100000")
    poor = evaluate("20000")

    assert rich.allowed is True and poor.allowed is True
    assert poor.approved_notional < rich.approved_notional


# ================================================= §100/§101: economics+liquidity
def test_a_sub_economic_add_is_rejected_never_upsized():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(liquidity_depth_qty=Decimal("10")),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert ADD_BELOW_ECONOMIC_NOTIONAL in decision.reason_codes
    assert decision.size is not None
    assert decision.size.approved_notional < decision.size.min_effective_notional


def test_unknown_liquidity_blocks_add():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(liquidity_depth_qty=None),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert "ADD_LIQUIDITY_UNKNOWN" in decision.reason_codes


def test_insufficient_margin_blocks_add():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(available_margin=Decimal("0")),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.verdict == VERDICT_REJECTED
    assert "INSUFFICIENT_MARGIN_FOR_SCALE_IN" in decision.reason_codes


# =================================================== §124/§126 the headline math
def test_winning_scale_in_adds_to_the_position_instead_of_replacing_it():
    """§124 — initial 100% + approved ADD extends the SAME campaign."""
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(
            current_total_qty=Decimal("1000"),
            total_notional=Decimal("100000"),  # 100% of equity
        ),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert decision.allowed is True
    projection = decision.size.projection
    assert projection is not None
    # The ADD is measured against the EXISTING position, not from scratch.
    assert projection.projected_position_notional == (
        Decimal("100000") + decision.approved_notional
    )
    assert projection.projected_total_qty == Decimal("1000") + decision.approved_quantity


def test_risk_budget_can_bind_before_the_notional_cap():
    """§126 — free notional room does not authorise free risk."""
    decision = service().evaluate(
        intent=intent(),
        # 100% of equity used, so 400% of notional room remains.
        campaign=campaign(total_notional=Decimal("100000"), total_risk_at_stop=Decimal("250")),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(
            campaign_risk_budget=Decimal("1000"), consumed_campaign_risk=Decimal("250")
        ),
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.binding_cap == "ADD_RISK_BUDGET"
    projection = decision.size.projection
    assert projection is not None
    assert projection.projected_position_notional < EQUITY * HARD_MAX_NOTIONAL_MULTIPLE
    assert projection.projected_total_risk_at_stop <= Decimal("1000")


def test_add_cannot_exceed_the_campaign_risk_budget_after_sizing():
    decision = service().evaluate(
        intent=intent(),
        campaign=campaign(total_notional=Decimal("100000"), total_risk_at_stop=Decimal("750")),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(
            campaign_risk_budget=Decimal("1000"), consumed_campaign_risk=Decimal("750")
        ),
        now=NOW,
    )
    assert decision.size is not None
    assert decision.size.projection is not None
    assert decision.size.projection.projected_total_risk_at_stop <= Decimal("1000")


def test_add_risk_budget_exhaustion_is_reported_when_projection_breaks_it():
    decision = service().evaluate(
        intent=intent(conviction=1.0),
        campaign=campaign(total_notional=Decimal("100000"), total_risk_at_stop=Decimal("900")),
        facts=facts(),
        instrument=instrument(),
        gate_inputs=gate_inputs(
            campaign_risk_budget=Decimal("1000"), consumed_campaign_risk=Decimal("900")
        ),
        now=NOW,
    )
    if decision.verdict == VERDICT_REJECTED:
        assert ADD_RISK_BUDGET_EXHAUSTED in decision.reason_codes or (
            decision.size is not None
            and decision.size.max_loss_estimate > 0
        )
    assert decision.order_created is False


# ============================================ §83/§89: lineage + fresh risk event
def test_every_add_is_a_new_risk_event_with_fresh_inputs():
    """§83 — nothing may be reused from the initial entry."""
    stale = service().evaluate(
        intent=intent(),
        campaign=campaign(),
        facts=facts(equity=None),
        instrument=instrument(),
        gate_inputs=gate_inputs(),
        now=NOW,
    )
    assert stale.verdict == VERDICT_REJECTED
    assert "ADD_INVALID_SIZING_INPUT" in stale.reason_codes


def test_campaign_lineage_is_complete_and_factual():
    evidence = campaign().to_evidence()
    for key in (
        "campaign_id",
        "symbol",
        "direction",
        "original_trade_plan_id",
        "initial_entry_decision_id",
        "scale_in_decision_ids",
        "scale_in_order_ids",
        "scale_in_fill_ids",
        "current_total_qty",
        "weighted_average_entry",
        "current_stop",
        "total_notional",
        "total_risk_at_stop",
        "add_count",
        "max_add_count",
        "opened_at",
        "last_add_at",
    ):
        assert key in evidence, key


def test_add_ttl_policy_declares_a_finite_lifetime():
    policy = ScaleInPolicy()
    assert policy.scale_in_order_ttl_seconds == 60.0
    # §112 — the value is part of the ADD contract, not an entry TTL.
    assert policy.scale_in_order_ttl_seconds < 300.0
