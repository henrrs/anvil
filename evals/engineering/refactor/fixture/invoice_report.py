"""Legacy invoice reporting module; callers depend on this import and result shape."""

TAX_RATES = {"standard": 0.0825, "reduced": 0.025, "none": 0.0}


def build_invoice(customer_id, items, tax_code="standard", discount=0.0, include_pending=False):
    if not isinstance(customer_id, str) or not customer_id.strip():
        raise ValueError("customer_id is required")
    if tax_code not in TAX_RATES:
        raise ValueError("unsupported tax code")
    try:
        discount_rate = float(discount)
    except (TypeError, ValueError) as exc:
        raise ValueError("discount must be numeric") from exc
    if discount_rate < 0 or discount_rate > 1:
        raise ValueError("discount must be between zero and one")

    rows = []
    subtotal = 0.0
    discount_total = 0.0
    tax_total = 0.0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each item must be a mapping")
        status = item.get("status", "posted")
        if status not in {"posted", "pending", "void"}:
            raise ValueError("unsupported item status")
        if status == "void" or (status == "pending" and not include_pending):
            continue
        try:
            quantity = int(item.get("quantity", 1))
            unit_price = float(item["unit_price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("item quantity and unit_price must be numeric") from exc
        if quantity <= 0 or unit_price < 0:
            raise ValueError("quantity and unit_price must be non-negative and quantity must be positive")
        line_subtotal = round(quantity * unit_price, 2)
        line_discount = 0.0 if status == "pending" else round(line_subtotal * discount_rate, 2)
        taxable = round(line_subtotal - line_discount, 2)
        rate = 0.0 if item.get("tax_exempt", False) or status == "pending" else TAX_RATES[tax_code]
        line_tax = round(taxable * rate, 2)
        subtotal = round(subtotal + line_subtotal, 2)
        discount_total = round(discount_total + line_discount, 2)
        tax_total = round(tax_total + line_tax, 2)
        rows.append({"description": str(item.get("description", "")), "status": status,
                     "quantity": quantity, "unit_price": round(unit_price, 2),
                     "subtotal": line_subtotal, "discount": line_discount, "tax": line_tax,
                     "total": round(taxable + line_tax, 2)})

    total = round(subtotal - discount_total + tax_total, 2)
    text = [f"Invoice for {customer_id}"]
    text.extend(f"{row['description']}: {row['total']:.2f}" for row in rows)
    text.append(f"Total: {total:.2f}")
    return {"customer_id": customer_id, "tax_code": tax_code, "items": rows,
            "subtotal": subtotal, "discount": discount_total, "tax": tax_total,
            "total": total, "text": "\n".join(text)}
