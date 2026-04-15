# Changelog

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
