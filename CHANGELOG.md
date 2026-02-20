# Changelog

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
