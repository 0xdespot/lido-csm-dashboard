"""API endpoints for the web interface."""

from fastapi import APIRouter, HTTPException, Query

from ..services.operator_service import OperatorService

router = APIRouter()


@router.get("/operator/{identifier}")
async def get_operator(
    identifier: str,
    detailed: bool = Query(False, description="Include validator status from beacon chain"),
    history: bool = Query(False, description="Include all historical distribution frames"),
    withdrawals: bool = Query(False, description="Include withdrawal/claim history"),
):
    """
    Get operator data by address or ID.

    - If identifier is numeric, treat as operator ID
    - If identifier starts with 0x, treat as Ethereum address
    - Add ?detailed=true to include validator status breakdown
    - Add ?history=true to include all historical distribution frames
    - Add ?withdrawals=true to include withdrawal/claim history
    """
    service = OperatorService()

    # Determine if this is an ID or address
    if identifier.isdigit():
        operator_id = int(identifier)
        if operator_id < 0 or operator_id > 1_000_000:
            raise HTTPException(status_code=400, detail="Invalid operator ID")
        rewards = await service.get_operator_by_id(operator_id, detailed or history, history, withdrawals)
    elif identifier.startswith("0x"):
        rewards = await service.get_operator_by_address(identifier, detailed or history, history, withdrawals)
    else:
        raise HTTPException(status_code=400, detail="Invalid identifier format")

    if rewards is None:
        raise HTTPException(status_code=404, detail="Operator not found")

    result = {
        "operator_id": rewards.node_operator_id,
        "manager_address": rewards.manager_address,
        "reward_address": rewards.reward_address,
        "curve_id": rewards.curve_id,
        "operator_type": rewards.operator_type,
        "rewards": {
            "current_bond_eth": str(rewards.current_bond_eth),
            "required_bond_eth": str(rewards.required_bond_eth),
            "excess_bond_eth": str(rewards.excess_bond_eth),
            "cumulative_rewards_shares": rewards.cumulative_rewards_shares,
            "cumulative_rewards_eth": str(rewards.cumulative_rewards_eth),
            "distributed_shares": rewards.distributed_shares,
            "distributed_eth": str(rewards.distributed_eth),
            "unclaimed_shares": rewards.unclaimed_shares,
            "unclaimed_eth": str(rewards.unclaimed_eth),
            "total_claimable_eth": str(rewards.total_claimable_eth),
        },
        "validators": {
            "total": rewards.total_validators,
            "active": rewards.active_validators,
            "exited": rewards.exited_validators,
        },
    }

    # Fetch active_since for basic (non-detailed) requests
    # For detailed requests, it's already included in rewards.active_since
    if not detailed and rewards.total_validators > 0:
        active_since = await service.get_operator_active_since(rewards.node_operator_id)
        if active_since:
            result["active_since"] = active_since.isoformat()

    # Add beacon chain validator details if available
    if rewards.validators_by_status:
        result["validators"]["by_status"] = rewards.validators_by_status

    if rewards.avg_effectiveness is not None:
        result["performance"] = {
            "avg_effectiveness": round(rewards.avg_effectiveness, 2),
        }

    if detailed and rewards.validator_details:
        result["validator_details"] = [v.to_dict() for v in rewards.validator_details]

    # Add APY metrics if available
    if rewards.apy:
        # Use actual excess bond for lifetime values (estimates for previous/current)
        lifetime_bond = float(rewards.excess_bond_eth)
        lifetime_net_total = (rewards.apy.lifetime_distribution_eth or 0) + lifetime_bond
        result["apy"] = {
            "previous_distribution_eth": rewards.apy.previous_distribution_eth,
            "previous_distribution_apy": rewards.apy.previous_distribution_apy,
            "previous_net_apy": rewards.apy.previous_net_apy,
            "previous_bond_eth": rewards.apy.previous_bond_eth,
            "previous_bond_apr": rewards.apy.previous_bond_apr,
            "previous_net_total_eth": rewards.apy.previous_net_total_eth,
            "current_distribution_eth": rewards.apy.current_distribution_eth,
            "current_distribution_apy": rewards.apy.current_distribution_apy,
            "current_bond_eth": rewards.apy.current_bond_eth,
            "current_bond_apr": rewards.apy.current_bond_apr,
            "current_net_total_eth": rewards.apy.current_net_total_eth,
            "lifetime_distribution_eth": rewards.apy.lifetime_distribution_eth,
            "lifetime_bond_eth": lifetime_bond,  # Actual excess bond, not estimate
            "lifetime_net_total_eth": lifetime_net_total,  # Matches Total Claimable
            # Accurate lifetime APY (per-frame bond calculation when available)
            "lifetime_reward_apy": rewards.apy.lifetime_reward_apy,
            "lifetime_bond_apy": rewards.apy.lifetime_bond_apy,
            "lifetime_net_apy": rewards.apy.lifetime_net_apy,
            "next_distribution_date": rewards.apy.next_distribution_date,
            "next_distribution_est_eth": rewards.apy.next_distribution_est_eth,
            "historical_reward_apy_28d": rewards.apy.historical_reward_apy_28d,
            "historical_reward_apy_ltd": rewards.apy.historical_reward_apy_ltd,
            "bond_apy": rewards.apy.bond_apy,
            "net_apy_28d": rewards.apy.net_apy_28d,
            "net_apy_ltd": rewards.apy.net_apy_ltd,
            "uses_historical_apr": rewards.apy.uses_historical_apr,
        }
        # Add frames if available (from history=true)
        if rewards.apy.frames:
            result["apy"]["frames"] = [
                {
                    "frame_number": f.frame_number,
                    "start_date": f.start_date,
                    "end_date": f.end_date,
                    "rewards_eth": f.rewards_eth,
                    "rewards_shares": f.rewards_shares,
                    "duration_days": f.duration_days,
                    "validator_count": f.validator_count,
                    "apy": f.apy,
                }
                for f in rewards.apy.frames
            ]

    # Add withdrawal history if withdrawals=true (already fetched during data gathering)
    if withdrawals and rewards.withdrawals:
        result["withdrawals"] = [
            {
                "block_number": w.block_number,
                "timestamp": w.timestamp,
                "shares": w.shares,
                "eth_value": w.eth_value,
                "tx_hash": w.tx_hash,
            }
            for w in rewards.withdrawals
        ]

    # Add active_since if available
    if rewards.active_since:
        result["active_since"] = rewards.active_since.isoformat()

    # Add health status if available
    if rewards.health:
        result["health"] = {
            "bond_healthy": rewards.health.bond_healthy,
            "bond_deficit_eth": str(rewards.health.bond_deficit_eth),
            "stuck_validators_count": rewards.health.stuck_validators_count,
            "slashed_validators_count": rewards.health.slashed_validators_count,
            "validators_at_risk_count": rewards.health.validators_at_risk_count,
            "strikes": {
                "total_validators_with_strikes": rewards.health.strikes.total_validators_with_strikes,
                "validators_at_risk": rewards.health.strikes.validators_at_risk,
                "validators_near_ejection": rewards.health.strikes.validators_near_ejection,
                "total_strikes": rewards.health.strikes.total_strikes,
                "max_strikes": rewards.health.strikes.max_strikes,
                "strike_threshold": rewards.health.strikes.strike_threshold,
            },
            "has_issues": rewards.health.has_issues,
        }

    return result


@router.get("/operators")
async def list_operators():
    """List all operators with rewards in the current tree."""
    service = OperatorService()
    operator_ids = await service.get_all_operators_with_rewards()
    return {"count": len(operator_ids), "operator_ids": operator_ids}


@router.get("/operator/{identifier}/strikes")
async def get_operator_strikes(identifier: str):
    """Get detailed strikes for an operator's validators."""
    service = OperatorService()

    # Determine if this is an ID or address
    if identifier.isdigit():
        operator_id = int(identifier)
    elif identifier.startswith("0x"):
        operator_id = await service.onchain.find_operator_by_address(identifier)
        if operator_id is None:
            raise HTTPException(status_code=404, detail="Operator not found")
    else:
        raise HTTPException(status_code=400, detail="Invalid identifier format")

    # Get curve_id to determine strike threshold
    curve_id = await service.onchain.get_bond_curve_id(operator_id)
    strikes = await service.get_operator_strikes(operator_id, curve_id)

    # Fetch frame dates for tooltip display
    frame_dates = await service.get_recent_frame_dates(6)

    # Get the threshold for this operator type
    strike_threshold = strikes[0].strike_threshold if strikes else 3

    return {
        "operator_id": operator_id,
        "strike_threshold": strike_threshold,
        "frame_dates": frame_dates,
        "validators": [
            {
                "pubkey": s.pubkey,
                "strike_count": s.strike_count,
                "strike_threshold": s.strike_threshold,
                "strikes": s.strikes,
                "at_ejection_risk": s.at_ejection_risk,
            }
            for s in strikes
        ],
    }


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
