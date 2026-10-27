# Delta physical path

Separate scan/listing/metadata, pruning/data skipping, physical file reads, shuffle, write tasks and transaction/commit time. Inspect actual files and sizes, partition/clustering layout, filter selectivity, read/write bytes and commit timeline. Many small files, a slow merge, poor pruning and a hot output partition are different mechanisms.

File sizing, compaction, clustering and repartitioning change costs elsewhere. Verify downstream reads, write amplification and concurrency/correctness before accepting a faster isolated stage. A table property or optimization command is not proof that the query prunes data. Do not prescribe vacuum or compute mutations as harmless performance experiments.

Load the existing `anvil-delta-lake` skill for transaction, CDC, retention and table-correctness decisions; keep this reference focused on measured physical performance. Engine/version support must come from the deployed runtime and official documentation.

Source: [Delta Lake best practices](https://docs.delta.io/latest/best-practices.html).
