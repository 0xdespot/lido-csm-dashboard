"""API endpoints for the web interface."""

from fastapi import APIRouter, HTTPException, Query

from ..services.operator_service import OperatorService

router = APIRouter()


@router.get("/operator/{identifier}")
async def get_operator(
    identifier: str,
    detailed: bool = Query(False, description="Include validator status from beacon chain"),
):
    """
    Get operator data by address or ID.

    - If identifier is numeric, treat as operator ID
    - If identifier starts with 0x, treat as Ethereum address
    - Add ?detailed=true to include validator status breakdown
    """
    service = OperatorService()

    # Determine if this is an ID or address
    if identifier.isdigit():
        operator_id = int(identifier)
        rewards = await service.get_operator_by_id(operator_id, detailed)
    elif identifier.startswith("0x"):
        rewards = await service.get_operator_by_address(identifier, detailed)
    else:
        raise HTTPException(status_code=400, detail="Invalid identifier format")

    if rewards is None:
        raise HTTPException(status_code=404, detail="Operator not found")

    result = {
        "operator_id": rewards.node_operator_id,
        "manager_address": rewards.manager_address,
        "reward_address": rewards.reward_address,
        "rewards": {
            "current_bond_eth": float(rewards.current_bond_eth),
            "required_bond_eth": float(rewards.required_bond_eth),
            "excess_bond_eth": float(rewards.excess_bond_eth),
            "cumulative_rewards_shares": rewards.cumulative_rewards_shares,
            "cumulative_rewards_eth": float(rewards.cumulative_rewards_eth),
            "distributed_shares": rewards.distributed_shares,
            "distributed_eth": float(rewards.distributed_eth),
            "unclaimed_shares": rewards.unclaimed_shares,
            "unclaimed_eth": float(rewards.unclaimed_eth),
            "total_claimable_eth": float(rewards.total_claimable_eth),
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
        result["apy"] = {
            "historical_reward_apy_28d": rewards.apy.historical_reward_apy_28d,
            "historical_reward_apy_ltd": rewards.apy.historical_reward_apy_ltd,
            "bond_apy": rewards.apy.bond_apy,
            "net_apy_28d": rewards.apy.net_apy_28d,
            "net_apy_ltd": rewards.apy.net_apy_ltd,
        }

    # Add active_since if available
    if rewards.active_since:
        result["active_since"] = rewards.active_since.isoformat()

    # Add health status if available
    if rewards.health:
        result["health"] = {
            "bond_healthy": rewards.health.bond_healthy,
            "bond_deficit_eth": float(rewards.health.bond_deficit_eth),
            "stuck_validators_count": rewards.health.stuck_validators_count,
            "slashed_validators_count": rewards.health.slashed_validators_count,
            "validators_at_risk_count": rewards.health.validators_at_risk_count,
            "strikes": {
                "total_validators_with_strikes": rewards.health.strikes.total_validators_with_strikes,
                "validators_at_risk": rewards.health.strikes.validators_at_risk,
                "validators_near_ejection": rewards.health.strikes.validators_near_ejection,
                "total_strikes": rewards.health.strikes.total_strikes,
                "max_strikes": rewards.health.strikes.max_strikes,
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

    strikes = await service.get_operator_strikes(operator_id)

    # Fetch frame dates for tooltip display
    frame_dates = await service.get_recent_frame_dates(6)

    return {
        "operator_id": operator_id,
        "frame_dates": frame_dates,
        "validators": [
            {
                "pubkey": s.pubkey,
                "strike_count": s.strike_count,
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
