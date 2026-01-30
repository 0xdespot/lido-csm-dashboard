"""FastAPI application factory."""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CSM Operator Dashboard",
        description="Track your Lido CSM validator earnings",
        version="0.3.6.1",
    )

    # Add request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info(f"Request: {request.method} {request.url.path}")
        try:
            response = await call_next(request)
            logger.info(f"Response: {request.method} {request.url.path} -> {response.status_code}")
            return response
        except Exception as e:
            logger.error(f"Request failed: {request.method} {request.url.path} -> {e}")
            raise

    app.include_router(router, prefix="/api")

    # Mount static files for favicon and images
    img_dir = Path(__file__).parent.parent.parent / "img"
    if img_dir.exists():
        app.mount("/img", StaticFiles(directory=str(img_dir)), name="img")

    @app.on_event("startup")
    async def startup_event():
        logger.info("CSM Dashboard starting up")

    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("CSM Dashboard shutting down")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        logger.debug("Serving index page")
        return """
<!DOCTYPE html>
<html>
<head>
    <title>CSM Operator Dashboard</title>
    <link rel="icon" type="image/x-icon" href="/img/favicon.ico">
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen p-8">
    <div class="max-w-4xl mx-auto">
        <h1 class="text-3xl font-bold mb-2">CSM Operator Dashboard</h1>
        <p class="text-gray-400 mb-8">Track your Lido Community Staking Module validator earnings</p>

        <form id="lookup-form" class="mb-8">
            <div class="flex gap-4">
                <input type="text" id="address"
                       placeholder="Enter Ethereum address or Operator ID"
                       class="flex-1 p-3 bg-gray-800 rounded text-white border border-gray-700 focus:border-blue-500 focus:outline-none" />
                <button type="submit"
                        class="px-6 py-3 bg-blue-600 rounded hover:bg-blue-700 font-medium">
                    Check Rewards
                </button>
            </div>
        </form>

        <!-- Saved Operators Section -->
        <div id="saved-operators-section" class="mb-8 hidden">
            <div class="flex justify-between items-center mb-4">
                <h2 class="text-xl font-bold">Saved Operators</h2>
                <button id="refresh-all-btn" class="px-4 py-2 bg-green-600 rounded hover:bg-green-700 text-sm font-medium">
                    Refresh All
                </button>
            </div>
            <div id="saved-operators-loading" class="hidden">
                <div class="flex items-center justify-center p-4">
                    <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-green-500"></div>
                    <span class="ml-3 text-gray-400">Loading saved operators...</span>
                </div>
            </div>
            <div id="saved-operators-list" class="grid gap-4">
                <!-- Populated by JavaScript -->
            </div>
        </div>

        <div id="loading" class="hidden">
            <div class="flex items-center justify-center p-8">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                <span class="ml-3">Loading...</span>
            </div>
        </div>

        <div id="error" class="hidden bg-red-900/50 border border-red-500 rounded p-4 mb-4">
            <p id="error-message" class="text-red-300"></p>
        </div>

        <div id="results" class="hidden">
            <div class="bg-gray-800 rounded-lg p-6 mb-6">
                <div class="flex justify-between items-start">
                    <h2 class="text-xl font-bold mb-2">
                        Operator #<span id="operator-id"></span>
                    </h2>
                    <button id="save-operator-btn"
                            class="px-4 py-2 bg-yellow-600 rounded hover:bg-yellow-700 text-sm font-medium transition-colors">
                        Save
                    </button>
                </div>
                <div id="active-since-row" class="hidden text-sm text-green-400 mb-3">
                    Active Since: <span id="active-since"></span>
                </div>
                <div class="grid grid-cols-2 gap-4 text-sm">
                    <div>
                        <span class="text-gray-400">Manager:</span>
                        <span id="manager-address" class="font-mono text-xs break-all"></span>
                    </div>
                    <div>
                        <span class="text-gray-400">Rewards:</span>
                        <span id="reward-address" class="font-mono text-xs break-all"></span>
                    </div>
                </div>
                <div id="lookup-tip" class="hidden mt-3 text-sm text-gray-400 bg-gray-700/50 rounded px-3 py-2">
                    Tip: Use operator ID <span id="tip-operator-id" class="font-bold text-blue-400"></span> directly for faster lookups
                </div>
            </div>

            <div class="grid grid-cols-3 gap-4 mb-6">
                <div class="bg-gray-800 rounded-lg p-4 text-center">
                    <div class="text-2xl font-bold" id="total-validators">0</div>
                    <div class="text-gray-400 text-sm">Total Validators</div>
                </div>
                <div class="bg-gray-800 rounded-lg p-4 text-center">
                    <div class="text-2xl font-bold text-green-400" id="active-validators">0</div>
                    <div class="text-gray-400 text-sm">Active</div>
                </div>
                <div class="bg-gray-800 rounded-lg p-4 text-center">
                    <div class="text-2xl font-bold text-gray-500" id="exited-validators">0</div>
                    <div class="text-gray-400 text-sm">Exited</div>
                </div>
            </div>

            <div id="validator-status" class="hidden mb-6 bg-gray-800 rounded-lg p-6">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-bold">Validator Status (Beacon Chain)</h3>
                    <a id="beaconchain-link" href="#" target="_blank" rel="noopener"
                       class="hidden px-3 py-1.5 bg-blue-600/80 hover:bg-blue-600 rounded text-sm font-medium inline-flex items-center gap-1">
                        View on beaconcha.in <span class="text-xs">↗</span>
                    </a>
                </div>
                <div class="grid grid-cols-3 md:grid-cols-6 gap-3 mb-4">
                    <div class="bg-green-900/50 rounded-lg p-3 text-center">
                        <div class="text-xl font-bold text-green-400" id="status-active">0</div>
                        <div class="text-xs text-gray-400">Active</div>
                    </div>
                    <div class="bg-yellow-900/50 rounded-lg p-3 text-center">
                        <div class="text-xl font-bold text-yellow-400" id="status-pending">0</div>
                        <div class="text-xs text-gray-400">Pending</div>
                    </div>
                    <div class="bg-yellow-900/50 rounded-lg p-3 text-center">
                        <div class="text-xl font-bold text-yellow-400" id="status-exiting">0</div>
                        <div class="text-xs text-gray-400">Exiting</div>
                    </div>
                    <div class="bg-gray-700 rounded-lg p-3 text-center">
                        <div class="text-xl font-bold text-gray-400" id="status-exited">0</div>
                        <div class="text-xs text-gray-400">Exited</div>
                    </div>
                    <div class="bg-red-900/50 rounded-lg p-3 text-center">
                        <div class="text-xl font-bold text-red-400" id="status-slashed">0</div>
                        <div class="text-xs text-gray-400">Slashed</div>
                    </div>
                    <div class="bg-gray-700 rounded-lg p-3 text-center">
                        <div class="text-xl font-bold text-gray-500" id="status-unknown">0</div>
                        <div class="text-xs text-gray-400">Unknown</div>
                    </div>
                </div>
                <div id="effectiveness-section" class="hidden border-t border-gray-700 pt-4 mt-4">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400">Average Attestation Effectiveness</span>
                        <span class="text-xl font-bold text-green-400"><span id="avg-effectiveness">--</span>%</span>
                    </div>
                </div>
            </div>

            <div id="health-section" class="hidden mb-6 bg-gray-800 rounded-lg p-6">
                <h3 class="text-lg font-bold mb-4">Health Status</h3>
                <div class="space-y-3">
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Bond</span>
                        <span id="health-bond" class="font-medium">--</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Stuck Validators</span>
                        <span id="health-stuck" class="font-medium">--</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Slashed</span>
                        <span id="health-slashed" class="font-medium">--</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">At Risk (<32 ETH)</span>
                        <span id="health-at-risk" class="font-medium">--</span>
                    </div>
                    <div class="flex justify-between items-center">
                        <span class="text-gray-400">Performance Strikes</span>
                        <span id="health-strikes" class="font-medium">--</span>
                    </div>
                    <div id="strikes-detail" class="hidden">
                        <button id="toggle-strikes" class="text-sm text-purple-400 hover:text-purple-300 mt-1 mb-2">
                            Show validator details ▼
                        </button>
                        <div id="strikes-list" class="hidden pl-4 border-l-2 border-gray-600 space-y-1 text-sm font-mono max-h-64 overflow-y-auto">
                            <!-- Populated by JavaScript -->
                        </div>
                    </div>
                    <hr class="border-gray-700">
                    <div class="flex justify-between items-center">
                        <span class="font-bold">Overall</span>
                        <span id="health-overall" class="font-bold">--</span>
                    </div>
                </div>
            </div>

            <div class="bg-gray-800 rounded-lg p-6">
                <h3 class="text-lg font-bold mb-4">Earnings Summary</h3>
                <div id="eth-price-display" class="hidden text-xs text-gray-500 mb-3">
                    ETH: $<span id="eth-price-value">0</span> USD
                </div>
                <div class="space-y-3">
                    <div class="flex justify-between">
                        <span class="text-gray-400">Current Bond</span>
                        <div class="text-right">
                            <span><span id="current-bond">0</span> ETH</span>
                            <span id="current-bond-usd" class="text-gray-500 text-sm ml-2"></span>
                        </div>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Required Bond</span>
                        <div class="text-right">
                            <span><span id="required-bond">0</span> ETH</span>
                            <span id="required-bond-usd" class="text-gray-500 text-sm ml-2"></span>
                        </div>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Excess Bond</span>
                        <div class="text-right">
                            <span class="text-green-400"><span id="excess-bond">0</span> ETH</span>
                            <span id="excess-bond-usd" class="text-gray-500 text-sm ml-2"></span>
                        </div>
                    </div>
                    <hr class="border-gray-700">
                    <div class="flex justify-between">
                        <span class="text-gray-400">Cumulative Rewards</span>
                        <div class="text-right">
                            <span><span id="cumulative-rewards">0</span> ETH</span>
                            <span id="cumulative-rewards-usd" class="text-gray-500 text-sm ml-2"></span>
                        </div>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Already Distributed</span>
                        <div class="text-right">
                            <span><span id="distributed-rewards">0</span> ETH</span>
                            <span id="distributed-rewards-usd" class="text-gray-500 text-sm ml-2"></span>
                        </div>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Unclaimed Rewards</span>
                        <div class="text-right">
                            <span class="text-green-400"><span id="unclaimed-rewards">0</span> ETH</span>
                            <span id="unclaimed-rewards-usd" class="text-gray-500 text-sm ml-2"></span>
                        </div>
                    </div>
                    <hr class="border-gray-700">
                    <div class="flex justify-between text-xl font-bold">
                        <span>Total Claimable</span>
                        <div class="text-right">
                            <span class="text-yellow-400"><span id="total-claimable">0</span> ETH</span>
                            <div id="total-claimable-usd" class="text-gray-400 text-sm font-normal"></div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="mt-6">
                <button id="load-details"
                        class="w-full px-4 py-3 bg-purple-600 rounded hover:bg-purple-700 font-medium transition-colors">
                    Load Validator Status & APY (Beacon Chain)
                </button>
            </div>

            <div id="details-loading" class="hidden mt-6">
                <div class="flex items-center justify-center p-4">
                    <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-purple-500"></div>
                    <span class="ml-3 text-gray-400">Loading validator status...</span>
                </div>
            </div>

            <div id="apy-section" class="hidden mt-6 bg-gray-800 rounded-lg p-6">
                <h3 class="text-lg font-bold mb-4">APY Metrics (Historical)</h3>
                <div class="overflow-x-auto">
                    <table class="w-full">
                        <thead>
                            <tr class="text-gray-400 text-sm">
                                <th class="text-left py-2">Metric</th>
                                <th class="text-right py-2">28-Day</th>
                                <th id="apy-lifetime-header" class="hidden text-right py-2">Lifetime</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm">
                            <tr>
                                <td class="py-2 text-gray-400">Reward APY</td>
                                <td class="py-2 text-right text-green-400" id="reward-apy-28d">--%</td>
                                <td class="hidden py-2 text-right text-green-400" id="reward-apy-ltd">--%</td>
                            </tr>
                            <tr>
                                <td class="py-2 text-gray-400">Bond APY (stETH)*</td>
                                <td class="py-2 text-right text-green-400" id="bond-apy-28d">--%</td>
                                <td class="hidden py-2 text-right text-green-400" id="bond-apy-ltd">--%</td>
                            </tr>
                            <tr class="border-t border-gray-700">
                                <td class="py-3 font-bold">NET APY</td>
                                <td class="py-3 text-right font-bold text-yellow-400" id="net-apy-28d">--%</td>
                                <td class="hidden py-3 text-right font-bold text-yellow-400" id="net-apy-ltd">--%</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <p class="mt-3 text-xs text-gray-500">*Bond APY uses current stETH rate</p>

                <!-- Next Distribution -->
                <div id="next-distribution" class="hidden mt-4 pt-4 border-t border-gray-700">
                    <h4 class="text-md font-semibold mb-2 text-blue-400">Next Distribution</h4>
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-400">Estimated Date</span>
                        <span id="next-dist-date">--</span>
                    </div>
                    <div class="flex justify-between text-sm mt-1">
                        <span class="text-gray-400">Est. Rewards</span>
                        <span class="text-green-400">~<span id="next-dist-eth">--</span> stETH</span>
                    </div>
                </div>
            </div>

            <!-- Distribution History Section -->
            <div id="history-section" class="hidden mt-6 bg-gray-800 rounded-lg p-6">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-bold">Distribution History</h3>
                    <button id="load-history-btn" class="px-4 py-2 bg-blue-600 rounded hover:bg-blue-700 text-sm font-medium">
                        Load History
                    </button>
                </div>
                <div id="history-loading" class="hidden">
                    <div class="flex items-center justify-center p-4">
                        <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-500"></div>
                        <span class="ml-2 text-gray-400 text-sm">Loading history...</span>
                    </div>
                </div>
                <div id="history-table" class="hidden overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-gray-400">
                                <th class="text-left py-2">#</th>
                                <th class="text-left py-2">Date Range</th>
                                <th class="text-right py-2">Rewards</th>
                                <th class="text-right py-2">Vals</th>
                                <th class="text-right py-2">Reward APY</th>
                                <th class="text-right py-2">Bond APY</th>
                                <th class="text-right py-2">Net APY</th>
                            </tr>
                        </thead>
                        <tbody id="history-tbody">
                            <!-- Populated by JavaScript -->
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Withdrawal History Section -->
            <div id="withdrawal-section" class="hidden mt-6 bg-gray-800 rounded-lg p-6">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-bold">Withdrawal History</h3>
                    <button id="load-withdrawals-btn" class="px-4 py-2 bg-blue-600 rounded hover:bg-blue-700 text-sm font-medium">
                        Load Withdrawals
                    </button>
                </div>
                <div id="withdrawal-loading" class="hidden">
                    <div class="flex items-center justify-center p-4">
                        <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-500"></div>
                        <span class="ml-2 text-gray-400 text-sm">Loading withdrawals...</span>
                    </div>
                </div>
                <div id="withdrawal-table" class="hidden overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-gray-400">
                                <th class="text-left py-2">#</th>
                                <th class="text-left py-2">Date</th>
                                <th class="text-left py-2">Type</th>
                                <th class="text-right py-2">Amount</th>
                                <th class="text-left py-2">Status</th>
                            </tr>
                        </thead>
                        <tbody id="withdrawal-tbody">
                            <!-- Populated by JavaScript -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        const form = document.getElementById('lookup-form');
        const loading = document.getElementById('loading');
        const error = document.getElementById('error');
        const errorMessage = document.getElementById('error-message');
        const results = document.getElementById('results');
        const loadDetailsBtn = document.getElementById('load-details');
        const detailsLoading = document.getElementById('details-loading');
        const validatorStatus = document.getElementById('validator-status');
        const beaconchainLink = document.getElementById('beaconchain-link');
        const apySection = document.getElementById('apy-section');
        const healthSection = document.getElementById('health-section');
        const historySection = document.getElementById('history-section');

        // Global abort controller for canceling requests on page unload
        let pageAbortController = new AbortController();
        window.addEventListener('beforeunload', () => {
            pageAbortController.abort();
        });

        // Helper to check if error is from abort (page unload)
        function isAbortError(err) {
            return err.name === 'AbortError';
        }

        // ETH price state
        let ethPriceUsd = null;

        // Fetch ETH price from CoinGecko via our API
        async function fetchEthPrice() {
            try {
                const response = await fetch('/api/price/eth', { signal: pageAbortController.signal });
                const data = await response.json();
                if (data.price) {
                    ethPriceUsd = data.price;
                    document.getElementById('eth-price-value').textContent = ethPriceUsd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                    document.getElementById('eth-price-display').classList.remove('hidden');
                    // Update any displayed USD values
                    updateUsdDisplays();
                    // Re-render saved operator cards to show USD
                    if (typeof rerenderSavedOperators === 'function') {
                        rerenderSavedOperators();
                    }
                }
            } catch (err) {
                if (!isAbortError(err)) {
                    console.error('Failed to fetch ETH price:', err);
                }
            }
        }

        // Format USD value
        function formatUsd(ethAmount) {
            if (ethPriceUsd === null || ethAmount === null || ethAmount === undefined) return '';
            const usd = parseFloat(ethAmount) * ethPriceUsd;
            if (usd < 0.01) return '';
            return '$' + usd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }

        // Update all USD displays based on current ETH values
        function updateUsdDisplays() {
            if (ethPriceUsd === null) return;

            const fields = [
                { eth: 'current-bond', usd: 'current-bond-usd' },
                { eth: 'required-bond', usd: 'required-bond-usd' },
                { eth: 'excess-bond', usd: 'excess-bond-usd' },
                { eth: 'cumulative-rewards', usd: 'cumulative-rewards-usd' },
                { eth: 'distributed-rewards', usd: 'distributed-rewards-usd' },
                { eth: 'unclaimed-rewards', usd: 'unclaimed-rewards-usd' },
                { eth: 'total-claimable', usd: 'total-claimable-usd' },
            ];

            fields.forEach(({ eth, usd }) => {
                const ethEl = document.getElementById(eth);
                const usdEl = document.getElementById(usd);
                if (ethEl && usdEl) {
                    const ethVal = parseFloat(ethEl.textContent);
                    usdEl.textContent = formatUsd(ethVal);
                }
            });
        }

        // Fetch ETH price on page load
        fetchEthPrice();
        const loadHistoryBtn = document.getElementById('load-history-btn');
        const historyLoading = document.getElementById('history-loading');
        const historyTable = document.getElementById('history-table');
        const historyTbody = document.getElementById('history-tbody');
        const nextDistribution = document.getElementById('next-distribution');
        const withdrawalSection = document.getElementById('withdrawal-section');
        const loadWithdrawalsBtn = document.getElementById('load-withdrawals-btn');
        const withdrawalLoading = document.getElementById('withdrawal-loading');
        const withdrawalTable = document.getElementById('withdrawal-table');
        const withdrawalTbody = document.getElementById('withdrawal-tbody');

        // State variables for history/withdrawal loading
        let historyLoaded = false;
        let withdrawalsLoaded = false;

        function formatApy(val) {
            return val !== null && val !== undefined ? val.toFixed(2) + '%' : '--%';
        }

        // Reset UI to initial state
        function resetUI() {
            error.classList.add('hidden');
            results.classList.add('hidden');
            validatorStatus.classList.add('hidden');
            apySection.classList.add('hidden');
            healthSection.classList.add('hidden');
            historySection.classList.add('hidden');
            nextDistribution.classList.add('hidden');
            historyTable.classList.add('hidden');
            historyTbody.innerHTML = '';
            historyLoaded = false;
            loadHistoryBtn.textContent = 'Load History';
            withdrawalSection.classList.add('hidden');
            withdrawalTable.classList.add('hidden');
            withdrawalTbody.innerHTML = '';
            withdrawalsLoaded = false;
            loadWithdrawalsBtn.textContent = 'Load Withdrawals';
            beaconchainLink.classList.add('hidden');
            beaconchainLink.href = '#';
            document.getElementById('apy-lifetime-header').classList.add('hidden');
            document.getElementById('reward-apy-ltd').classList.add('hidden');
            document.getElementById('bond-apy-ltd').classList.add('hidden');
            document.getElementById('net-apy-ltd').classList.add('hidden');
            document.getElementById('active-since-row').classList.add('hidden');
            document.getElementById('effectiveness-section').classList.add('hidden');
            loadDetailsBtn.classList.remove('hidden');
            loadDetailsBtn.disabled = false;
            loadDetailsBtn.textContent = 'Load Validator Status & APY (Beacon Chain)';

            const strikesDetailDiv = document.getElementById('strikes-detail');
            const strikesList = document.getElementById('strikes-list');
            if (strikesDetailDiv) strikesDetailDiv.classList.add('hidden');
            if (strikesList) {
                strikesList.classList.add('hidden');
                strikesList.innerHTML = '';
            }
        }

        // Display operator data in UI (handles both basic and detailed data)
        function displayOperatorData(data) {
            // Basic info
            document.getElementById('operator-id').textContent = data.operator_id;
            document.getElementById('manager-address').textContent = data.manager_address;
            document.getElementById('reward-address').textContent = data.reward_address;

            // Active Since
            if (data.active_since) {
                const activeSince = new Date(data.active_since);
                const options = { year: 'numeric', month: 'short', day: 'numeric' };
                document.getElementById('active-since').textContent = activeSince.toLocaleDateString('en-US', options);
                document.getElementById('active-since-row').classList.remove('hidden');
            }

            // Tip
            document.getElementById('tip-operator-id').textContent = data.operator_id;
            document.getElementById('lookup-tip').classList.remove('hidden');

            // Validators
            document.getElementById('total-validators').textContent = data.validators?.total ?? 0;
            document.getElementById('active-validators').textContent = data.validators?.active ?? 0;
            document.getElementById('exited-validators').textContent = data.validators?.exited ?? 0;

            // Rewards
            document.getElementById('current-bond').textContent = parseFloat(data.rewards?.current_bond_eth ?? 0).toFixed(6);
            document.getElementById('required-bond').textContent = parseFloat(data.rewards?.required_bond_eth ?? 0).toFixed(6);
            document.getElementById('excess-bond').textContent = parseFloat(data.rewards?.excess_bond_eth ?? 0).toFixed(6);
            document.getElementById('cumulative-rewards').textContent = parseFloat(data.rewards?.cumulative_rewards_eth ?? 0).toFixed(6);
            document.getElementById('distributed-rewards').textContent = parseFloat(data.rewards?.distributed_eth ?? 0).toFixed(6);
            document.getElementById('unclaimed-rewards').textContent = parseFloat(data.rewards?.unclaimed_eth ?? 0).toFixed(6);
            document.getElementById('total-claimable').textContent = parseFloat(data.rewards?.total_claimable_eth ?? 0).toFixed(6);

            // Update USD equivalents
            updateUsdDisplays();

            results.classList.remove('hidden');

            // Detailed data (if available)
            if (data.validators?.by_status) {
                document.getElementById('status-active').textContent = data.validators.by_status.active || 0;
                document.getElementById('status-pending').textContent = data.validators.by_status.pending || 0;
                document.getElementById('status-exiting').textContent = data.validators.by_status.exiting || 0;
                document.getElementById('status-exited').textContent = data.validators.by_status.exited || 0;
                document.getElementById('status-slashed').textContent = data.validators.by_status.slashed || 0;
                document.getElementById('status-unknown').textContent = data.validators.by_status.unknown || 0;
                validatorStatus.classList.remove('hidden');
                // Hide the load button since we have detailed data
                loadDetailsBtn.classList.add('hidden');
            }

            // Performance/effectiveness
            if (data.performance && data.performance.avg_effectiveness !== null) {
                document.getElementById('avg-effectiveness').textContent = data.performance.avg_effectiveness.toFixed(1);
                document.getElementById('effectiveness-section').classList.remove('hidden');
            }

            // APY
            if (data.apy) {
                document.getElementById('reward-apy-28d').textContent = formatApy(data.apy.historical_reward_apy_28d);
                document.getElementById('reward-apy-ltd').textContent = formatApy(data.apy.historical_reward_apy_ltd);
                document.getElementById('bond-apy-28d').textContent = formatApy(data.apy.bond_apy);
                document.getElementById('bond-apy-ltd').textContent = formatApy(data.apy.bond_apy);
                document.getElementById('net-apy-28d').textContent = formatApy(data.apy.net_apy_28d);
                document.getElementById('net-apy-ltd').textContent = formatApy(data.apy.net_apy_ltd);

                if (data.apy.next_distribution_date || data.apy.next_distribution_est_eth) {
                    if (data.apy.next_distribution_date) {
                        const nextDate = new Date(data.apy.next_distribution_date);
                        const options = { year: 'numeric', month: 'short', day: 'numeric' };
                        document.getElementById('next-dist-date').textContent = nextDate.toLocaleDateString('en-US', options);
                    }
                    if (data.apy.next_distribution_est_eth) {
                        document.getElementById('next-dist-eth').textContent = data.apy.next_distribution_est_eth.toFixed(4);
                    }
                    nextDistribution.classList.remove('hidden');
                }

                apySection.classList.remove('hidden');
                historySection.classList.remove('hidden');
                withdrawalSection.classList.remove('hidden');
            }

            // Health
            if (data.health) {
                const h = data.health;

                if (h.bond_healthy) {
                    document.getElementById('health-bond').innerHTML = '<span class="text-green-400">HEALTHY</span>';
                } else {
                    document.getElementById('health-bond').innerHTML = `<span class="text-red-400">DEFICIT -${parseFloat(h.bond_deficit_eth).toFixed(4)} ETH</span>`;
                }

                if (h.stuck_validators_count === 0) {
                    document.getElementById('health-stuck').innerHTML = '<span class="text-green-400">0</span>';
                } else {
                    document.getElementById('health-stuck').innerHTML = `<span class="text-red-400">${h.stuck_validators_count} (exit within 4 days!)</span>`;
                }

                if (h.slashed_validators_count === 0) {
                    document.getElementById('health-slashed').innerHTML = '<span class="text-green-400">0</span>';
                } else {
                    document.getElementById('health-slashed').innerHTML = `<span class="text-red-400">${h.slashed_validators_count}</span>`;
                }

                if (h.validators_at_risk_count === 0) {
                    document.getElementById('health-at-risk').innerHTML = '<span class="text-green-400">0</span>';
                } else {
                    document.getElementById('health-at-risk').innerHTML = `<span class="text-yellow-400">${h.validators_at_risk_count}</span>`;
                }

                // Strikes
                const strikesDetailDiv = document.getElementById('strikes-detail');
                if (h.strikes && h.strikes.total_validators_with_strikes === 0) {
                    document.getElementById('health-strikes').innerHTML = '<span class="text-green-400">0 validators</span>';
                    strikesDetailDiv.classList.add('hidden');
                } else if (h.strikes) {
                    const strikeParts = [];
                    if (h.strikes.validators_at_risk > 0) {
                        strikeParts.push(`${h.strikes.validators_at_risk} at ejection`);
                    }
                    if (h.strikes.validators_near_ejection > 0) {
                        strikeParts.push(`${h.strikes.validators_near_ejection} near ejection`);
                    }
                    const strikeStatus = strikeParts.length > 0 ? strikeParts.join(', ') : 'monitoring';
                    const strikeColor = h.strikes.validators_at_risk > 0 ? 'text-red-400' :
                        (h.strikes.validators_near_ejection > 0 ? 'text-orange-400' : 'text-yellow-400');
                    document.getElementById('health-strikes').innerHTML =
                        `<span class="${strikeColor}">${h.strikes.total_validators_with_strikes} validators (${strikeStatus})</span>`;
                    strikesDetailDiv.classList.remove('hidden');
                }

                healthSection.classList.remove('hidden');
            }

            // Distribution History (if frames available in cached data)
            if (data.apy?.frames && data.apy.frames.length > 0) {
                historyTbody.innerHTML = data.apy.frames.map(frame => {
                    const startDate = new Date(frame.start_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                    const endDate = new Date(frame.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                    const perVal = frame.validator_count > 0 ? (frame.rewards_eth / frame.validator_count).toFixed(6) : '--';
                    return `<tr class="border-t border-gray-700">
                        <td class="py-2">${frame.frame_number}</td>
                        <td class="py-2">${startDate} - ${endDate}</td>
                        <td class="py-2 text-right text-green-400">${frame.rewards_eth.toFixed(4)}</td>
                        <td class="py-2 text-right">${frame.validator_count}</td>
                        <td class="py-2 text-right text-gray-400">${perVal}</td>
                    </tr>`;
                }).join('');

                // Add total row
                const totalEth = data.apy.frames.reduce((sum, f) => sum + f.rewards_eth, 0);
                historyTbody.innerHTML += `<tr class="border-t-2 border-gray-600 font-bold">
                    <td class="py-2" colspan="2">Total</td>
                    <td class="py-2 text-right text-yellow-400">${totalEth.toFixed(4)}</td>
                    <td class="py-2 text-right">--</td>
                    <td class="py-2 text-right">--</td>
                </tr>`;

                historyTable.classList.remove('hidden');
                historyLoaded = true;
                loadHistoryBtn.textContent = 'Hide History';
            }

            // Withdrawal History (if withdrawals available in cached data)
            if (data.withdrawals && data.withdrawals.length > 0) {
                withdrawalTbody.innerHTML = data.withdrawals.map((w, i) => {
                    const date = new Date(w.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                    const wType = w.withdrawal_type || 'stETH';
                    let amount, amountClass;
                    if (wType === 'unstETH' && w.claimed_eth !== null) {
                        amount = w.claimed_eth.toFixed(4) + ' ETH';
                        amountClass = 'text-green-400';
                    } else {
                        amount = w.eth_value.toFixed(4) + ' stETH';
                        amountClass = 'text-green-400';
                    }
                    let status;
                    if (wType === 'unstETH' && w.status) {
                        const statusColors = {
                            'pending': 'text-yellow-400',
                            'finalized': 'text-blue-400',
                            'claimed': 'text-green-400',
                        };
                        const statusLabels = {
                            'pending': 'Pending',
                            'finalized': 'Ready',
                            'claimed': 'Claimed',
                        };
                        status = `<span class="${statusColors[w.status] || 'text-gray-400'}">${statusLabels[w.status] || w.status}</span>`;
                    } else if (wType !== 'unstETH') {
                        status = '<span class="text-green-400">Claimed</span>';
                    } else {
                        status = '--';
                    }
                    return `<tr class="border-t border-gray-700">
                        <td class="py-2">${i + 1}</td>
                        <td class="py-2">${date}</td>
                        <td class="py-2">${wType}</td>
                        <td class="py-2 text-right ${amountClass}">${amount}</td>
                        <td class="py-2">${status}</td>
                    </tr>`;
                }).join('');

                withdrawalTable.classList.remove('hidden');
                withdrawalsLoaded = true;
                loadWithdrawalsBtn.textContent = 'Hide Withdrawals';
            } else if (data.withdrawals && data.withdrawals.length === 0) {
                // Explicit empty withdrawals
                withdrawalTbody.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-gray-400">No withdrawals found</td></tr>';
                withdrawalTable.classList.remove('hidden');
                withdrawalsLoaded = true;
                loadWithdrawalsBtn.textContent = 'Hide Withdrawals';
            }
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const input = document.getElementById('address').value.trim();

            if (!input) return;

            // Reset UI and show loading
            loading.classList.remove('hidden');
            resetUI();

            try {
                const response = await fetch(`/api/operator/${input}`, { signal: pageAbortController.signal });
                const data = await response.json();

                loading.classList.add('hidden');

                if (!response.ok) {
                    error.classList.remove('hidden');
                    errorMessage.textContent = data.detail || 'An error occurred';
                    return;
                }

                displayOperatorData(data);
            } catch (err) {
                if (isAbortError(err)) return;  // Page is unloading, ignore
                loading.classList.add('hidden');
                error.classList.remove('hidden');
                errorMessage.textContent = err.message || 'Network error';
            }
        });

        let isLoadingDetails = false;

        loadDetailsBtn.addEventListener('click', async () => {
            if (isLoadingDetails) return;
            isLoadingDetails = true;

            const operatorId = document.getElementById('operator-id').textContent;

            // Show loading, hide button
            loadDetailsBtn.classList.add('hidden');
            detailsLoading.classList.remove('hidden');

            try {
                const response = await fetch(`/api/operator/${operatorId}?detailed=true`, { signal: pageAbortController.signal });
                const data = await response.json();

                detailsLoading.classList.add('hidden');

                if (!response.ok) {
                    loadDetailsBtn.classList.remove('hidden');
                    loadDetailsBtn.textContent = 'Failed - Click to Retry';
                    return;
                }

                // Populate validator status
                if (data.validators.by_status) {
                    document.getElementById('status-active').textContent = data.validators.by_status.active || 0;
                    document.getElementById('status-pending').textContent = data.validators.by_status.pending || 0;
                    document.getElementById('status-exiting').textContent = data.validators.by_status.exiting || 0;
                    document.getElementById('status-exited').textContent = data.validators.by_status.exited || 0;
                    document.getElementById('status-slashed').textContent = data.validators.by_status.slashed || 0;
                    document.getElementById('status-unknown').textContent = data.validators.by_status.unknown || 0;
                }

                // Show effectiveness if available
                if (data.performance && data.performance.avg_effectiveness !== null) {
                    document.getElementById('avg-effectiveness').textContent = data.performance.avg_effectiveness.toFixed(1);
                    document.getElementById('effectiveness-section').classList.remove('hidden');
                }

                validatorStatus.classList.remove('hidden');

                // Build beaconcha.in dashboard URL with validator indices
                if (data.validator_details && data.validator_details.length > 0) {
                    const validatorIds = data.validator_details
                        .map(v => v.index !== null && v.index !== undefined ? v.index : v.pubkey)
                        .slice(0, 100)
                        .join(',');
                    beaconchainLink.href = `https://beaconcha.in/dashboard?validators=${validatorIds}`;
                    beaconchainLink.classList.remove('hidden');
                }

                // Populate APY metrics if available
                if (data.apy) {
                    document.getElementById('reward-apy-28d').textContent = formatApy(data.apy.historical_reward_apy_28d);
                    document.getElementById('reward-apy-ltd').textContent = formatApy(data.apy.historical_reward_apy_ltd);
                    document.getElementById('bond-apy-28d').textContent = formatApy(data.apy.bond_apy);
                    document.getElementById('bond-apy-ltd').textContent = formatApy(data.apy.bond_apy);
                    document.getElementById('net-apy-28d').textContent = formatApy(data.apy.net_apy_28d);
                    document.getElementById('net-apy-ltd').textContent = formatApy(data.apy.net_apy_ltd);

                    // Show next distribution info if available
                    if (data.apy.next_distribution_date || data.apy.next_distribution_est_eth) {
                        if (data.apy.next_distribution_date) {
                            const nextDate = new Date(data.apy.next_distribution_date);
                            const options = { year: 'numeric', month: 'short', day: 'numeric' };
                            document.getElementById('next-dist-date').textContent = nextDate.toLocaleDateString('en-US', options);
                        }
                        if (data.apy.next_distribution_est_eth) {
                            document.getElementById('next-dist-eth').textContent = data.apy.next_distribution_est_eth.toFixed(4);
                        }
                        nextDistribution.classList.remove('hidden');
                    }

                    apySection.classList.remove('hidden');
                    // Show history and withdrawal sections with toggles
                    historySection.classList.remove('hidden');
                    withdrawalSection.classList.remove('hidden');
                }

                // Display Active Since date if available
                if (data.active_since) {
                    const activeSince = new Date(data.active_since);
                    const options = { year: 'numeric', month: 'short', day: 'numeric' };
                    document.getElementById('active-since').textContent = activeSince.toLocaleDateString('en-US', options);
                    document.getElementById('active-since-row').classList.remove('hidden');
                }

                // Populate health status if available
                if (data.health) {
                    const h = data.health;

                    // Bond health
                    if (h.bond_healthy) {
                        document.getElementById('health-bond').innerHTML = '<span class="text-green-400">HEALTHY</span>';
                    } else {
                        document.getElementById('health-bond').innerHTML = `<span class="text-red-400">DEFICIT -${parseFloat(h.bond_deficit_eth).toFixed(4)} ETH</span>`;
                    }

                    // Stuck validators
                    if (h.stuck_validators_count === 0) {
                        document.getElementById('health-stuck').innerHTML = '<span class="text-green-400">0</span>';
                    } else {
                        document.getElementById('health-stuck').innerHTML = `<span class="text-red-400">${h.stuck_validators_count} (exit within 4 days!)</span>`;
                    }

                    // Slashed
                    if (h.slashed_validators_count === 0) {
                        document.getElementById('health-slashed').innerHTML = '<span class="text-green-400">0</span>';
                    } else {
                        document.getElementById('health-slashed').innerHTML = `<span class="text-red-400">${h.slashed_validators_count}</span>`;
                    }

                    // At risk
                    if (h.validators_at_risk_count === 0) {
                        document.getElementById('health-at-risk').innerHTML = '<span class="text-green-400">0</span>';
                    } else {
                        document.getElementById('health-at-risk').innerHTML = `<span class="text-yellow-400">${h.validators_at_risk_count}</span>`;
                    }

                    // Strikes
                    const strikesDetailDiv = document.getElementById('strikes-detail');
                    const toggleStrikesBtn = document.getElementById('toggle-strikes');
                    const strikesList = document.getElementById('strikes-list');

                    if (h.strikes.total_validators_with_strikes === 0) {
                        document.getElementById('health-strikes').innerHTML = '<span class="text-green-400">0 validators</span>';
                        strikesDetailDiv.classList.add('hidden');
                    } else {
                        // Build strike status message
                        const strikeParts = [];
                        if (h.strikes.validators_at_risk > 0) {
                            strikeParts.push(`${h.strikes.validators_at_risk} at ejection`);
                        }
                        if (h.strikes.validators_near_ejection > 0) {
                            strikeParts.push(`${h.strikes.validators_near_ejection} near ejection`);
                        }
                        const strikeStatus = strikeParts.length > 0 ? strikeParts.join(', ') : 'monitoring';
                        const strikeColor = h.strikes.validators_at_risk > 0 ? 'text-red-400' :
                            (h.strikes.validators_near_ejection > 0 ? 'text-orange-400' : 'text-yellow-400');
                        document.getElementById('health-strikes').innerHTML =
                            `<span class="${strikeColor}">${h.strikes.total_validators_with_strikes} validators (${strikeStatus})</span>`;

                        // Show the toggle button for strikes detail
                        strikesDetailDiv.classList.remove('hidden');
                        let strikesLoaded = false;

                        // Function to load strikes data
                        const loadStrikesData = async () => {
                            if (strikesLoaded) return;
                            strikesList.innerHTML = '<div class="text-gray-400">Loading...</div>';
                            strikesList.classList.remove('hidden');
                            try {
                                const opId = document.getElementById('operator-id').textContent;
                                const strikesResp = await fetch(`/api/operator/${opId}/strikes`, { signal: pageAbortController.signal });
                                const strikesData = await strikesResp.json();
                                const threshold = strikesData.strike_threshold || 3;
                                strikesList.innerHTML = strikesData.validators.map(v => {
                                    const vThreshold = v.strike_threshold || threshold;
                                    const colorClass = v.at_ejection_risk ? 'text-red-400' :
                                        (v.strike_count === vThreshold - 1 ? 'text-orange-400' : 'text-yellow-400');

                                    // Generate 6 dots with date tooltips
                                    const dots = v.strikes.map((strike, i) => {
                                        const frame = strikesData.frame_dates && strikesData.frame_dates[i];
                                        const dateRange = frame ? `${frame.start} - ${frame.end}` : `Frame ${i + 1}`;
                                        const tooltip = `${dateRange}: ${strike ? 'Strike' : 'OK'}`;
                                        const color = strike ? 'text-red-500' : 'text-green-500';
                                        return `<span class="${color} cursor-help" title="${tooltip}">●</span>`;
                                    }).join('');

                                    // Truncated pubkey with copy + beaconcha.in link
                                    const shortPubkey = v.pubkey.slice(0, 10) + '...' + v.pubkey.slice(-8);
                                    const beaconUrl = `https://beaconcha.in/validator/${v.pubkey}`;

                                    return `<div class="flex items-center gap-2 py-1.5 border-b border-gray-700 last:border-0 ${colorClass}">
                                        <span class="font-mono text-xs">${shortPubkey}</span>
                                        <button onclick="navigator.clipboard.writeText('${v.pubkey}'); this.textContent='✓'; setTimeout(() => this.textContent='📋', 1000)"
                                                class="text-gray-400 hover:text-white text-sm" title="Copy full address">📋</button>
                                        <a href="${beaconUrl}" target="_blank" rel="noopener"
                                           class="text-blue-400 hover:text-blue-300 text-sm" title="View on beaconcha.in">↗</a>
                                        <span class="flex gap-0.5 text-base ml-1">${dots}</span>
                                        <span class="text-gray-400 text-xs">(${v.strike_count}/${vThreshold})</span>
                                    </div>`;
                                }).join('');
                                strikesLoaded = true;
                                toggleStrikesBtn.textContent = 'Hide validator details ▲';
                            } catch (err) {
                                if (isAbortError(err)) return;  // Page is unloading, ignore
                                strikesList.innerHTML = '<div class="text-red-400">Failed to load strikes</div>';
                            }
                        };

                        // Auto-load strikes data when there are strikes
                        loadStrikesData();

                        // Remove old listener to prevent memory leak
                        if (toggleStrikesBtn._clickHandler) {
                            toggleStrikesBtn.removeEventListener('click', toggleStrikesBtn._clickHandler);
                        }
                        toggleStrikesBtn._clickHandler = async () => {
                            if (strikesList.classList.contains('hidden')) {
                                // Expand
                                if (!strikesLoaded) {
                                    await loadStrikesData();
                                } else {
                                    strikesList.classList.remove('hidden');
                                }
                                toggleStrikesBtn.textContent = 'Hide validator details ▲';
                            } else {
                                // Collapse
                                strikesList.classList.add('hidden');
                                toggleStrikesBtn.textContent = 'Show validator details ▼';
                            }
                        };
                        toggleStrikesBtn.addEventListener('click', toggleStrikesBtn._clickHandler);
                    }

                    // Overall - color-coded by severity
                    const strikeThreshold = h.strikes.strike_threshold || 3;
                    if (!h.has_issues) {
                        document.getElementById('health-overall').innerHTML = '<span class="text-green-400">No issues detected</span>';
                    } else if (
                        !h.bond_healthy ||
                        h.stuck_validators_count > 0 ||
                        h.slashed_validators_count > 0 ||
                        h.validators_at_risk_count > 0 ||
                        h.strikes.max_strikes >= strikeThreshold
                    ) {
                        // Critical issues (red)
                        let message = 'Issues detected - action required!';
                        if (h.strikes.max_strikes >= strikeThreshold) {
                            message = `Validator ejectable (${h.strikes.validators_at_risk} at ${strikeThreshold}/${strikeThreshold} strikes)`;
                        }
                        document.getElementById('health-overall').innerHTML = `<span class="text-red-400">${message}</span>`;
                    } else if (h.strikes.max_strikes === strikeThreshold - 1) {
                        // Warning level 2 (orange) - one more strike = ejectable
                        document.getElementById('health-overall').innerHTML =
                            `<span class="text-orange-400">Warning - ${h.strikes.validators_near_ejection} validator(s) at ${strikeThreshold - 1}/${strikeThreshold} strikes</span>`;
                    } else {
                        // Warning level 1 (yellow) - has strikes but not critical
                        document.getElementById('health-overall').innerHTML =
                            '<span class="text-yellow-400">Warning - validator(s) have strikes</span>';
                    }

                    healthSection.classList.remove('hidden');
                }
            } catch (err) {
                if (isAbortError(err)) return;  // Page is unloading, ignore
                detailsLoading.classList.add('hidden');
                loadDetailsBtn.classList.remove('hidden');
                loadDetailsBtn.textContent = 'Failed - Click to Retry';
            } finally {
                isLoadingDetails = false;
            }
        });

        // History button handler
        loadHistoryBtn.addEventListener('click', async () => {
            if (historyLoaded) {
                // Toggle visibility
                historyTable.classList.toggle('hidden');
                loadHistoryBtn.textContent = historyTable.classList.contains('hidden')
                    ? 'Load History' : 'Hide History';
                return;
            }

            const operatorId = document.getElementById('operator-id').textContent;
            historyLoading.classList.remove('hidden');
            historyTable.classList.add('hidden');

            try {
                const response = await fetch(`/api/operator/${operatorId}?detailed=true&history=true`, { signal: pageAbortController.signal });
                const data = await response.json();

                historyLoading.classList.add('hidden');

                if (!response.ok || !data.apy || !data.apy.frames) {
                    historyTbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-gray-400">No history available</td></tr>';
                    historyTable.classList.remove('hidden');
                    return;
                }

                // Populate history table
                historyTbody.innerHTML = data.apy.frames.map(frame => {
                    const startDate = new Date(frame.start_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                    const endDate = new Date(frame.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                    const rewardApy = frame.apy !== null && frame.apy !== undefined ? frame.apy.toFixed(2) + '%' : '--';
                    const bondApy = frame.bond_apy !== null && frame.bond_apy !== undefined ? frame.bond_apy.toFixed(2) + '%' : '--';
                    const netApy = frame.net_apy !== null && frame.net_apy !== undefined ? frame.net_apy.toFixed(2) + '%' : '--';
                    return `<tr class="border-t border-gray-700">
                        <td class="py-2">${frame.frame_number}</td>
                        <td class="py-2">${startDate} - ${endDate}</td>
                        <td class="py-2 text-right text-green-400">${frame.rewards_eth.toFixed(4)}</td>
                        <td class="py-2 text-right">${frame.validator_count}</td>
                        <td class="py-2 text-right text-green-400">${rewardApy}</td>
                        <td class="py-2 text-right text-green-400">${bondApy}</td>
                        <td class="py-2 text-right text-yellow-400 font-bold">${netApy}</td>
                    </tr>`;
                }).join('');

                // Add total row with lifetime APYs
                const totalEth = data.apy.frames.reduce((sum, f) => sum + f.rewards_eth, 0);
                const lifetimeRewardApy = data.apy.lifetime_reward_apy !== null && data.apy.lifetime_reward_apy !== undefined ? data.apy.lifetime_reward_apy.toFixed(2) + '%' : '--';
                const lifetimeBondApy = data.apy.lifetime_bond_apy !== null && data.apy.lifetime_bond_apy !== undefined ? data.apy.lifetime_bond_apy.toFixed(2) + '%' : '--';
                const lifetimeNetApy = data.apy.lifetime_net_apy !== null && data.apy.lifetime_net_apy !== undefined ? data.apy.lifetime_net_apy.toFixed(2) + '%' : '--';
                historyTbody.innerHTML += `<tr class="border-t-2 border-gray-600 font-bold">
                    <td class="py-2" colspan="2">Lifetime</td>
                    <td class="py-2 text-right text-yellow-400">${totalEth.toFixed(4)}</td>
                    <td class="py-2 text-right">--</td>
                    <td class="py-2 text-right text-green-400">${lifetimeRewardApy}</td>
                    <td class="py-2 text-right text-green-400">${lifetimeBondApy}</td>
                    <td class="py-2 text-right text-yellow-400">${lifetimeNetApy}</td>
                </tr>`;

                // Reveal and populate lifetime APY columns
                if (data.apy) {
                    document.getElementById('apy-lifetime-header').classList.remove('hidden');
                    document.getElementById('reward-apy-ltd').textContent = formatApy(data.apy.lifetime_reward_apy);
                    document.getElementById('reward-apy-ltd').classList.remove('hidden');
                    document.getElementById('bond-apy-ltd').textContent = formatApy(data.apy.lifetime_bond_apy);
                    document.getElementById('bond-apy-ltd').classList.remove('hidden');
                    document.getElementById('net-apy-ltd').textContent = formatApy(data.apy.lifetime_net_apy);
                    document.getElementById('net-apy-ltd').classList.remove('hidden');
                }

                historyTable.classList.remove('hidden');
                historyLoaded = true;
                loadHistoryBtn.textContent = 'Hide History';
            } catch (err) {
                if (isAbortError(err)) return;  // Page is unloading, ignore
                historyLoading.classList.add('hidden');
                historyTbody.innerHTML = '<tr><td colspan="7" class="py-4 text-center text-red-400">Failed to load history</td></tr>';
                historyTable.classList.remove('hidden');
            }
        });

        // Withdrawal button handler
        loadWithdrawalsBtn.addEventListener('click', async () => {
            if (withdrawalsLoaded) {
                // Toggle visibility
                withdrawalTable.classList.toggle('hidden');
                loadWithdrawalsBtn.textContent = withdrawalTable.classList.contains('hidden')
                    ? 'Load Withdrawals' : 'Hide Withdrawals';
                return;
            }

            const operatorId = document.getElementById('operator-id').textContent;
            withdrawalLoading.classList.remove('hidden');
            withdrawalTable.classList.add('hidden');

            try {
                const response = await fetch(`/api/operator/${operatorId}?withdrawals=true`, { signal: pageAbortController.signal });
                const data = await response.json();

                withdrawalLoading.classList.add('hidden');

                if (!response.ok || !data.withdrawals || data.withdrawals.length === 0) {
                    withdrawalTbody.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-gray-400">No withdrawals found</td></tr>';
                    withdrawalTable.classList.remove('hidden');
                    withdrawalsLoaded = true;
                    loadWithdrawalsBtn.textContent = 'Hide Withdrawals';
                    return;
                }

                // Populate withdrawal table
                withdrawalTbody.innerHTML = data.withdrawals.map((w, i) => {
                    const date = new Date(w.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
                    const wType = w.withdrawal_type || 'stETH';
                    // For unstETH, show claimed ETH if available, otherwise show stETH value
                    let amount, amountClass;
                    if (wType === 'unstETH' && w.claimed_eth !== null) {
                        amount = w.claimed_eth.toFixed(4) + ' ETH';
                        amountClass = 'text-green-400';
                    } else {
                        amount = w.eth_value.toFixed(4) + ' stETH';
                        amountClass = 'text-green-400';
                    }
                    // Status for unstETH
                    let status;
                    if (wType === 'unstETH' && w.status) {
                        const statusColors = {
                            'pending': 'text-yellow-400',
                            'finalized': 'text-blue-400',
                            'claimed': 'text-green-400',
                        };
                        const statusLabels = {
                            'pending': 'Pending',
                            'finalized': 'Ready',
                            'claimed': 'Claimed',
                        };
                        status = `<span class="${statusColors[w.status] || 'text-gray-400'}">${statusLabels[w.status] || w.status}</span>`;
                    } else if (wType !== 'unstETH') {
                        status = '<span class="text-green-400">Claimed</span>';
                    } else {
                        status = '--';
                    }
                    return `<tr class="border-t border-gray-700">
                        <td class="py-2">${i + 1}</td>
                        <td class="py-2">${date}</td>
                        <td class="py-2"><span class="${wType === 'unstETH' ? 'text-purple-400' : 'text-blue-400'}">${wType}</span></td>
                        <td class="py-2 text-right ${amountClass}">${amount}</td>
                        <td class="py-2">${status}</td>
                    </tr>`;
                }).join('');

                // Add total row
                const stethTotal = data.withdrawals
                    .filter(w => w.withdrawal_type !== 'unstETH')
                    .reduce((sum, w) => sum + w.eth_value, 0);
                const ethTotal = data.withdrawals
                    .filter(w => w.withdrawal_type === 'unstETH' && w.claimed_eth !== null)
                    .reduce((sum, w) => sum + w.claimed_eth, 0);
                let totalStr = '';
                if (stethTotal > 0) totalStr += stethTotal.toFixed(4) + ' stETH';
                if (ethTotal > 0) totalStr += (totalStr ? ' + ' : '') + ethTotal.toFixed(4) + ' ETH';
                if (!totalStr) totalStr = '0';

                withdrawalTbody.innerHTML += `<tr class="border-t-2 border-gray-600 font-bold">
                    <td class="py-2" colspan="3">Total Claimed</td>
                    <td class="py-2 text-right text-yellow-400" colspan="2">${totalStr}</td>
                </tr>`;

                withdrawalTable.classList.remove('hidden');
                withdrawalsLoaded = true;
                loadWithdrawalsBtn.textContent = 'Hide Withdrawals';
            } catch (err) {
                if (isAbortError(err)) return;  // Page is unloading, ignore
                withdrawalLoading.classList.add('hidden');
                withdrawalTbody.innerHTML = '<tr><td colspan="5" class="py-4 text-center text-red-400">Failed to load withdrawals</td></tr>';
                withdrawalTable.classList.remove('hidden');
            }
        });

        // ===== SAVED OPERATORS FUNCTIONALITY =====
        const savedOperatorsSection = document.getElementById('saved-operators-section');
        const savedOperatorsList = document.getElementById('saved-operators-list');
        const savedOperatorsLoading = document.getElementById('saved-operators-loading');
        const refreshAllBtn = document.getElementById('refresh-all-btn');
        const saveOperatorBtn = document.getElementById('save-operator-btn');

        let currentOperatorSaved = false;
        let savedOperatorsData = {};  // Store operator data by ID for quick lookup

        // Format relative time with precision
        function formatRelativeTime(isoString) {
            const date = new Date(isoString);
            const now = new Date();
            const diffMs = now - date;
            const diffSecs = Math.floor(diffMs / 1000);
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffSecs < 60) return 'just now';
            if (diffMins < 60) return `${diffMins} min ago`;
            if (diffHours < 24) {
                const mins = diffMins % 60;
                if (mins === 0) return `${diffHours}h ago`;
                return `${diffHours}h ${mins}m ago`;
            }
            if (diffDays < 7) {
                const hours = diffHours % 24;
                if (hours === 0) return `${diffDays}d ago`;
                return `${diffDays}d ${hours}h ago`;
            }
            return `${diffDays}d ago`;
        }

        // Render a single saved operator card
        function renderSavedOperatorCard(op) {
            const claimable = parseFloat(op.rewards?.total_claimable_eth ?? 0).toFixed(4);
            const claimableUsd = formatUsd(claimable);
            const validators = op.validators?.active ?? 0;
            const updatedAt = op._updated_at ? formatRelativeTime(op._updated_at) : 'unknown';

            // Health indicator
            let healthDot = '<span class="w-2 h-2 rounded-full bg-green-500 inline-block"></span>';
            if (op.health?.has_issues) {
                if (!op.health.bond_healthy || op.health.slashed_validators_count > 0 || op.health.stuck_validators_count > 0) {
                    healthDot = '<span class="w-2 h-2 rounded-full bg-red-500 inline-block"></span>';
                } else {
                    healthDot = '<span class="w-2 h-2 rounded-full bg-yellow-500 inline-block"></span>';
                }
            }

            return `
                <div class="bg-gray-800 rounded-lg p-4 flex justify-between items-center" data-operator-id="${op.operator_id}">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-1">
                            ${healthDot}
                            <span class="font-bold">Operator #${op.operator_id}</span>
                            <span class="text-gray-500 text-xs">Updated ${updatedAt}</span>
                        </div>
                        <div class="text-sm text-gray-400">
                            <span class="text-green-400">${validators}</span> active validators |
                            <span class="text-yellow-400">${claimable} ETH</span>${claimableUsd ? ` <span class="text-gray-500">(${claimableUsd})</span>` : ''} claimable
                        </div>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="viewSavedOperator(${op.operator_id})"
                                class="px-3 py-1 bg-blue-600 rounded hover:bg-blue-700 text-sm">
                            View
                        </button>
                        <button onclick="refreshSavedOperator(${op.operator_id}, this)"
                                class="px-3 py-1 bg-green-600 rounded hover:bg-green-700 text-sm">
                            Refresh
                        </button>
                        <button onclick="removeSavedOperator(${op.operator_id}, this)"
                                class="px-3 py-1 bg-red-600 rounded hover:bg-red-700 text-sm">
                            Remove
                        </button>
                    </div>
                </div>
            `;
        }

        // Re-render saved operator cards (called when ETH price updates)
        function rerenderSavedOperators() {
            if (Object.keys(savedOperatorsData).length > 0) {
                const operators = Object.values(savedOperatorsData);
                savedOperatorsList.innerHTML = operators.map(renderSavedOperatorCard).join('');
            }
        }

        // Load saved operators on page load
        async function loadSavedOperators() {
            try {
                const response = await fetch('/api/saved-operators', { signal: pageAbortController.signal });
                const data = await response.json();

                if (data.operators && data.operators.length > 0) {
                    // Store data for quick lookup
                    savedOperatorsData = {};
                    data.operators.forEach(op => {
                        savedOperatorsData[op.operator_id] = op;
                    });
                    savedOperatorsList.innerHTML = data.operators.map(renderSavedOperatorCard).join('');
                    savedOperatorsSection.classList.remove('hidden');
                } else {
                    savedOperatorsData = {};
                    savedOperatorsSection.classList.add('hidden');
                }
            } catch (err) {
                if (!isAbortError(err)) {
                    console.error('Failed to load saved operators:', err);
                }
            }
        }

        // View a saved operator (display cached data directly)
        window.viewSavedOperator = function(operatorId) {
            const opData = savedOperatorsData[operatorId];
            if (!opData) {
                // Fallback to API fetch if data not in cache
                document.getElementById('address').value = operatorId;
                form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                return;
            }

            // Display cached data directly
            document.getElementById('address').value = operatorId;
            resetUI();
            displayOperatorData(opData);

            // Update save button state
            currentOperatorSaved = true;
            updateSaveButton();
        };

        // Refresh a saved operator
        window.refreshSavedOperator = async function(operatorId, btn) {
            const originalText = btn.textContent;
            btn.innerHTML = '<span class="inline-block animate-spin">&#8635;</span>';
            btn.disabled = true;

            try {
                const response = await fetch(`/api/operator/${operatorId}/refresh`, { method: 'POST', signal: pageAbortController.signal });
                if (response.ok) {
                    const data = await response.json();
                    // Update the card in the list and stored data
                    const card = document.querySelector(`[data-operator-id="${operatorId}"]`);
                    if (card && data.data) {
                        data.data._updated_at = new Date().toISOString();
                        savedOperatorsData[operatorId] = data.data;  // Update stored data
                        card.outerHTML = renderSavedOperatorCard(data.data);
                    }
                }
            } catch (err) {
                if (!isAbortError(err)) {
                    console.error('Failed to refresh operator:', err);
                }
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        };

        // Remove a saved operator
        window.removeSavedOperator = async function(operatorId, btn) {
            const originalText = btn.textContent;
            btn.innerHTML = '<span class="inline-block animate-spin">&#8635;</span>';
            btn.disabled = true;

            try {
                const response = await fetch(`/api/operator/${operatorId}/save`, { method: 'DELETE', signal: pageAbortController.signal });
                if (response.ok) {
                    delete savedOperatorsData[operatorId];  // Remove from stored data
                    const card = document.querySelector(`[data-operator-id="${operatorId}"]`);
                    if (card) card.remove();

                    // Hide section if no more operators
                    if (savedOperatorsList.children.length === 0) {
                        savedOperatorsSection.classList.add('hidden');
                    }

                    // Update save button if viewing this operator
                    const currentOpId = document.getElementById('operator-id').textContent;
                    if (currentOpId == operatorId) {
                        currentOperatorSaved = false;
                        updateSaveButton();
                    }
                }
            } catch (err) {
                if (!isAbortError(err)) {
                    console.error('Failed to remove operator:', err);
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }
            }
        };

        // Refresh all saved operators
        refreshAllBtn.addEventListener('click', async () => {
            const originalText = refreshAllBtn.textContent;
            refreshAllBtn.disabled = true;

            const cards = savedOperatorsList.querySelectorAll('[data-operator-id]');
            const total = cards.length;
            let current = 0;

            for (const card of cards) {
                current++;
                refreshAllBtn.innerHTML = `<span class="inline-block animate-spin mr-1">&#8635;</span> ${current}/${total}`;

                const operatorId = card.dataset.operatorId;
                try {
                    const response = await fetch(`/api/operator/${operatorId}/refresh`, { method: 'POST', signal: pageAbortController.signal });
                    if (response.ok) {
                        const data = await response.json();
                        if (data.data) {
                            data.data._updated_at = new Date().toISOString();
                            savedOperatorsData[operatorId] = data.data;  // Update stored data
                            card.outerHTML = renderSavedOperatorCard(data.data);
                        }
                    }
                } catch (err) {
                    if (isAbortError(err)) break;  // Page is unloading, stop loop
                    console.error(`Failed to refresh operator ${operatorId}:`, err);
                }
            }

            refreshAllBtn.innerHTML = originalText;
            refreshAllBtn.disabled = false;
        });

        // Update save button state
        function updateSaveButton() {
            if (currentOperatorSaved) {
                saveOperatorBtn.textContent = 'Saved';
                saveOperatorBtn.classList.remove('bg-yellow-600', 'hover:bg-yellow-700');
                saveOperatorBtn.classList.add('bg-gray-600', 'hover:bg-gray-700');
            } else {
                saveOperatorBtn.textContent = 'Save';
                saveOperatorBtn.classList.remove('bg-gray-600', 'hover:bg-gray-700');
                saveOperatorBtn.classList.add('bg-yellow-600', 'hover:bg-yellow-700');
            }
        }

        // Check if current operator is saved
        async function checkIfOperatorSaved(operatorId) {
            try {
                const response = await fetch(`/api/operator/${operatorId}/saved`, { signal: pageAbortController.signal });
                const data = await response.json();
                currentOperatorSaved = data.saved;
                updateSaveButton();
            } catch (err) {
                if (!isAbortError(err)) {
                    console.error('Failed to check if operator is saved:', err);
                }
            }
        }

        // Save/unsave operator button handler
        saveOperatorBtn.addEventListener('click', async () => {
            const operatorId = document.getElementById('operator-id').textContent;
            if (!operatorId) return;

            saveOperatorBtn.disabled = true;
            saveOperatorBtn.innerHTML = '<span class="inline-block animate-spin">&#8635;</span>';

            try {
                if (currentOperatorSaved) {
                    // Unsave
                    const response = await fetch(`/api/operator/${operatorId}/save`, { method: 'DELETE', signal: pageAbortController.signal });
                    if (response.ok) {
                        currentOperatorSaved = false;
                        delete savedOperatorsData[operatorId];  // Remove from stored data
                        // Remove from saved list
                        const card = document.querySelector(`[data-operator-id="${operatorId}"]`);
                        if (card) card.remove();
                        if (savedOperatorsList.children.length === 0) {
                            savedOperatorsSection.classList.add('hidden');
                        }
                    }
                } else {
                    // Save
                    const response = await fetch(`/api/operator/${operatorId}/save`, { method: 'POST', signal: pageAbortController.signal });
                    if (response.ok) {
                        currentOperatorSaved = true;
                        // Reload saved operators to show the new one
                        await loadSavedOperators();
                    }
                }
            } catch (err) {
                if (!isAbortError(err)) {
                    console.error('Failed to save/unsave operator:', err);
                }
            } finally {
                saveOperatorBtn.disabled = false;
                updateSaveButton();
            }
        });

        // Modify form submit to check if operator is saved
        const originalFormSubmit = form.onsubmit;
        form.addEventListener('submit', async (e) => {
            // Wait a bit for the results to load, then check if saved
            setTimeout(async () => {
                const operatorId = document.getElementById('operator-id').textContent;
                if (operatorId) {
                    await checkIfOperatorSaved(operatorId);
                }
            }, 100);
        });

        // Load saved operators on page load
        loadSavedOperators();
    </script>
</body>
</html>
        """

    return app
