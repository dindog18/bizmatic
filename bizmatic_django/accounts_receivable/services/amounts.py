"""Line arithmetic shared by AP/AR setup tests, imports and reconciliation."""

from decimal import Decimal, ROUND_HALF_UP, localcontext

CENT = Decimal("0.01")
ZERO = Decimal("0")


def line_amount_difference(line, quantity_field):
    # Line discounts and tax are amounts, not rates. Header charges are checked separately.
    # Two 18-digit quantity/price fields can exceed the default Decimal precision.
    with localcontext() as amount_context:
        amount_context.prec = 40
        expected = (getattr(line, quantity_field) * line.unit_price
                    - line.discount_amount + line.tax_amount).quantize(CENT, rounding=ROUND_HALF_UP)
        return abs(line.line_total - expected)


def line_amount_issues(line, quantity_field, tolerance=CENT):
    """Describe inconsistent source values without changing the extracted evidence."""
    issues = []
    if getattr(line, quantity_field) <= ZERO:
        issues.append(f"Line {line.line_no} needs a positive quantity before it can be matched.")
    if line_amount_difference(line, quantity_field) > tolerance:
        issues.append(f"Line {line.line_no}: quantity, unit price, discount and tax do not agree with its total.")
    return issues
