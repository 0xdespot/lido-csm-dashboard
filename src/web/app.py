"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .routes import router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CSM Operator Dashboard",
        description="Track your Lido CSM validator earnings",
        version="0.1.0",
    )

    app.include_router(router, prefix="/api")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return """
<!DOCTYPE html>
<html>
<head>
    <title>CSM Operator Dashboard</title>
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
                <h2 class="text-xl font-bold mb-4">
                    Operator #<span id="operator-id"></span>
                </h2>
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

            <div class="bg-gray-800 rounded-lg p-6">
                <h3 class="text-lg font-bold mb-4">Earnings Summary</h3>
                <div class="space-y-3">
                    <div class="flex justify-between">
                        <span class="text-gray-400">Current Bond</span>
                        <span><span id="current-bond">0</span> ETH</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Required Bond</span>
                        <span><span id="required-bond">0</span> ETH</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Excess Bond</span>
                        <span class="text-green-400"><span id="excess-bond">0</span> ETH</span>
                    </div>
                    <hr class="border-gray-700">
                    <div class="flex justify-between">
                        <span class="text-gray-400">Cumulative Rewards</span>
                        <span><span id="cumulative-rewards">0</span> ETH</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Already Distributed</span>
                        <span><span id="distributed-rewards">0</span> ETH</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-400">Unclaimed Rewards</span>
                        <span class="text-green-400"><span id="unclaimed-rewards">0</span> ETH</span>
                    </div>
                    <hr class="border-gray-700">
                    <div class="flex justify-between text-xl font-bold">
                        <span>Total Claimable</span>
                        <span class="text-yellow-400"><span id="total-claimable">0</span> ETH</span>
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

            <div id="validator-status" class="hidden mt-6 bg-gray-800 rounded-lg p-6">
                <h3 class="text-lg font-bold mb-4">Validator Status (Beacon Chain)</h3>
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

            <div id="apy-section" class="hidden mt-6 bg-gray-800 rounded-lg p-6">
                <h3 class="text-lg font-bold mb-4">APY Metrics</h3>
                <div class="overflow-x-auto">
                    <table class="w-full">
                        <thead>
                            <tr class="text-gray-400 text-sm">
                                <th class="text-left py-2">Metric</th>
                                <th class="text-right py-2">7-Day</th>
                                <th class="text-right py-2">28-Day</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm">
                            <tr>
                                <td class="py-2 text-gray-400">Reward APY</td>
                                <td class="py-2 text-right text-green-400" id="reward-apy-7d">--%</td>
                                <td class="py-2 text-right text-green-400" id="reward-apy-28d">--%</td>
                            </tr>
                            <tr>
                                <td class="py-2 text-gray-400">Bond APY (stETH)</td>
                                <td class="py-2 text-right text-green-400" id="bond-apy-7d">--%</td>
                                <td class="py-2 text-right text-green-400" id="bond-apy-28d">--%</td>
                            </tr>
                            <tr class="border-t border-gray-700">
                                <td class="py-3 font-bold">NET APY</td>
                                <td class="py-3 text-right font-bold text-yellow-400" id="net-apy-7d">--%</td>
                                <td class="py-3 text-right font-bold text-yellow-400" id="net-apy-28d">--%</td>
                            </tr>
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
        const apySection = document.getElementById('apy-section');

        function formatApy(val) {
            return val !== null && val !== undefined ? val.toFixed(2) + '%' : '--%';
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const input = document.getElementById('address').value.trim();

            if (!input) return;

            // Reset UI
            loading.classList.remove('hidden');
            error.classList.add('hidden');
            results.classList.add('hidden');
            validatorStatus.classList.add('hidden');
            apySection.classList.add('hidden');
            loadDetailsBtn.classList.remove('hidden');
            loadDetailsBtn.disabled = false;
            loadDetailsBtn.textContent = 'Load Validator Status & APY (Beacon Chain)';

            try {
                const response = await fetch(`/api/operator/${input}`);
                const data = await response.json();

                loading.classList.add('hidden');

                if (!response.ok) {
                    error.classList.remove('hidden');
                    errorMessage.textContent = data.detail || 'An error occurred';
                    return;
                }

                // Populate results
                document.getElementById('operator-id').textContent = data.operator_id;
                document.getElementById('manager-address').textContent = data.manager_address;
                document.getElementById('reward-address').textContent = data.reward_address;

                // Show tip with operator ID for faster lookups
                document.getElementById('tip-operator-id').textContent = data.operator_id;
                document.getElementById('lookup-tip').classList.remove('hidden');

                document.getElementById('total-validators').textContent = data.validators.total;
                document.getElementById('active-validators').textContent = data.validators.active;
                document.getElementById('exited-validators').textContent = data.validators.exited;

                document.getElementById('current-bond').textContent = data.rewards.current_bond_eth.toFixed(6);
                document.getElementById('required-bond').textContent = data.rewards.required_bond_eth.toFixed(6);
                document.getElementById('excess-bond').textContent = data.rewards.excess_bond_eth.toFixed(6);
                document.getElementById('cumulative-rewards').textContent = data.rewards.cumulative_rewards_eth.toFixed(6);
                document.getElementById('distributed-rewards').textContent = data.rewards.distributed_eth.toFixed(6);
                document.getElementById('unclaimed-rewards').textContent = data.rewards.unclaimed_eth.toFixed(6);
                document.getElementById('total-claimable').textContent = data.rewards.total_claimable_eth.toFixed(6);

                results.classList.remove('hidden');
            } catch (err) {
                loading.classList.add('hidden');
                error.classList.remove('hidden');
                errorMessage.textContent = err.message || 'Network error';
            }
        });

        loadDetailsBtn.addEventListener('click', async () => {
            const operatorId = document.getElementById('operator-id').textContent;

            // Show loading, hide button
            loadDetailsBtn.classList.add('hidden');
            detailsLoading.classList.remove('hidden');

            try {
                const response = await fetch(`/api/operator/${operatorId}?detailed=true`);
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

                // Populate APY metrics if available
                if (data.apy) {
                    document.getElementById('reward-apy-7d').textContent = formatApy(data.apy.reward_apy_7d);
                    document.getElementById('reward-apy-28d').textContent = formatApy(data.apy.reward_apy_28d);
                    document.getElementById('bond-apy-7d').textContent = formatApy(data.apy.bond_apy);
                    document.getElementById('bond-apy-28d').textContent = formatApy(data.apy.bond_apy);
                    document.getElementById('net-apy-7d').textContent = formatApy(data.apy.net_apy_7d);
                    document.getElementById('net-apy-28d').textContent = formatApy(data.apy.net_apy_28d);

                    apySection.classList.remove('hidden');
                }
            } catch (err) {
                detailsLoading.classList.add('hidden');
                loadDetailsBtn.classList.remove('hidden');
                loadDetailsBtn.textContent = 'Failed - Click to Retry';
            }
        });
    </script>
</body>
</html>
        """

    return app
