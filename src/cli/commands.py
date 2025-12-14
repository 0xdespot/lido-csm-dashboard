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
    return asyncio.get_event_loop().run_until_complete(coro)


def format_as_api_json(rewards: OperatorRewards, include_validators: bool = False) -> dict:
    """Format rewards data in the same structure as the API endpoint."""
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

    return result


@app.command()
def check(
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
):
    """
    Check CSM operator rewards and earnings.

    Examples:
        csm check 0xYourAddress
        csm check --id 42
        csm check 0xYourAddress --json
        csm check --id 42 --detailed
    """
    if address is None and operator_id is None:
        console.print("[red]Error: Must provide either ADDRESS or --id[/red]")
        raise typer.Exit(1)

    service = OperatorService(rpc_url)

    if not output_json:
        console.print()
        status_msg = "[bold blue]Fetching operator data..."
        if detailed:
            status_msg = "[bold blue]Fetching operator data and validator status..."
        with console.status(status_msg):
            if operator_id is not None:
                rewards = run_async(service.get_operator_by_id(operator_id, detailed))
            else:
                console.print(f"[dim]Looking up operator for address: {address}[/dim]")
                rewards = run_async(service.get_operator_by_address(address, detailed))
    else:
        # JSON mode - no status output
        if operator_id is not None:
            rewards = run_async(service.get_operator_by_id(operator_id, detailed))
        else:
            rewards = run_async(service.get_operator_by_address(address, detailed))

    if rewards is None:
        if output_json:
            print(json.dumps({"error": "Operator not found"}, indent=2))
        else:
            console.print("[red]No CSM operator found for this address/ID[/red]")
        raise typer.Exit(1)

    # JSON output mode
    if output_json:
        print(json.dumps(format_as_api_json(rewards, detailed), indent=2))
        return

    # Header panel
    active_since_str = ""
    if rewards.active_since:
        active_since_str = f"Active Since: {rewards.active_since.strftime('%b %d, %Y')}"
    console.print(
        Panel(
            f"[bold]CSM Operator #{rewards.node_operator_id}[/bold]\n"
            f"{active_since_str}\n\n"
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

    # Validator status breakdown (from beacon chain)
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

    # APY Metrics table (only shown with --detailed flag)
    if detailed and rewards.apy:
        apy_table = Table(title="APY Metrics (Historical)")
        apy_table.add_column("Metric", style="cyan")
        apy_table.add_column("28-Day", style="green", justify="right")
        apy_table.add_column("Lifetime", style="green", justify="right")

        def fmt_apy(val: float | None) -> str:
            return f"{val:.2f}%" if val is not None else "--"

        apy_table.add_row(
            "Reward APY",
            fmt_apy(rewards.apy.historical_reward_apy_28d),
            fmt_apy(rewards.apy.historical_reward_apy_ltd),
        )
        apy_table.add_row(
            "Bond APY (stETH)*",
            fmt_apy(rewards.apy.bond_apy),
            fmt_apy(rewards.apy.bond_apy),
        )
        apy_table.add_row("", "", "")
        apy_table.add_row(
            "[bold]NET APY[/bold]",
            f"[bold yellow]{fmt_apy(rewards.apy.net_apy_28d)}[/bold yellow]",
            f"[bold yellow]{fmt_apy(rewards.apy.net_apy_ltd)}[/bold yellow]",
        )

        console.print(apy_table)
        console.print("[dim]*Bond APY uses current stETH rate[/dim]")
        console.print()


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
    while True:
        console.clear()
        check(address, rpc_url=rpc_url)
        console.print(
            f"\n[dim]Refreshing every {interval} seconds... Press Ctrl+C to stop[/dim]"
        )
        time.sleep(interval)


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
