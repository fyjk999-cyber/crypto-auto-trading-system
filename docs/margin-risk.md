# Margin Risk

- initial_margin = position_notional / effective_leverage.
- maintenance_margin supports a tier-provider hook; default brackets 0.1%, 0.25%, 0.5%.
- available_margin = total_balance - initial_margin used.
- margin_ratio = equity / maintenance_margin; unhealthy below 1.0.
- Hard max leverage = 6x. Alpha recommendations above 6x are capped.
