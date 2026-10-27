# Evidence and experiment record

Record symptom/window, code/query identity, runtime/version, input rows/bytes/types/distribution, executor resources, physical/adaptive plan, stage/task quantiles and retry/spill/GC/shuffle evidence available. Mark missing fields UNKNOWN rather than inventing counters.

Compare hypotheses explicitly. For low CPU and slow ingestion, source waits, Python conversion and scheduling predict different timelines. Ask for the smallest discriminating measurement, such as source-only versus conversion-only throughput or task bytes versus duration. For shuffle-heavy tails, compare key/partition distribution and fetch wait before prescribing skew treatment.

Each experiment states mechanism, one changed factor, expected discriminating result, correctness/resource constraints and repeated baseline/candidate measurements. Keep startup/cache state, data scale and output semantics comparable. Report observed change and limitations; a projection is not a measured speedup. Stop investigation when dominant mechanism and safe action have sufficient evidence, then verify the intervention.

Source: [Spark monitoring](https://spark.apache.org/docs/latest/monitoring.html). Runtime UI/event-log evidence is authoritative for the actual workload.
