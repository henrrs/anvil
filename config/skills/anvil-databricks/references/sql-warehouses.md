# SQL warehouse discovery and Statement Execution

Use SQL warehouses for SQL. `databricks warehouses list --output json` exposes warehouse ID, name, state, type, size, min/max clusters, and auto-stop minutes. If multiple suitable warehouses run, ask which one to use. If all are stopped, request approval before any start. Anvil's adapter never starts, stops, resizes, or edits warehouses.

The helper calls the [Statement Execution API](https://docs.databricks.com/api/statement-execution/v1/statement-execution) with `INLINE` / `JSON_ARRAY`, a 100-row cap, and a 1 MB byte cap. It polls `PENDING` and `RUNNING`, returns results only for `SUCCEEDED`, and treats `FAILED`, `CANCELED`, `CLOSED`, timeout, or permission errors as non-success. It asks the API to cancel after a local timeout. It does not use external result links.

Use parameters when user data becomes SQL values. For example:

```bash
python3 "$XDG_CONFIG_HOME/opencode/scripts/databricks.py" sql \
  --warehouse-id WAREHOUSE_ID \
  --parameters-json '[{"name":"job_id","type":"BIGINT","value":"123"}]' \
  'SELECT job_id FROM system.lakeflow.jobs WHERE job_id = :job_id LIMIT 10'
```

The helper rejects common DDL/DML/configuration statements unless the user directly approved the mutation and the caller passes `--allow-mutation`. Use that switch only after approval at the point of action. A SQL endpoint returning HTTP success does not establish query success; inspect the statement state.
