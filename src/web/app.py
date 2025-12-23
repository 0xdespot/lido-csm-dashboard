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
                <h2 class="text-xl font-bold mb-2">
                    Operator #<span id="operator-id"></span>
                </h2>
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

            <div id="apy-section" class="hidden mt-6 bg-gray-800 rounded-lg p-6">
                <h3 class="text-lg font-bold mb-4">APY Metrics (Historical)</h3>
                <div class="overflow-x-auto">
                    <table class="w-full">
                        <thead>
                            <tr class="text-gray-400 text-sm">
                                <th class="text-left py-2">Metric</th>
                                <th class="text-right py-2">28-Day</th>
                                <th class="text-right py-2">Lifetime</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm">
                            <tr>
                                <td class="py-2 text-gray-400">Reward APY</td>
                                <td class="py-2 text-right text-green-400" id="reward-apy-28d">--%</td>
                                <td class="py-2 text-right text-green-400" id="reward-apy-ltd">--%</td>
                            </tr>
                            <tr>
                                <td class="py-2 text-gray-400">Bond APY (stETH)*</td>
                                <td class="py-2 text-right text-green-400" id="bond-apy-28d">--%</td>
                                <td class="py-2 text-right text-green-400" id="bond-apy-ltd">--%</td>
                            </tr>
                            <tr class="border-t border-gray-700">
                                <td class="py-3 font-bold">NET APY</td>
                                <td class="py-3 text-right font-bold text-yellow-400" id="net-apy-28d">--%</td>
                                <td class="py-3 text-right font-bold text-yellow-400" id="net-apy-ltd">--%</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <p class="mt-3 text-xs text-gray-500">*Bond APY uses current stETH rate</p>
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
        const healthSection = document.getElementById('health-section');

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
            healthSection.classList.add('hidden');
            document.getElementById('active-since-row').classList.add('hidden');
            loadDetailsBtn.classList.remove('hidden');
            loadDetailsBtn.disabled = false;
            loadDetailsBtn.textContent = 'Load Validator Status & APY (Beacon Chain)';

            // Reset strikes state for new search
            const strikesDetailDiv = document.getElementById('strikes-detail');
            const strikesList = document.getElementById('strikes-list');
            if (strikesDetailDiv) strikesDetailDiv.classList.add('hidden');
            if (strikesList) {
                strikesList.classList.add('hidden');
                strikesList.innerHTML = '';
            }

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

                // Show Active Since if available
                if (data.active_since) {
                    const activeSince = new Date(data.active_since);
                    const options = { year: 'numeric', month: 'short', day: 'numeric' };
                    document.getElementById('active-since').textContent = activeSince.toLocaleDateString('en-US', options);
                    document.getElementById('active-since-row').classList.remove('hidden');
                }

                // Show tip with operator ID for faster lookups
                document.getElementById('tip-operator-id').textContent = data.operator_id;
                document.getElementById('lookup-tip').classList.remove('hidden');

                document.getElementById('total-validators').textContent = data.validators.total;
                document.getElementById('active-validators').textContent = data.validators.active;
                document.getElementById('exited-validators').textContent = data.validators.exited;

                document.getElementById('current-bond').textContent = parseFloat(data.rewards?.current_bond_eth ?? 0).toFixed(6);
                document.getElementById('required-bond').textContent = parseFloat(data.rewards?.required_bond_eth ?? 0).toFixed(6);
                document.getElementById('excess-bond').textContent = parseFloat(data.rewards?.excess_bond_eth ?? 0).toFixed(6);
                document.getElementById('cumulative-rewards').textContent = parseFloat(data.rewards?.cumulative_rewards_eth ?? 0).toFixed(6);
                document.getElementById('distributed-rewards').textContent = parseFloat(data.rewards?.distributed_eth ?? 0).toFixed(6);
                document.getElementById('unclaimed-rewards').textContent = parseFloat(data.rewards?.unclaimed_eth ?? 0).toFixed(6);
                document.getElementById('total-claimable').textContent = parseFloat(data.rewards?.total_claimable_eth ?? 0).toFixed(6);

                results.classList.remove('hidden');
            } catch (err) {
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
                    document.getElementById('reward-apy-28d').textContent = formatApy(data.apy.historical_reward_apy_28d);
                    document.getElementById('reward-apy-ltd').textContent = formatApy(data.apy.historical_reward_apy_ltd);
                    document.getElementById('bond-apy-28d').textContent = formatApy(data.apy.bond_apy);
                    document.getElementById('bond-apy-ltd').textContent = formatApy(data.apy.bond_apy);
                    document.getElementById('net-apy-28d').textContent = formatApy(data.apy.net_apy_28d);
                    document.getElementById('net-apy-ltd').textContent = formatApy(data.apy.net_apy_ltd);

                    apySection.classList.remove('hidden');
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
                                const strikesResp = await fetch(`/api/operator/${opId}/strikes`);
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
                detailsLoading.classList.add('hidden');
                loadDetailsBtn.classList.remove('hidden');
                loadDetailsBtn.textContent = 'Failed - Click to Retry';
            } finally {
                isLoadingDetails = false;
            }
        });
    </script>
</body>
</html>
        """

    return app
