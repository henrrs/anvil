# Plans and adaptive decisions

Compare analyzed/optimized logical plans with initial and final physical plans. Check statistics, filter/projection pushdown, join cardinality and the actual build side before blaming an optimizer choice. A broadcast hint requires measured build size and executor-memory headroom; it is not a generic escape from shuffle.

AQE can revise eligible execution choices from runtime statistics, including post-shuffle partition sizing and supported skew/join decisions. Verify effective settings, runtime version and final plan. AQE cannot repair an external query bottleneck, invent source partitioning or optimize arbitrary Python code. Changes to partition settings may be overridden or transformed adaptively; inspect resulting task sizes.

Experiment with a representative query and equivalent cache/input state. Compare operator/stage duration, shuffle, task distribution and output correctness. Missing or inaccurate statistics and changed cardinality are competing hypotheses; gather discriminating evidence before applying hints.

Source: [Spark SQL performance tuning](https://spark.apache.org/docs/latest/sql-performance-tuning.html).
