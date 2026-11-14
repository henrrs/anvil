import unittest

from invoice_report import build_invoice


class InvoicePublicTests(unittest.TestCase):
    def test_basic_invoice(self):
        result = build_invoice("acme", [{"description": "part", "unit_price": 10, "quantity": 2}])
        self.assertEqual(result["total"], 21.65)
        self.assertEqual(result["text"].splitlines()[0], "Invoice for acme")

    def test_pending_rows_are_opt_in_and_untaxed(self):
        rows = [{"description": "pending", "unit_price": 3, "status": "pending"}]
        self.assertEqual(build_invoice("acme", rows)["items"], [])
        report = build_invoice("acme", rows, include_pending=True)
        self.assertEqual(report["items"][0]["tax"], 0.0)

    def test_rejects_unknown_tax_code(self):
        with self.assertRaises(ValueError):
            build_invoice("acme", [], tax_code="special")


if __name__ == "__main__":
    unittest.main()
