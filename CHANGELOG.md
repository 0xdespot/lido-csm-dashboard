# Changelog

## [Unreleased]

### Fixed
- **Distribution History stopped in April and silently dropped the newest frames** — The distribution log format gained a versioned envelope (`{"_ver": 1, "frames": [...]}`) in place of a bare top-level frame object. The parser only understood the legacy shape, so every log in the new format was discarded and the table simply ended early. Logs are now normalised through `normalize_log_frames`, which reads both shapes and keeps *every* frame in the list (the versioned format permits more than one per CID). For operator 457 this took the history from 6 frames ending 2026-04-13 to 11 frames ending 2026-08-31.
- **The versioned format quotes wei amounts as strings, which blanked the whole history** — `distributed_rewards` arrives as `"425672527568186470"` rather than an int. It flowed unconverted into `sum(...)` in the APY calculation, raising a `TypeError` that the surrounding broad `except Exception` swallowed into an empty frame list. Values are now coerced to `int`, and an unparseable one logs a warning and counts as 0 instead of taking the section down.
- **All three default IPFS gateways were failing at once** — `dweb.link` and `ipfs.io` are both Protocol Labs and rate-limit (HTTP 429) together, and `w3s.link` was refusing connections, so recent distribution logs could not be fetched at all. A gateway on separate infrastructure is appended to the default list as a fallback. A non-200 gateway response is also logged now; previously it was skipped in silence, so a fleet-wide 429 looked exactly like a missing CID.
- **A malformed IPFS log hung the request forever** — `get_frame_info` falls back to `(0, 0)` when a log lacks or malforms its `frame` key, making the frame length zero. The next-distribution estimate then stepped forward by zero epochs in an unbounded `while`, pinning a worker thread at 100% CPU with no request timeout anywhere to break it. The estimate is now the testable `estimate_next_distribution_date`, which returns `None` for a non-positive frame length and records a `data_warnings` entry.
- **A bad gateway response became sticky on disk** — `fetch_log` cached whatever it received, so one truncated or error payload poisoned the cache permanently. Payloads are now shape-checked before being written, rejected on read if they were written before this check existed, and a malformed response falls through to the next gateway instead of being accepted.
- **HTTP 503/500 were displayed as "No history available"** — the History and Withdrawals panels collapsed every failed request into the grey empty state and discarded `data.detail`, making a dead or rate-limited RPC indistinguishable from an operator with no data. Both now show the real message (the RPC-unreachable handler already composes an actionable one) and leave the panel unloaded so the button retries rather than flipping to "Hide".
- **`data_warnings` was returned by every endpoint and rendered nowhere** — only the CLI displayed them, so "Failed to fetch 18/24 distribution logs from IPFS" was invisible in the browser. A yellow banner now accumulates and de-duplicates warnings across the separate history and withdrawal fetches.
- **Withdrawal History showed no total for saved operators** — the total row existed only in the live "Load Withdrawals" path; the cached saved-operator path held a near-identical copy of the render code that omitted it (and had already drifted in how it styled the type column). Both paths now share one `renderWithdrawals`, so the total cannot go missing or diverge again. In-flight unstETH requests are reported on their own line rather than being folded into the claimed total, matching the CLI.
- **Nothing persisted across container restarts on Unraid** — the template mapped appdata to `/app/data`, which the application never writes to; the operator database, discovered-CID cache and IPFS log cache all live under `~/.cache/csm-dashboard`. Every restart therefore re-ran full CID discovery and re-fetched every IPFS log. The template now maps the directory actually used, and all four caches derive from a single `CACHE_DIR` setting.

### Added
- **`ETH_RPC_URL` accepts a comma-separated list with automatic failover** — endpoints are tried in order, the winner is memoized for 5 minutes, and the memo is dropped the moment a call fails at the transport level, so the next request fails over instead of pinning a dead node for the rest of the TTL. Intended for a self-hosted node whose address moves (a DAppNode on DHCP) with a public endpoint as the last entry. A single configured endpoint short-circuits without a probe, so the common case costs nothing. Mirrors the existing `ipfs_gateways` pattern, and the "all endpoints failed" error names every host tried with API keys stripped.
- **`HOST` and `PORT` are settings like everything else** — previously the port was a hardcoded `typer.Option(8080)` plus a hardcoded `--port 3000` in the Docker CMD, and the `PORT` variable in `docker-compose.yml` only remapped the host side of the published port without ever reaching the container. Precedence is now `--port` flag > `PORT` env > `.env` > default. The image sets `HOST=0.0.0.0`/`PORT=3000` as defaults that `docker run -e PORT=…` overrides, its healthcheck follows `$PORT`, and compose moves both sides of the mapping together.
- **`CACHE_DIR` relocates every on-disk cache at once** — the operator database, discovered-CID cache, IPFS log cache and strikes cache all derive from it. An explicit `DATABASE_PATH` still wins for the database alone.

## [0.6.3] - 2026-06-27

### Fixed
- **Unreachable RPC node crashed requests with an opaque 500 + traceback** — When the configured `ETH_RPC_URL` node was down (connection refused, DNS failure, timeout), web3 contract calls raised a raw `requests.exceptions.ConnectionError` that bubbled through the FastAPI route and was dumped as a full Python traceback behind a generic HTTP 500. Transport-level failures are now detected (`is_connection_error` walks the exception cause/context chain) and translated into a typed `RPCUnavailableError`, which a FastAPI exception handler renders as **HTTP 503** with an actionable body — `Ethereum RPC node unreachable at <host>. Check that the node is running and ETH_RPC_URL is correct.` — shown directly in the dashboard's error banner. The host is sanitized to `scheme://host:port`, so an API key embedded in the RPC URL is never leaked, and a single WARNING is logged instead of a traceback.
- **A dead node masqueraded as "operator not found" on the address-lookup path** — `find_operator_by_address` swallowed all exceptions and ground through every operator, so an unreachable node returned a slow, misleading 404. Connection failures now short-circuit to the 503. Likewise `get_bond_curve_id` no longer silently reports curve `0`, and the best-effort APY / capital-efficiency / strikes / withdrawal-enrichment steps re-raise connection failures instead of degrading to partial data. Genuinely degraded conditions (pruned receipts, unsupported batch, single bad block) keep their existing graceful handling.

### Added
- **CLI surfaces unreachable nodes cleanly** — Instead of a traceback, `csm rewards` prints `RPC node unreachable at <host> — check ETH_RPC_URL / --rpc` (or `{"error": ...}` in `--json` mode) and exits 1.

## [0.6.2] - 2026-05-23

### Fixed
- **Capital Efficiency section silently missing for operators on RPC nodes with receipt pruning** — `get_bond_event_history` scans from CSM deployment block (20,873,000) in chunks; on nodes that prune transaction receipts (Nethermind's default, Geth in hybrid mode, etc.), the first chunks fail with `-32000 "Receipt not available"`, the 3-strike abort fires, and `bond_events` returns `[]`. `apy.capital_efficiency` is then dropped from the saved-operator JSON and the dashboard hides the section without explanation. The scan now distinguishes pruned-receipt errors (skip the chunk, don't count toward strikes) from real RPC failures (abort and surface a `data_warnings` entry + WARNING log). For operators created after the prune cutoff, all bond events are now collected even on pruned nodes.
- **Empty bond_events result cached for a full hour** — A scan that produced `[]` was held in the 1h `@cached(ttl=3600)` decorator, so even after fixing the underlying issue a stale empty result lingered. Caching is now inline with a conditional TTL: 3600s for non-empty results, 60s for empty results, so retries can recover quickly.

### Changed
- **Bond event scan is ~13x faster on the uncached path.** Three changes combine: (1) the caller now passes a `start_block` derived from the operator's earliest distribution frame (with a 6-month safety margin) instead of scanning from CSM deployment; (2) chunk size raised from 10k to 50k blocks, consistent with other event scans; (3) the 8 bond event types are now scanned in parallel via `asyncio.gather` instead of sequentially. Measured against a local Nethermind RPC for an active operator (220 validators, 18 bond events), the uncached scan went from ~16 minutes to ~73 seconds. Cached results still hit in <1ms.
- Bond event scan abort now logs at WARNING (was DEBUG) so the failure is visible at the default INFO log level.

## [0.6.1] - 2026-05-21

### Fixed
- **False "distribution history incomplete" warning on RPC-only setups** — `get_distribution_log_history` only marked results complete when the Etherscan path succeeded, so a fully successful RPC fallback scan still emitted the *"may be incomplete… Configure etherscan_api_key"* warning and cached for only 5 minutes instead of 1 hour. `_query_events_chunked` now reports whether it scanned the full block range without hitting the consecutive-failure abort; a clean RPC scan is treated as complete. Genuinely failed scans still warn.

### Added
- **RPC endpoint startup log** — On first connection, the active RPC endpoint, chain ID, and head block are logged once per process (e.g. `RPC connected: http://localhost:8545 (chain_id=1, block=25,146,605)`), making it easy to confirm a self-hosted node is actually in use. A non-mainnet chain ID is flagged. Only the host is logged — API keys embedded in the RPC URL are never written to logs, including on connection failures. A connectivity check failure warns but is non-fatal.

## [0.6.0] - 2026-04-15

### Fixed
- **Etherscan API completely broken since v0.5.1** — `hexbytes` 1.3.1 changed `.hex()` to no longer include the `0x` prefix, causing all Etherscan event queries to return "Invalid topic0 length". Switched all 4 query methods to use `.to_0x_hex()` which is the stable API for prefixed hex output. This was the primary cause of missing distribution history.
- **Distribution history gaps for recent months** — Restructured the distribution discovery pipeline to merge all available data sources (known CIDs, persistent cache, Etherscan, RPC, and on-chain contract state) instead of a fragile sequential fallback. The current distribution from the contract is now always included.
- **RPC event scanning too fragile** — Increased chunk size from 10k to 50k blocks, added adaptive chunk sizing on failure, exponential backoff, and raised the abort threshold from 3 to 10 consecutive failures.
- **Incomplete results cached too long** — Distribution history with incomplete data now caches for 5 minutes instead of 1 hour, allowing faster recovery.
- **Silent data quality failures** — Added `data_warnings` field to API responses and yellow CLI warnings when distribution data may be incomplete (Etherscan unavailable, RPC scan aborted early, etc.)
- **Warning snapshot bleeding across concerns** — Discovery warnings are now tracked locally and only discovery-related warnings are cached for re-emission.

### Added
- **Persistent CID discovery cache** — Discovered distribution CIDs are now saved to `~/.cache/csm-dashboard/discovered_cids.json` and reused across restarts, eliminating redundant scanning.
- **IPFS fetch failure tracking** — `get_operator_history()` now reports how many IPFS log fetches failed, surfaced as a data warning when non-zero.
- **Data warnings in API and CLI** — New `data_warnings` array in API responses and stderr warnings in CLI when data quality issues are detected.

## [0.5.0] - 2026-03-07

### Added
- **Capital efficiency tracking** — New dashboard section showing CSM XIRR (cash-flow IRR accounting for exact timing of deposits, claims, and distributions), annualized simple return, stETH holding benchmark, and CSM advantage ratio
- **Saved operator database** — SQLite-backed persistence for followed operators with full history and withdrawal data cached locally
- **Version single source of truth** — Version string now sourced from package metadata (`importlib.metadata`), eliminating duplication

### Fixed
- **XIRR calculation** — Corrected cash-flow model to include bond claims, split claimed/unclaimed rewards correctly, and use proper terminal value
- **Cache `None` bug** — `@cached` decorator now correctly caches `None` return values (previously re-called the function on every request for failed/not-found lookups)
- **DB init race condition** — `init_db()` now uses `asyncio.Lock` with double-checked locking to prevent concurrent initialization errors under parallel startup requests
- **IPFS rate limiter** — Lock is now released before sleeping, allowing concurrent coroutines to schedule their time slots in parallel instead of serializing behind a 1-second sleep

### Changed
- **Rate limiting on save/refresh** — `POST /operator/{id}/save` and `POST /operator/{id}/refresh` now enforce a 60-second per-operator cooldown to prevent hammering external APIs
- **Timestamps** — Database timestamps now use timezone-aware `datetime.now(timezone.utc)` (replaces deprecated `datetime.utcnow()`)
- **Code deduplication** — Extracted `_build_operator_data_dict()` helper in routes, eliminating ~110 lines of duplicated serialization logic between save and refresh endpoints

## [0.4.3] - 2026-02-20

### Changed
- **Bond APY now uses on-chain data** — Historical stETH APR is fetched directly from `TokenRebased` events via RPC, replacing the previous The Graph subgraph dependency. Bond APY per distribution frame now works out of the box with no extra API keys.

### Removed
- `THEGRAPH_API_KEY` configuration option (no longer needed; existing `.env` files with it are safely ignored)

## [0.4.2] - 2026-02-17

### Added
- Operator identifier parsing with Ethereum address validation via Web3
- Validator pubkey validation to filter malformed entries from strikes data

### Fixed
- XSS vulnerability in strikes detail rendering — replaced innerHTML with DOM APIs

## [0.4.1] - 2026-02-14

### Changed
- Improved distribution event fetching with hybrid approach
- Added new distribution log entries

## [0.3.6] - 2026-01-22

### Added
- Retry logic and rate limiting for validator batch fetching

## [0.3.5] - 2026-01-05

### Added
- **Web:** Withdrawal History section with Load/Hide button toggle
- **Web:** Distribution History section with Load/Hide button toggle
- **Web:** Next Distribution info (estimated date and rewards)
- **Web:** Favicon support

### Fixed
- **CLI/Web:** unstETH withdrawals now correctly show as "unstETH" type with ETH amounts
- **CLI:** Added total row to Withdrawal History table

### Changed
- **Web:** History toggles changed from checkboxes to buttons for better UX

## [0.3.4] - 2025-12

### Added
- unstETH (Lido Withdrawal NFT) tracking for `claimRewardsUnstETH` claims
- Withdrawal status tracking (Pending/Ready/Claimed)

## [0.3.3] and earlier
- See git history for previous changes
