def run_sync(source, sink, checkpoint, page_size=100):
    cursor = checkpoint.sequence
    processed = 0
    while True:
        page = source.page(cursor, page_size)
        if not page:
            return {"processed": processed, "sequence": cursor}
        for event in page:
            checkpoint.save(event.sequence)
            sink.commit(event)
            cursor = event.sequence
            processed += 1
