def append_event(connection, event):
    connection.execute("INSERT INTO events (event_id, payload) VALUES (?, ?)", (event.id, event.payload))
