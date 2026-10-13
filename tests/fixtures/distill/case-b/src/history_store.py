def save_version(connection, key, body):
    """Active path: retire the prior version, then append the next version."""
    connection.execute("UPDATE history SET current = 0 WHERE key = ? AND current = 1", (key,))
    connection.execute("INSERT INTO history (key, body, current) VALUES (?, ?, 1)", (key, body))
