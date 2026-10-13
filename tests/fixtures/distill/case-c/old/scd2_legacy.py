def obsolete_update(connection, key, body):
    # Unused historical SCD2 draft. No active imports or callers.
    connection.execute("UPDATE records SET current = 0 WHERE key = ?", (key,))
    connection.execute("INSERT INTO records (key, body, current) VALUES (?, ?, 1)", (key, body))
