# Long-tail discrimination

Compare p50/p95/max task duration with bytes, records and partition/key distribution. A task taking ten times longer with similar input could reflect slow source ranges, executor health, retry, GC or remote I/O rather than key skew. Check placement and repeated behavior before naming the cause.

If evidence supports skew, inspect heavy/null keys, join multiplicity and aggregation behavior. AQE skew handling, a different join strategy or carefully bounded salting can be experiments, not automatic prescriptions. Salting changes keys and may require a second aggregation or replicated join side; prove result equivalence and quantify extra work.

Source query ranges can be imbalanced even when Spark's downstream shuffle is balanced. A source-side distribution correction belongs at that boundary. Compare critical-path task reduction, total resource cost and output correctness across repeated runs.

Source: [Spark adaptive skew handling](https://spark.apache.org/docs/latest/sql-performance-tuning.html#adaptive-query-execution).
