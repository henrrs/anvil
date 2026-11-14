# SE-02 — Behavior-preserving invoice reporting refactor

Refactor the existing invoice reporting component into small, cohesive modules while
preserving its public import, function signature, output shape, rounding, ordering,
filtering, and error behavior. Existing callers import `invoice_report` from
`invoice_report.py` and call `build_invoice(customer_id, items, tax_code="standard",
discount=0.0, include_pending=False)`.

Keep the facade import-compatible. Separate amount/discount calculations, tax policy,
and report formatting so each rule has one clear owner. Use only the Python standard
library. Do not add a framework, change the input schema, or broaden the accepted tax
codes. Keep calculations deterministic and avoid mutating caller-owned rows.

Run the public tests and add focused tests for any behavior that was not already
covered. Explain which compatibility cases you checked and any limitations.
