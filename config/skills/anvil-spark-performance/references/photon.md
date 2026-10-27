# Native execution applicability

Photon is a Databricks execution capability, not an explanation for arbitrary Spark/Python/source behavior. Establish whether it is enabled and which operators use it in the actual query profile. Native columnar execution, fallback boundaries, Python code and external database reads can have different dominant costs.

Do not promise that enabling Photon accelerates a Python function, JDBC wait or unsupported operator. Compare equivalent plans/inputs and identify native versus fallback work, conversion costs and end-to-end timing. A faster supported stage may leave overall latency unchanged if source extraction or startup dominates.

Use current official support/limitations for the deployed Databricks runtime and compute type. Treat proprietary implementation claims beyond documented/observed behavior as UNKNOWN. Domain applicability does not assign architecture ownership or authorize compute changes/cost.

Source: [Databricks Photon](https://docs.databricks.com/aws/en/compute/photon).
