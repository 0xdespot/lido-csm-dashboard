# Lido CSM Operator Dashboard

Track your Lido Community Staking Module (CSM) validator earnings, excess bond, and cumulative rewards.

## Features

- Look up operator by Ethereum address (manager or rewards address)
- View current bond vs required bond (excess is claimable)
- Track cumulative rewards and unclaimed amounts
- CLI for quick terminal lookups
- Web interface for browser-based monitoring

## Installation

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
- `CACHE_TTL_SECONDS`: Cache duration in seconds (default: 300)

## Usage

### CLI Commands

```bash
# Check rewards by address
csm check 0xYourAddress

# Check by operator ID (faster, skips address lookup)
csm check 0xYourAddress --id 42

# Use custom RPC
csm check 0xYourAddress --rpc https://eth.llamarpc.com

# Continuous monitoring (refreshes every 5 minutes by default)
csm watch 0xYourAddress --interval 60

# List all operators with rewards
csm list
```

### Web Interface

```bash
# Start the web server
csm serve --port 8080

# With auto-reload for development
csm serve --reload
```

Then open http://localhost:8080 in your browser.

### API Endpoints

- `GET /api/operator/{address_or_id}` - Get operator rewards data
- `GET /api/operators` - List all operators with rewards
- `GET /api/health` - Health check

## Data Sources

- **On-chain contracts**: CSModule, CSAccounting, CSFeeDistributor
- **Rewards tree**: https://github.com/lidofinance/csm-rewards (updates hourly)

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
