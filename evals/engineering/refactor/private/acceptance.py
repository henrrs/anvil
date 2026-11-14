"""Private compatibility grader. Kept outside the model-visible fixture tree."""
import importlib
import math
import pathlib
import sys


def compatibility():
    from invoice_report import build_invoice
    assert tuple(__import__("inspect").signature(build_invoice).parameters) == (
        "customer_id", "items", "tax_code", "discount", "include_pending")
    cases = [
        ("c-1", [{"description": "a", "unit_price": 0.1, "quantity": 3}], "standard", 0.0, False,
         (0.30, 0.0, 0.32)),
        ("c-2", [{"description": "x", "unit_price": 5.555, "quantity": 2},
                 {"description": "y", "unit_price": 4, "quantity": 1, "tax_exempt": True}],
         "reduced", 0.1, False, (15.11, 1.51, 13.85)),
        ("c-3", [{"description": "p", "unit_price": 7, "status": "pending"},
                 {"description": "v", "unit_price": 9, "status": "void"}],
         "standard", 0.5, True, (7.0, 0.0, 7.0)),
        ("c-4", [{"description": "zero", "unit_price": 0, "quantity": 1}], "none", 1.0, False,
         (0.0, 0.0, 0.0)),
    ]
    for customer, rows, tax_code, discount, include_pending, expected in cases:
        before = [dict(item) for item in rows]
        result = build_invoice(customer, rows, tax_code, discount, include_pending)
        assert (result["subtotal"], result["discount"], result["total"]) == expected
        assert result["customer_id"] == customer and result["tax_code"] == tax_code
        assert result["text"].splitlines()[0] == f"Invoice for {customer}"
        assert rows == before, "input rows were mutated"
    for values in [("", []), ("c", [], "unknown"), ("c", [], "standard", -0.1),
                   ("c", [{"unit_price": -1}]), ("c", [None])]:
        try:
            build_invoice(*values)
        except (ValueError, TypeError):
            continue
        raise AssertionError(f"invalid input accepted: {values!r}")


def boundaries():
    for module_name, forbidden in (("pricing", ("taxes", "rendering", "invoice_report")),
                                   ("taxes", ("pricing", "rendering", "invoice_report")),
                                   ("rendering", ("pricing", "taxes", "invoice_report"))):
        module = importlib.import_module(module_name)
        source = pathlib.Path(module.__file__).read_text()
        for dependency in forbidden:
            assert f"import {dependency}" not in source and f"from {dependency}" not in source, (module_name, dependency)
    facade = pathlib.Path("invoice_report.py").read_text()
    assert "def build_invoice" not in facade, "legacy facade still owns the full implementation"
    for name in ("pricing.py", "taxes.py", "rendering.py"):
        assert pathlib.Path(name).is_file(), f"missing cohesive module {name}"


if __name__ == "__main__":
    {"all": lambda: (compatibility(), boundaries()), "compatibility": compatibility,
     "boundaries": boundaries}[sys.argv[1]]()
    print("PASS refactor acceptance")
