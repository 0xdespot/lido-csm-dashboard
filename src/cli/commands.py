"""Typer CLI commands with Rich formatting."""

import asyncio
import json
import time
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..core.types import OperatorRewards
from ..services.operator_service import OperatorService

app = typer.Typer(
    name="csm",
    help="Lido CSM Operator Dashboard - Track your validator earnings",
)
console = Console()


def run_async(coro):
    """Helper to run async functions from sync CLI."""
    return asyncio.run(coro)


def format_as_api_json(rewards: OperatorRewards, include_validators: bool = False, include_withdrawals: bool = False) -> dict:
    """Format rewards data in the same structure as the API endpoint."""
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

    # Add beacon chain validator details if available
    if rewards.validators_by_status:
        result["validators"]["by_status"] = rewards.validators_by_status

    if rewards.avg_effectiveness is not None:
        result["performance"] = {
            "avg_effectiveness": round(rewards.avg_effectiveness, 2),
        }

    if include_validators and rewards.validator_details:
        result["validator_details"] = [v.to_dict() for v in rewards.validator_details]

    # Add APY metrics if available
    if rewards.apy:
        # Use actual excess bond for lifetime values (matches Web API)
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
        # Add frames if available (from --history flag)
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
                    "bond_apy": f.bond_apy,
                    "net_apy": f.net_apy,
                }
                for f in rewards.apy.frames
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
            },
            "has_issues": rewards.health.has_issues,
        }

    # Add withdrawal history if requested
    if include_withdrawals and rewards.withdrawals:
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

    return result


@app.command("rewards")
@app.command("check", hidden=True)
def rewards(
    address: Optional[str] = typer.Argument(
        None, help="Ethereum address (required unless --id is provided)"
    ),
    operator_id: Optional[int] = typer.Option(
        None, "--id", "-i", help="Operator ID (skip address lookup)"
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc", "-r", help="Custom RPC URL"
    ),
    output_json: bool = typer.Option(
        False, "--json", "-j", help="Output as JSON (same format as API)"
    ),
    detailed: bool = typer.Option(
        False, "--detailed", "-d", help="Include validator status from beacon chain"
    ),
    history: bool = typer.Option(
        False, "--history", "-H", help="Show all historical distribution frames"
    ),
    withdrawals: bool = typer.Option(
        False, "--withdrawals", "-w", help="Include withdrawal/claim history"
    ),
):
    """
    Check CSM operator rewards and earnings.

    Examples:
        csm rewards 0xYourAddress
        csm rewards 42
        csm rewards 0xYourAddress --json
        csm rewards 42 --detailed
        csm rewards 42 --history
        csm rewards 42 --withdrawals
    """
    if address is None and operator_id is None:
        console.print("[red]Error: Must provide either ADDRESS or --id[/red]")
        raise typer.Exit(1)

    # Parse numeric address as operator ID
    if address is not None and address.isdigit():
        operator_id = int(address)
        address = None

    service = OperatorService(rpc_url)

    if not output_json:
        console.print()
        status_msg = "[bold blue]Fetching operator data..."
        if detailed or history or withdrawals:
            status_msg = "[bold blue]Fetching operator data and validator status..."
        with console.status(status_msg):
            if operator_id is not None:
                rewards = run_async(service.get_operator_by_id(operator_id, detailed or history, history, withdrawals))
            else:
                console.print(f"[dim]Looking up operator for address: {address}[/dim]")
                rewards = run_async(service.get_operator_by_address(address, detailed or history, history, withdrawals))
    else:
        # JSON mode - no status output
        if operator_id is not None:
            rewards = run_async(service.get_operator_by_id(operator_id, detailed or history, history, withdrawals))
        else:
            rewards = run_async(service.get_operator_by_address(address, detailed or history, history, withdrawals))

    if rewards is None:
        if output_json:
            print(json.dumps({"error": "Operator not found"}, indent=2))
        else:
            console.print("[red]No CSM operator found for this address/ID[/red]")
        raise typer.Exit(1)

    # JSON output mode
    if output_json:
        print(json.dumps(format_as_api_json(rewards, detailed, withdrawals), indent=2))
        return

    # Header panel
    active_since_str = ""
    if rewards.active_since:
        active_since_str = f"Active Since: {rewards.active_since.strftime('%b %d, %Y')}"
    operator_type_str = f"Type: {rewards.operator_type}"
    console.print(
        Panel(
            f"[bold]CSM Operator #{rewards.node_operator_id}[/bold]\n"
            f"{active_since_str}  |  {operator_type_str}\n\n"
            f"Manager: {rewards.manager_address}\n"
            f"Rewards: {rewards.reward_address}",
            title="Operator Info",
        )
    )

    # Validators table
    val_table = Table(title="Validators", show_header=False)
    val_table.add_column("Metric", style="cyan")
    val_table.add_column("Value", style="green")
    val_table.add_row("Total Validators", str(rewards.total_validators))
    val_table.add_row("Active Validators", str(rewards.active_validators))
    val_table.add_row("Exited Validators", str(rewards.exited_validators))
    console.print(val_table)
    console.print()

    # Validator status breakdown (from beacon chain) - shown right after validators table
    if detailed and rewards.validators_by_status:
        status_table = Table(title="Validator Status (Beacon Chain)")
        status_table.add_column("Status", style="cyan")
        status_table.add_column("Count", style="green", justify="right")

        status_order = ["active", "pending", "exiting", "exited", "slashed", "unknown"]
        status_styles = {
            "active": "green",
            "pending": "yellow",
            "exiting": "yellow",
            "exited": "dim",
            "slashed": "red bold",
            "unknown": "dim",
        }

        for status in status_order:
            count = rewards.validators_by_status.get(status, 0)
            if count > 0:
                style = status_styles.get(status, "white")
                status_table.add_row(
                    status.capitalize(),
                    f"[{style}]{count}[/{style}]",
                )

        console.print(status_table)

        if rewards.avg_effectiveness is not None:
            console.print(
                f"\n[cyan]Average Attestation Effectiveness:[/cyan] "
                f"[bold green]{rewards.avg_effectiveness:.1f}%[/bold green]"
            )
        console.print()

    # Health Status - shown right after validator status
    if detailed and rewards.health:
        health_table = Table(title="Health Status")
        health_table.add_column("Check", style="cyan")
        health_table.add_column("Status", justify="right")

        # Bond health
        if rewards.health.bond_healthy:
            health_table.add_row("Bond", "[green]HEALTHY[/green]")
        else:
            health_table.add_row(
                "Bond",
                f"[red bold]DEFICIT -{rewards.health.bond_deficit_eth:.4f} ETH[/red bold]"
            )

        # Stuck validators
        if rewards.health.stuck_validators_count == 0:
            health_table.add_row("Stuck Validators", "[green]0[/green]")
        else:
            health_table.add_row(
                "Stuck Validators",
                f"[red bold]{rewards.health.stuck_validators_count}[/red bold] (exit within 4 days!)"
            )

        # Slashed validators
        if rewards.health.slashed_validators_count == 0:
            health_table.add_row("Slashed", "[green]0[/green]")
        else:
            health_table.add_row(
                "Slashed",
                f"[red bold]{rewards.health.slashed_validators_count}[/red bold] (est. 1-33 ETH penalty each)"
            )

        # At-risk validators (balance < 32 ETH)
        if rewards.health.validators_at_risk_count == 0:
            health_table.add_row("At Risk (<32 ETH)", "[green]0[/green]")
        else:
            health_table.add_row(
                "At Risk (<32 ETH)",
                f"[yellow]{rewards.health.validators_at_risk_count}[/yellow]"
            )

        # Strikes
        strikes = rewards.health.strikes
        if strikes.total_validators_with_strikes == 0:
            health_table.add_row("Performance Strikes", "[green]0/3[/green]")
        else:
            # Build strike status message
            strike_parts = []
            if strikes.validators_at_risk > 0:
                strike_parts.append(f"{strikes.validators_at_risk} at ejection")
            if strikes.validators_near_ejection > 0:
                strike_parts.append(f"{strikes.validators_near_ejection} near ejection")

            strike_status = ", ".join(strike_parts) if strike_parts else "monitoring"
            strike_style = "red bold" if strikes.validators_at_risk > 0 else (
                "bright_yellow" if strikes.validators_near_ejection > 0 else "yellow"
            )
            health_table.add_row(
                "Performance Strikes",
                f"[{strike_style}]{strikes.total_validators_with_strikes} validators[/{strike_style}] "
                f"({strike_status})"
            )

        console.print(health_table)

        # Overall status - color-coded by severity
        if not rewards.health.has_issues:
            console.print("\n[bold green]Overall: No issues detected[/bold green]")
        elif (
            not rewards.health.bond_healthy
            or rewards.health.stuck_validators_count > 0
            or rewards.health.slashed_validators_count > 0
            or rewards.health.validators_at_risk_count > 0
            or strikes.max_strikes >= 3
        ):
            # Critical issues (red)
            console.print("\n[bold red]Overall: Issues detected - review above[/bold red]")
        elif strikes.max_strikes == 2:
            # Warning level 2 (orange/bright yellow)
            console.print("\n[bold bright_yellow]Overall: Warning - 2 strikes detected[/bold bright_yellow]")
        else:
            # Warning level 1 (yellow)
            console.print("\n[bold yellow]Overall: Warning - strikes detected[/bold yellow]")
        console.print()

    # Rewards table
    rewards_table = Table(title="Earnings Summary")
    rewards_table.add_column("Metric", style="cyan")
    rewards_table.add_column("Value", style="green")
    rewards_table.add_column("Notes", style="dim")

    rewards_table.add_row(
        "Current Bond",
        f"{rewards.current_bond_eth:.6f} ETH",
        f"Required: {rewards.required_bond_eth:.6f} ETH",
    )
    rewards_table.add_row(
        "Excess Bond",
        f"[bold green]{rewards.excess_bond_eth:.6f} ETH[/bold green]",
        "Claimable",
    )
    rewards_table.add_row("", "", "")
    rewards_table.add_row(
        "Cumulative Rewards",
        f"{rewards.cumulative_rewards_eth:.6f} ETH",
        f"({rewards.cumulative_rewards_shares:,} shares)" if detailed else "All-time total",
    )
    rewards_table.add_row(
        "Already Distributed",
        f"{rewards.distributed_eth:.6f} ETH",
        f"({rewards.distributed_shares:,} shares)" if detailed else "",
    )
    rewards_table.add_row(
        "Unclaimed Rewards",
        f"[bold green]{rewards.unclaimed_eth:.6f} ETH[/bold green]",
        f"({rewards.unclaimed_shares:,} shares)" if detailed else "",
    )
    rewards_table.add_row("", "", "")
    rewards_table.add_row(
        "[bold]TOTAL CLAIMABLE[/bold]",
        f"[bold yellow]{rewards.total_claimable_eth:.6f} ETH[/bold yellow]",
        "Excess bond + unclaimed rewards",
    )

    console.print(rewards_table)
    console.print()

    # APY Metrics table (only shown with --detailed or --history flag)
    if (detailed or history) and rewards.apy:
        def fmt_apy(val: float | None) -> str:
            return f"{val:.2f}%" if val is not None else "--"

        def fmt_eth(val: float | None) -> str:
            return f"{val:.4f}" if val is not None else "--"

        # Determine which columns to show
        # --detailed only: Current column only
        # --history: Previous, Current, and Lifetime columns
        show_all_columns = history

        if show_all_columns:
            # Full table with 3 columns (Previous, Current, Lifetime)
            apy_table = Table(title="APY Metrics")
            apy_table.add_column("Metric", style="cyan")
            apy_table.add_column("Previous", style="green", justify="right")
            apy_table.add_column("Current", style="green", justify="right")
            apy_table.add_column("Lifetime", style="green", justify="right")

            # Use accurate lifetime APY when available (per-frame bond calculation)
            lifetime_reward_apy = rewards.apy.lifetime_reward_apy or rewards.apy.historical_reward_apy_ltd
            lifetime_bond_apy = rewards.apy.lifetime_bond_apy or rewards.apy.bond_apy
            lifetime_net_apy = rewards.apy.lifetime_net_apy or rewards.apy.net_apy_ltd

            apy_table.add_row(
                "Reward APY",
                fmt_apy(rewards.apy.previous_distribution_apy),
                fmt_apy(rewards.apy.current_distribution_apy),
                fmt_apy(lifetime_reward_apy),
            )
            # Show historical APR for Previous/Current if available, otherwise current APR
            prev_bond_apr = rewards.apy.previous_bond_apr or rewards.apy.bond_apy
            curr_bond_apr = rewards.apy.current_bond_apr or rewards.apy.bond_apy
            bond_label = "Bond APY (stETH)"
            apy_table.add_row(
                bond_label,
                fmt_apy(prev_bond_apr),
                fmt_apy(curr_bond_apr),
                fmt_apy(lifetime_bond_apy),
            )
            apy_table.add_row(
                "[bold]NET APY[/bold]",
                f"[bold yellow]{fmt_apy(rewards.apy.previous_net_apy)}[/bold yellow]",
                f"[bold yellow]{fmt_apy(rewards.apy.net_apy_28d)}[/bold yellow]",
                f"[bold yellow]{fmt_apy(lifetime_net_apy)}[/bold yellow]",
            )
            apy_table.add_row("─" * 15, "─" * 10, "─" * 10, "─" * 10)
            apy_table.add_row(
                "Rewards (stETH)",
                fmt_eth(rewards.apy.previous_distribution_eth),
                fmt_eth(rewards.apy.current_distribution_eth),
                fmt_eth(rewards.apy.lifetime_distribution_eth),
            )
            # All columns show estimated bond stETH rebasing earnings (consistent metric)
            apy_table.add_row(
                "Bond (stETH)*",
                fmt_eth(rewards.apy.previous_bond_eth),
                fmt_eth(rewards.apy.current_bond_eth),
                fmt_eth(rewards.apy.lifetime_bond_eth),
            )
            # All columns show sum of Rewards + Bond (consistent metric)
            apy_table.add_row(
                "[bold]Net Total (stETH)[/bold]",
                f"[bold]{fmt_eth(rewards.apy.previous_net_total_eth)}[/bold]",
                f"[bold]{fmt_eth(rewards.apy.current_net_total_eth)}[/bold]",
                f"[bold]{fmt_eth(rewards.apy.lifetime_net_total_eth)}[/bold]",
            )

            console.print(apy_table)
            # Show footnote about per-frame bond calculation
            console.print("[dim]*Previous/Current use per-frame validator count for bond calculations[/dim]")
        else:
            # Single column (Current only) for --detailed without --history
            apy_table = Table(title="APY Metrics (Current Frame)")
            apy_table.add_column("Metric", style="cyan")
            apy_table.add_column("Current", style="green", justify="right")

            apy_table.add_row(
                "Reward APY",
                fmt_apy(rewards.apy.current_distribution_apy),
            )
            curr_bond_apr = rewards.apy.current_bond_apr or rewards.apy.bond_apy
            apy_table.add_row(
                "Bond APY (stETH)",
                fmt_apy(curr_bond_apr),
            )
            apy_table.add_row(
                "[bold]NET APY[/bold]",
                f"[bold yellow]{fmt_apy(rewards.apy.net_apy_28d)}[/bold yellow]",
            )
            apy_table.add_row("─" * 15, "─" * 10)
            apy_table.add_row(
                "Rewards (stETH)",
                fmt_eth(rewards.apy.current_distribution_eth),
            )
            apy_table.add_row(
                "Bond (stETH)*",
                fmt_eth(rewards.apy.current_bond_eth),
            )
            apy_table.add_row(
                "[bold]Net Total (stETH)[/bold]",
                f"[bold]{fmt_eth(rewards.apy.current_net_total_eth)}[/bold]",
            )

            console.print(apy_table)
            # Show appropriate footer based on whether historical APR was used
            if rewards.apy.uses_historical_apr:
                console.print("[dim]*Bond (stETH) is estimated from current bond and historical APR[/dim]")
            else:
                console.print("[dim]*Bond (stETH) is estimated from current bond and APR[/dim]")

        # Show next distribution estimate
        if rewards.apy.next_distribution_date:
            from datetime import datetime
            try:
                next_dt = datetime.fromisoformat(rewards.apy.next_distribution_date)
                next_date_str = next_dt.strftime("%b %d, %Y")
                est_eth = rewards.apy.next_distribution_est_eth
                if est_eth:
                    console.print(f"\n[cyan]Next Distribution:[/cyan] ~{next_date_str} (est. {est_eth:.4f} ETH)")
                else:
                    console.print(f"\n[cyan]Next Distribution:[/cyan] ~{next_date_str}")
            except (ValueError, TypeError):
                pass
        console.print()

        # Show full distribution history if --history flag is used
        if history and rewards.apy.frames:
            from datetime import datetime
            history_table = Table(title="Distribution History")
            history_table.add_column("#", style="cyan", justify="right")
            history_table.add_column("Distribution Date", style="white")
            history_table.add_column("Rewards (ETH)", style="green", justify="right")
            history_table.add_column("Vals", style="dim", justify="right")
            history_table.add_column("ETH/Val", style="green", justify="right")
            history_table.add_column("Reward APY", style="green", justify="right")
            history_table.add_column("Bond APY", style="green", justify="right")
            history_table.add_column("Net APY", style="bold yellow", justify="right")

            # Display oldest first (chronological order)
            for frame in rewards.apy.frames:
                try:
                    end_dt = datetime.fromisoformat(frame.end_date)
                    dist_date = end_dt.strftime("%b %d, %Y")
                except (ValueError, TypeError):
                    dist_date = frame.end_date

                # Calculate ETH per validator
                eth_per_val = frame.rewards_eth / frame.validator_count if frame.validator_count > 0 else 0

                history_table.add_row(
                    str(frame.frame_number),
                    dist_date,
                    f"{frame.rewards_eth:.4f}",
                    str(frame.validator_count),
                    f"{eth_per_val:.6f}",
                    fmt_apy(frame.apy),
                    fmt_apy(frame.bond_apy),
                    fmt_apy(frame.net_apy),
                )

            console.print(history_table)
            console.print()

    # Show withdrawal history if --withdrawals flag is used
    if withdrawals and rewards.withdrawals:
        from datetime import datetime
        withdrawal_table = Table(title="Withdrawal History")
        withdrawal_table.add_column("#", style="cyan", justify="right")
        withdrawal_table.add_column("Date", style="white")
        withdrawal_table.add_column("Type", style="magenta")
        withdrawal_table.add_column("Amount", style="green", justify="right")
        withdrawal_table.add_column("Status", style="yellow")
        withdrawal_table.add_column("Tx Hash", style="dim")

        for i, w in enumerate(rewards.withdrawals, 1):
            try:
                w_dt = datetime.fromisoformat(w.timestamp)
                w_date = w_dt.strftime("%b %d, %Y")
            except (ValueError, TypeError):
                w_date = w.timestamp[:10] if w.timestamp else "--"

            # Determine display values based on type
            withdrawal_type = w.withdrawal_type if w.withdrawal_type else "stETH"

            # For unstETH, show claimed ETH if available, otherwise requested stETH
            if withdrawal_type == "unstETH" and w.claimed_eth is not None:
                amount_str = f"{w.claimed_eth:.4f} ETH"
            else:
                amount_str = f"{w.eth_value:.4f} stETH"

            # Status column for unstETH
            if withdrawal_type == "unstETH" and w.status:
                status_colors = {
                    "pending": "[yellow]Pending[/yellow]",
                    "finalized": "[blue]Ready[/blue]",
                    "claimed": "[green]Claimed[/green]",
                    "unknown": "[dim]Unknown[/dim]",
                }
                status_str = status_colors.get(w.status, w.status)
            elif withdrawal_type != "unstETH":
                status_str = "[green]Claimed[/green]"
            else:
                status_str = "--"

            withdrawal_table.add_row(
                str(i),
                w_date,
                withdrawal_type,
                amount_str,
                status_str,
                f"{w.tx_hash[:10]}..." if w.tx_hash else "--",
            )

        console.print(withdrawal_table)

        # Show totals
        steth_total = sum(
            w.eth_value for w in rewards.withdrawals
            if w.withdrawal_type != "unstETH"
        )
        unsteth_claimed_total = sum(
            w.claimed_eth for w in rewards.withdrawals
            if w.withdrawal_type == "unstETH" and w.claimed_eth is not None
        )
        if steth_total > 0 or unsteth_claimed_total > 0:
            total_parts = []
            if steth_total > 0:
                total_parts.append(f"{steth_total:.4f} stETH")
            if unsteth_claimed_total > 0:
                total_parts.append(f"{unsteth_claimed_total:.4f} ETH")
            console.print(f"[bold]Total claimed:[/bold] {' + '.join(total_parts)}")
        console.print()

        # Show pending unstETH summary if any
        pending_unsteth = [
            w for w in rewards.withdrawals
            if w.withdrawal_type == "unstETH"
            and w.status in ("pending", "finalized")
        ]
        if pending_unsteth:
            pending_total = sum(w.eth_value for w in pending_unsteth)
            ready_count = sum(1 for w in pending_unsteth if w.status == "finalized")
            console.print(
                f"[yellow]Note: {len(pending_unsteth)} unstETH request(s) "
                f"({ready_count} ready to claim) totaling ~{pending_total:.4f} stETH[/yellow]"
            )
            console.print()


@app.command()
def health(
    address: Optional[str] = typer.Argument(
        None, help="Ethereum address (required unless --id is provided)"
    ),
    operator_id: Optional[int] = typer.Option(
        None, "--id", "-i", help="Operator ID (skip address lookup)"
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc", "-r", help="Custom RPC URL"
    ),
    output_json: bool = typer.Option(
        False, "--json", "-j", help="Output as JSON"
    ),
):
    """
    Check CSM operator health status - penalties, strikes, and risks.

    Examples:
        csm health 0xYourAddress
        csm health 42
        csm health --id 42 --json
    """
    if address is None and operator_id is None:
        console.print("[red]Error: Must provide either ADDRESS or --id[/red]")
        raise typer.Exit(1)

    # Parse numeric address as operator ID
    if address is not None and address.isdigit():
        operator_id = int(address)
        address = None

    service = OperatorService(rpc_url)

    if not output_json:
        console.print()
        with console.status("[bold blue]Fetching operator health status..."):
            if operator_id is not None:
                rewards = run_async(service.get_operator_by_id(operator_id, True))
            else:
                console.print(f"[dim]Looking up operator for address: {address}[/dim]")
                rewards = run_async(service.get_operator_by_address(address, True))
    else:
        if operator_id is not None:
            rewards = run_async(service.get_operator_by_id(operator_id, True))
        else:
            rewards = run_async(service.get_operator_by_address(address, True))

    if rewards is None:
        if output_json:
            print(json.dumps({"error": "Operator not found"}, indent=2))
        else:
            console.print("[red]No CSM operator found for this address/ID[/red]")
        raise typer.Exit(1)

    # JSON output
    if output_json:
        result = {"operator_id": rewards.node_operator_id}
        if rewards.health:
            # Fetch validator strikes details
            validator_strikes = []
            if rewards.health.strikes.total_validators_with_strikes > 0:
                strikes_data = run_async(service.get_operator_strikes(rewards.node_operator_id, rewards.curve_id))
                validator_strikes = [
                    {
                        "pubkey": vs.pubkey,
                        "strike_count": vs.strike_count,
                        "strike_threshold": vs.strike_threshold,
                        "at_ejection_risk": vs.at_ejection_risk,
                    }
                    for vs in strikes_data
                ]

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
                    "validators": validator_strikes,
                },
                "has_issues": rewards.health.has_issues,
            }
        print(json.dumps(result, indent=2))
        return

    # Rich output
    console.print(
        Panel(
            f"[bold]CSM Operator #{rewards.node_operator_id} Health Status[/bold]",
            title="Health Check",
        )
    )

    if not rewards.health:
        console.print("[yellow]Health status not available[/yellow]")
        return

    health = rewards.health

    # Build health status panel content
    lines = []

    # Bond status
    if health.bond_healthy:
        lines.append(f"Bond:           [green]HEALTHY[/green] (excess: {rewards.excess_bond_eth:.4f} ETH)")
    else:
        lines.append(f"Bond:           [red bold]DEFICIT -{health.bond_deficit_eth:.4f} ETH[/red bold]")

    # Stuck validators
    if health.stuck_validators_count == 0:
        lines.append("Stuck:          [green]0 validators[/green]")
    else:
        lines.append(f"Stuck:          [red bold]{health.stuck_validators_count} validators[/red bold] (exit within 4 days!)")

    # Slashed
    if health.slashed_validators_count == 0:
        lines.append("Slashed:        [green]0 validators[/green]")
    else:
        lines.append(f"Slashed:        [red bold]{health.slashed_validators_count} validators[/red bold]")

    # At risk
    if health.validators_at_risk_count == 0:
        lines.append("At Risk:        [green]0 validators[/green] (<32 ETH balance)")
    else:
        lines.append(f"At Risk:        [yellow]{health.validators_at_risk_count} validators[/yellow] (<32 ETH balance)")

    # Strikes
    strikes = health.strikes
    if strikes.total_validators_with_strikes == 0:
        lines.append("Strikes:        [green]0 validators[/green]")
    else:
        # Build strike status message
        strike_parts = []
        if strikes.validators_at_risk > 0:
            strike_parts.append(f"{strikes.validators_at_risk} at ejection")
        if strikes.validators_near_ejection > 0:
            strike_parts.append(f"{strikes.validators_near_ejection} near ejection")

        strike_status = ", ".join(strike_parts) if strike_parts else "monitoring"
        strike_style = "red bold" if strikes.validators_at_risk > 0 else (
            "bright_yellow" if strikes.validators_near_ejection > 0 else "yellow"
        )
        lines.append(
            f"Strikes:        [{strike_style}]{strikes.total_validators_with_strikes} validators[/{strike_style}] "
            f"({strike_status})"
        )

    lines.append("")

    # Overall status - color-coded by severity
    if not health.has_issues:
        lines.append("[bold green]Overall:        No issues detected[/bold green]")
    elif (
        not health.bond_healthy
        or health.stuck_validators_count > 0
        or health.slashed_validators_count > 0
        or health.validators_at_risk_count > 0
        or strikes.max_strikes >= 3
    ):
        # Critical issues (red)
        lines.append("[bold red]Overall:        Issues detected - action required![/bold red]")
    elif strikes.max_strikes == 2:
        # Warning level 2 (orange/bright yellow)
        lines.append("[bold bright_yellow]Overall:        Warning - 2 strikes detected[/bold bright_yellow]")
    else:
        # Warning level 1 (yellow)
        lines.append("[bold yellow]Overall:        Warning - strikes detected[/bold yellow]")

    console.print(Panel("\n".join(lines), title="Status"))

    # Show detailed strikes if any
    if strikes.total_validators_with_strikes > 0:
        console.print()
        console.print("[bold]Validator Strikes Detail:[/bold]")
        validator_strikes = run_async(service.get_operator_strikes(rewards.node_operator_id, rewards.curve_id))
        for vs in validator_strikes:
            strike_display = f"{vs.strike_count}/{vs.strike_threshold}"
            if vs.at_ejection_risk:
                console.print(f"  {vs.pubkey}: [red bold]{strike_display}[/red bold] (EJECTION RISK!)")
            elif vs.strike_count > 0:
                console.print(f"  {vs.pubkey}: [yellow]{strike_display}[/yellow]")
            else:
                console.print(f"  {vs.pubkey}: [green]{strike_display}[/green]")


@app.command()
def watch(
    address: str = typer.Argument(..., help="Ethereum address to monitor"),
    interval: int = typer.Option(
        300, "--interval", "-i", help="Refresh interval in seconds"
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc", "-r", help="Custom RPC URL"
    ),
):
    """
    Continuously monitor rewards with live updates.
    Press Ctrl+C to stop.
    """
    try:
        while True:
            console.clear()
            try:
                rewards(address, rpc_url=rpc_url)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
            console.print(
                f"\n[dim]Refreshing every {interval} seconds... Press Ctrl+C to stop[/dim]"
            )
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch stopped.[/yellow]")


@app.command(name="list")
def list_operators(
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc", "-r", help="Custom RPC URL"
    ),
):
    """List all operators with rewards in the current tree."""
    service = OperatorService(rpc_url)

    with console.status("[bold blue]Fetching rewards tree..."):
        operator_ids = run_async(service.get_all_operators_with_rewards())

    console.print(f"\n[bold]Found {len(operator_ids)} operators with rewards:[/bold]")
    console.print(", ".join(str(op_id) for op_id in operator_ids))


if __name__ == "__main__":
    app()
