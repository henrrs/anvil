# Databricks SQL providers

The CLI is the preferred SQL provider. When it is unavailable, Anvil uses the official Python SDK's Statement Execution API. If SDK SQL execution is unavailable and the SQL Connector is already present, Anvil can use the official SQL Connector when the active warehouse exposes supported connection metadata.

Anvil verifies that the requested warehouse is visible and running before submitting SQL. It never starts a stopped warehouse. Results are normalized to columns, rows, state, and truncation metadata; output is bounded to 100 rows and 1 MB. Potentially mutating statements require direct user approval and an explicit adapter flag. System-table queries remain read-only by default.

The SQL Connector is specialized and is not installed by default because SDK Statement Execution already covers Anvil's current SQL use. The connector path uses supported OAuth U2M authentication and the selected Unified Authentication profile; it does not persist credentials. If connection metadata or auth mode is unsupported, Anvil reports the limitation instead of pretending the query succeeded.

References: [Statement Execution API](https://docs.databricks.com/api/statement-execution/v1/statement-execution), [Python SQL Connector](https://docs.databricks.com/aws/en/dev-tools/python-sql-connector), and [Unified Authentication](https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth).
