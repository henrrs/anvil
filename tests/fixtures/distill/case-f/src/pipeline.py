import json
from pathlib import Path

JOB_CONFIG = json.loads((Path(__file__).parents[1] / "config" / "job.json").read_text())


def build_customer_pipeline():
    return IngestionPipeline(num_partitions=JOB_CONFIG["numPartitions"])
