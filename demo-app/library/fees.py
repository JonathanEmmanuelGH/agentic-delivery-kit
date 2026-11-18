"""Late fees. Money is Decimal, quantized once, half up."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

DAILY_FEE = Decimal("0.25")
FEE_CAP = Decimal("10.00")
CENT = Decimal("0.01")


def late_fee(days_late: int, daily_fee: Decimal = DAILY_FEE, cap: Decimal = FEE_CAP) -> Decimal:
    """Fee for a return `days_late` days after the due date, capped, in whole cents."""
    if days_late < 0:
        raise ValueError("days_late cannot be negative")
    fee = min(Decimal(days_late) * daily_fee, cap)
    return fee.quantize(CENT, rounding=ROUND_HALF_UP)
