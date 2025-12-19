# Lido CSM Operator Dashboard

Track your Lido Community Staking Module (CSM) validator earnings, excess bond, and cumulative rewards.

![CLI Output](img/csm-dash-cli.png)

![Web Dashboard](img/csm-dash-web.png)

## Features

- Look up operator by Ethereum address (manager or rewards address) or operator ID
- View current bond vs required bond (excess is claimable)
- Track cumulative rewards and unclaimed amounts
- Detailed validator status from beacon chain (with `--detailed` flag)
- APY metrics: reward APY, bond APY (stETH rebase), and net APY
- JSON output for scripting and automation
- CLI for quick terminal lookups
- Web interface for browser-based monitoring

## Installation

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone <repo-url>
cd lido-csm-dashboard

# Copy and configure environment
cp .env.example .env

# Start the web dashboard
docker compose up -d

# View logs
docker compose logs -f
```

The web dashboard will be available at http://localhost:3000

### Option 2: Local Python Installation

```bash
# Clone the repository
git clone <repo-url>
cd lido-csm-dashboard

# Install with pip
pip install -e .

# Or with uv
uv pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Available settings:
- `ETH_RPC_URL`: Ethereum RPC endpoint (default: https://eth.llamarpc.com)
- `BEACON_API_URL`: Beacon chain API (default: https://beaconcha.in/api/v1)
- `BEACON_API_KEY`: Optional API key for beaconcha.in (higher rate limits)
- `ETHERSCAN_API_KEY`: Optional API key for Etherscan (recommended for accurate historical data)
- `CACHE_TTL_SECONDS`: Cache duration in seconds (default: 300)

## Usage

### Docker Usage

The web dashboard runs automatically when you start the container. You can also use CLI commands inside the container:

```bash
# Check operator rewards
docker compose exec csm-dashboard csm rewards 0xYourAddress

# Check by operator ID
docker compose exec csm-dashboard csm rewards --id 42

# Get detailed info with APY metrics
docker compose exec csm-dashboard csm rewards --id 42 --detailed

# JSON output
docker compose exec csm-dashboard csm rewards --id 42 --json

# List all operators
docker compose exec csm-dashboard csm list

# Monitor continuously (refresh every 60 seconds)
docker compose exec csm-dashboard csm watch 0xYourAddress --interval 60
```

### Local CLI Usage

### `csm rewards` - Check operator rewards

```bash
csm rewards [ADDRESS] [OPTIONS]
```

> **Note:** The `check` command is still available as an alias for backwards compatibility.

| Argument/Option | Short | Description |
|-----------------|-------|-------------|
| `ADDRESS` | | Ethereum address (required unless `--id` is provided) |
| `--id` | `-i` | Operator ID (skips address lookup, faster) |
| `--detailed` | `-d` | Include validator status from beacon chain and APY metrics |
| `--json` | `-j` | Output as JSON (same format as API) |
| `--rpc` | `-r` | Custom RPC URL |

**Examples:**

```bash
# Check by address
csm rewards 0xYourAddress

# Check by operator ID (faster)
csm rewards --id 42

# Get detailed validator info and APY
csm rewards --id 42 --detailed

# JSON output for scripting
csm rewards --id 42 --json

# JSON with detailed info
csm rewards --id 42 --detailed --json
```

### `csm watch` - Continuous monitoring

```bash
csm watch ADDRESS [OPTIONS]
```

| Argument/Option | Short | Description |
|-----------------|-------|-------------|
| `ADDRESS` | | Ethereum address to monitor (required) |
| `--interval` | `-i` | Refresh interval in seconds (default: 300) |
| `--rpc` | `-r` | Custom RPC URL |

**Examples:**

```bash
# Monitor with default 5-minute refresh
csm watch 0xYourAddress

# Monitor with 60-second refresh
csm watch 0xYourAddress --interval 60
```

### `csm list` - List all operators

```bash
csm list [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--rpc` | `-r` | Custom RPC URL |

Lists all operator IDs that have rewards in the current merkle tree.

### `csm serve` - Start web dashboard

```bash
csm serve [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--host` | Host to bind to (default: 127.0.0.1) |
| `--port` | Port to bind to (default: 8080) |
| `--reload` | Enable auto-reload for development |

**Examples:**

```bash
# Start on default port
csm serve

# Start on custom port
csm serve --port 3000

# Development mode with auto-reload
csm serve --reload
```

Then open http://localhost:8080 in your browser.

**Docker:** The web dashboard is already running when you use `docker compose up`. Access it at http://localhost:3000

## JSON Output

The `--json` flag outputs data in the same format as the API, making it easy to integrate with scripts or other tools:

```bash
csm rewards --id 333 --json
```

```json
{
  "operator_id": 333,
  "manager_address": "0x6ac683C503CF210CCF88193ec7ebDe2c993f63a4",
  "reward_address": "0x55915Cf2115c4D6e9085e94c8dAD710cabefef31",
  "rewards": {
    "current_bond_eth": 651.5523536856277,
    "required_bond_eth": 650.2,
    "excess_bond_eth": 1.3523536856277778,
    "cumulative_rewards_shares": 8973877501313655495,
    "cumulative_rewards_eth": 10.9642938931415,
    "distributed_shares": 7867435720490255061,
    "distributed_eth": 9.61244204773546,
    "unclaimed_shares": 1106441780823400434,
    "unclaimed_eth": 1.3518518454060409,
    "total_claimable_eth": 2.7042055310338187
  },
  "validators": {
    "total": 500,
    "active": 500,
    "exited": 0
  }
}
```

With `--detailed`, additional fields are included:

```json
{
  "operator_id": 333,
  "...": "...",
  "validators": {
    "total": 500,
    "active": 500,
    "exited": 0,
    "by_status": {
      "active": 100,
      "pending": 0,
      "exiting": 0,
      "exited": 0,
      "slashed": 0,
      "unknown": 0
    }
  },
  "performance": {
    "avg_effectiveness": 98.5
  },
  "apy": {
    "historical_reward_apy_28d": 2.21,
    "historical_reward_apy_ltd": 2.03,
    "bond_apy": 2.54,
    "net_apy_28d": 4.75,
    "net_apy_ltd": 4.57
  },
  "active_since": "2025-02-16T12:00:00"
}
```

## API Endpoints

- `GET /api/operator/{address_or_id}` - Get operator rewards data
  - Query param: `?detailed=true` for validator status and APY
- `GET /api/operators` - List all operators with rewards
- `GET /api/health` - Health check

## Understanding APY Metrics

The dashboard shows three APY metrics when using the `--detailed` flag:

| Metric | What It Means |
|--------|---------------|
| **Reward APY** | Your earnings from CSM fee distributions, based on your validators' performance |
| **Bond APY** | Automatic growth of your stETH bond from protocol rebasing (same for all operators) |
| **NET APY** | Total return = Reward APY + Bond APY |

### How APY is Calculated

**Reward APY** is calculated from actual reward distribution data published by Lido. Every ~28 days, Lido calculates how much each operator earned and publishes a "distribution frame" to IPFS (a decentralized file storage network). The dashboard fetches all these historical frames to calculate both 28-day and lifetime APY.

- **28-Day APY**: Based on the most recent ~28 days of reward distributions
- **Lifetime APY**: Based on all periods where you earned rewards (excludes ramp-up periods with no rewards to avoid misleadingly low numbers)

**Bond APY** represents the stETH rebase rate—the automatic growth of your bond due to Ethereum staking rewards. This rate is set by the Lido protocol and applies equally to all operators. The dashboard shows the current 7-day average rate from Lido's API.

> **Note**: Bond APY shows the current stETH rate for both 28-Day and Lifetime columns, as historical rates aren't readily available.

### Why You Might Want an Etherscan API Key

The actual reward data lives on IPFS and is always accessible. However, to *discover* which IPFS files exist, the dashboard needs to find historical `DistributionLogUpdated` events on the blockchain. This can be done in several ways:

| Method | Description |
|--------|-------------|
| **With Etherscan API key** | Most reliable. Queries Etherscan directly for complete, up-to-date distribution history. |
| **Without API key** | Uses a built-in list of known distributions. Works fine but may be slightly behind if new distributions happened recently. |

**How to get one (free):**
1. Go to [etherscan.io/apis](https://etherscan.io/apis)
2. Create a free account
3. Generate an API key
4. Add to your `.env` file: `ETHERSCAN_API_KEY=your_key_here`

The free tier allows 5 calls/second, which is plenty for this dashboard.

## Data Sources

- **On-chain contracts**: CSModule, CSAccounting, CSFeeDistributor, stETH
- **Rewards tree**: https://github.com/lidofinance/csm-rewards (updates hourly)
- **Beacon chain**: beaconcha.in API (for validator status)
- **Lido API**: stETH APR data (for bond APY calculations)
- **IPFS**: Historical reward distribution logs (cached locally after first fetch)

## Contract Addresses (Mainnet)

- CSModule: `0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F`
- CSAccounting: `0x4d72BFF1BeaC69925F8Bd12526a39BAAb069e5Da`
- CSFeeDistributor: `0xD99CC66fEC647E68294C6477B40fC7E0F6F618D0`
- stETH: `0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84`

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

## License

MIT
