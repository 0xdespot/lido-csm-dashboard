"""Capital efficiency calculations for CSM operators.

Pure functions - no async, no RPC calls. Easy to test.
"""

from datetime import datetime, timezone


def calculate_capital_efficiency(
    bond_events: list[dict],
    total_rewards_eth: float,
    current_bond_eth: float,
    steth_apr: float | None,
    historical_apr_data: list[dict] | None = None,
    distribution_flows: list[dict] | None = None,
    get_average_apr_for_range=None,
) -> dict:
    """Calculate capital efficiency metrics for a CSM operator.

    Args:
        bond_events: List of bond events from get_bond_event_history()
        total_rewards_eth: Total lifetime distributed rewards in ETH
        current_bond_eth: Current bond value in ETH
        steth_apr: Current stETH APR (percentage)
        historical_apr_data: Historical APR data for benchmark calculation
        distribution_flows: List of {date, amount_eth} for XIRR calculation
        get_average_apr_for_range: Function to get average APR for a time range

    Returns:
        Dict with capital efficiency fields (matching CapitalEfficiency model)
    """
    deposits = [e for e in bond_events if e["flow_direction"] == 1]
    if not deposits:
        return {}

    now = datetime.now(timezone.utc)

    # First deposit date
    first_deposit_ts = deposits[0].get("timestamp", "")
    if not first_deposit_ts:
        return {}
    try:
        first_deposit_dt = datetime.fromisoformat(first_deposit_ts)
    except (ValueError, TypeError):
        return {}

    total_days = (now - first_deposit_dt).total_seconds() / 86400
    if total_days < 1:
        return {}

    # Sum of all deposits
    total_capital_deployed = sum(e["amount_eth"] for e in deposits)
    if total_capital_deployed <= 0:
        return {}

    # Net deposits (deposits - claims - burns)
    net_deposits = sum(e["amount_eth"] * e["flow_direction"] for e in bond_events)

    # Bond appreciation = current bond value - net deposits
    bond_appreciation = current_bond_eth - net_deposits

    # Total CSM returns = reward distributions + bond appreciation
    total_csm_return = total_rewards_eth + bond_appreciation

    # Time-weighted average capital for annualization
    # For each deposit, calculate: amount * (days_since_deposit / total_days)
    time_weighted_capital = 0.0
    for dep in deposits:
        dep_ts = dep.get("timestamp", "")
        if not dep_ts:
            continue
        try:
            dep_dt = datetime.fromisoformat(dep_ts)
        except (ValueError, TypeError):
            continue
        days_deployed = (now - dep_dt).total_seconds() / 86400
        time_weighted_capital += dep["amount_eth"] * (days_deployed / total_days)

    if time_weighted_capital <= 0:
        time_weighted_capital = total_capital_deployed

    # Annualized CSM return
    csm_annualized = (total_csm_return / time_weighted_capital) * (365 / total_days) * 100

    # stETH benchmark: average historical APR over operating period
    steth_benchmark = None
    if historical_apr_data and get_average_apr_for_range:
        start_ts = int(first_deposit_dt.timestamp())
        end_ts = int(now.timestamp())
        avg_apr = get_average_apr_for_range(historical_apr_data, start_ts, end_ts)
        if avg_apr is not None:
            steth_benchmark = avg_apr
    if steth_benchmark is None and steth_apr is not None:
        steth_benchmark = steth_apr

    # Advantage ratio
    csm_advantage = None
    if steth_benchmark and steth_benchmark > 0:
        csm_advantage = round(csm_annualized / steth_benchmark, 2)

    # XIRR calculation
    xirr_pct = None
    if distribution_flows:
        cash_flows = _build_xirr_cash_flows(
            bond_events, distribution_flows, current_bond_eth
        )
        if cash_flows:
            xirr_pct = calculate_xirr(cash_flows)

    return {
        "total_csm_return_eth": round(total_csm_return, 6),
        "total_capital_deployed_eth": round(total_capital_deployed, 6),
        "csm_annualized_return_pct": round(csm_annualized, 2),
        "steth_benchmark_return_pct": round(steth_benchmark, 2) if steth_benchmark is not None else None,
        "csm_advantage_ratio": csm_advantage,
        "first_deposit_date": first_deposit_ts,
        "days_operating": round(total_days, 1),
        "xirr_pct": round(xirr_pct, 2) if xirr_pct is not None else None,
    }


def _build_xirr_cash_flows(
    bond_events: list[dict],
    distribution_flows: list[dict],
    current_bond_eth: float,
) -> list[tuple[datetime, float]]:
    """Build cash flow list for XIRR calculation.

    Bond deposits are negative (money in), reward distributions are positive (money out),
    and current bond value is a positive terminal value at today's date.
    """
    cash_flows = []

    # Bond deposits -> negative cash flows
    for e in bond_events:
        if e["flow_direction"] != 1:
            continue
        ts = e.get("timestamp", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            continue
        cash_flows.append((dt, -e["amount_eth"]))

    # Reward distributions -> positive cash flows
    for flow in distribution_flows:
        dt = flow.get("date")
        amount = flow.get("amount_eth", 0)
        if dt and amount > 0:
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt)
                except (ValueError, TypeError):
                    continue
            cash_flows.append((dt, amount))

    # Terminal value: current bond at today's date
    now = datetime.now(timezone.utc)
    if current_bond_eth > 0:
        cash_flows.append((now, current_bond_eth))

    # Need at least one negative and one positive flow
    has_negative = any(cf[1] < 0 for cf in cash_flows)
    has_positive = any(cf[1] > 0 for cf in cash_flows)
    if not (has_negative and has_positive):
        return []

    cash_flows.sort(key=lambda x: x[0])
    return cash_flows


def calculate_xirr(
    cash_flows: list[tuple[datetime, float]],
    guess: float = 0.1,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Calculate XIRR using Newton's method.

    Args:
        cash_flows: List of (date, amount) tuples. Negative = investment, positive = return.
        guess: Initial rate guess (0.1 = 10%)
        tol: Convergence tolerance
        max_iter: Maximum iterations

    Returns:
        XIRR as percentage (e.g., 8.5 for 8.5%), or None if doesn't converge
    """
    if not cash_flows or len(cash_flows) < 2:
        return None

    dates, amounts = zip(*cash_flows)
    d0 = dates[0]
    # Day fractions from first date
    day_fracs = [(d - d0).total_seconds() / (365.25 * 86400) for d in dates]

    rate = guess
    for _ in range(max_iter):
        # NPV and its derivative
        npv = 0.0
        dnpv = 0.0
        for amt, t in zip(amounts, day_fracs):
            denom = (1 + rate) ** t
            if denom == 0:
                return None
            npv += amt / denom
            if t != 0:
                dnpv -= t * amt / ((1 + rate) ** (t + 1))

        if abs(dnpv) < 1e-12:
            return None

        new_rate = rate - npv / dnpv

        # Clamp to avoid divergence
        if new_rate < -0.99:
            new_rate = -0.99
        if new_rate > 10:
            new_rate = 10

        if abs(new_rate - rate) < tol:
            return float(new_rate * 100)  # Convert to percentage

        rate = new_rate

    return None  # Did not converge
