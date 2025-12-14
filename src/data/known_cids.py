"""Known historical distribution log CIDs as fallback.

These are manually curated from on-chain DistributionLogUpdated events.
Used when neither Etherscan API nor RPC event queries are available.

To update this list:
1. Query events from Etherscan or a full node
2. Add new entries in chronological order (oldest first)

Last updated: December 2025
"""

# Format: {"block": block_number, "logCid": "Qm..."}
KNOWN_DISTRIBUTION_LOGS: list[dict] = [
    # CSM launched Dec 2024, first distribution frame ~Jan 2025
    {"block": 21277898, "logCid": "QmezkGCHPUJ9XSAJfibmo6Sup35VgbhnodfYsc1xNT3rbo"},
    {"block": 21445874, "logCid": "Qmb5CZUD9uLXP9LS68jnJp1v2GTF1KjYsNLJuML9fpRufE"},
    {"block": 21644860, "logCid": "QmePUqG8tMXbv3eHDu3j56Dod4gwmGh1Vapsh7u4gxotT4"},
    {"block": 21859279, "logCid": "QmT5JWn3sR7fYxxxSh3kHBmjZyPBWjKb6CsSLGXMQbLXMX"},
    {"block": 22047254, "logCid": "QmWxANi2GWvoxwnPRsxwZNF6NRyjwMBPAF4bBMcL3HGG3i"},
    {"block": 22247841, "logCid": "QmYQPDuqVbxWq2YNSZS55LE3eTeriy51HTCgBHLiW9fN7N"},
    {"block": 22448016, "logCid": "QmeZduNqrnSMLTVE5tkNDv2WhtL3uAgHRP1915m5CHcCqM"},
    {"block": 22646060, "logCid": "QmaHU6Ah99Yk6kQVtSrN4inxqqYoU6epZ5UKyDvwdYUKAS"},
    {"block": 22847998, "logCid": "Qmemm9gD2fQgwNziBsf9mAaveNXJ3eJvHpqBTWKoLdUXXV"},
    {"block": 23048383, "logCid": "QmVgGQS7QBeRMq2noqqxekY5ezmqRsgu7JjiyMyRaaWEDv"},
    {"block": 23248929, "logCid": "QmaUC2HBv88mJ9Gf99hfNgtH4qo2F1yHaBMC4imwVhxDDi"},
    {"block": 23463926, "logCid": "QmPPFkydgtnwMBDF6nZZaU5nnqy3csbKts3UfRRgWXreEu"},
    {"block": 23649468, "logCid": "QmSdx8WFnaeMWLKURBYgMMiixZ9z4xn3mvGPBeuRzPt6MQ"},
    {"block": 23849500, "logCid": "QmZyzTYdSait7BYCEToFJFJ6qVkX2HJBrrvXhk64e82xoK"},
]
