"""Fee and profit calculator.

Pure functions without a database, so the arithmetic can be tested in
isolation.

Rules
-----
- All amounts are `Decimal`; floats are rejected.
- Commission and payment fees are charged on what the buyer pays
  (sale price + shipping charged), as eBay does.
- Each cost item is rounded to whole cents on its own with ROUND_HALF_UP.
  Net proceeds and profit are sums of rounded items, so no "floating"
  half cents appear.
- Margin = profit / gross * 100, rounded to 0.1 percentage point.
  With a gross of zero the margin is `None`.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def money(value) -> Decimal:
    """Round to cents using the fixed rounding rule."""
    return _dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Use Decimal or str for amounts, not float.")
    return value if isinstance(value, Decimal) else Decimal(value)


@dataclass(frozen=True)
class Fees:
    commission_percentage: Decimal
    fixed_fee: Decimal = ZERO
    payment_percentage: Decimal = ZERO

    @property
    def total_rate(self) -> Decimal:
        return (_dec(self.commission_percentage) + _dec(self.payment_percentage)) / HUNDRED


@dataclass(frozen=True)
class CostInput:
    sale_price: Decimal
    shipping_income: Decimal = ZERO
    shipping_cost: Decimal = ZERO
    packaging_cost: Decimal = ZERO
    purchase_cost: Decimal = ZERO


@dataclass(frozen=True)
class CostResult:
    gross: Decimal
    commission: Decimal
    payment_fee: Decimal
    shipping_cost: Decimal
    packaging_cost: Decimal
    net_proceeds: Decimal
    purchase_cost: Decimal
    profit: Decimal
    margin: Decimal | None

    @property
    def total_fees(self) -> Decimal:
        return self.commission + self.payment_fee

    @property
    def is_loss(self) -> bool:
        return self.profit < ZERO


def calculate(data: CostInput, fees: Fees) -> CostResult:
    sale_price = money(data.sale_price)
    shipping_income = money(data.shipping_income)
    shipping_cost = money(data.shipping_cost)
    packaging_cost = money(data.packaging_cost)
    purchase_cost = money(data.purchase_cost)

    gross = sale_price + shipping_income
    commission = money(gross * _dec(fees.commission_percentage) / HUNDRED) + money(
        fees.fixed_fee
    )
    payment_fee = money(gross * _dec(fees.payment_percentage) / HUNDRED)

    net = gross - commission - payment_fee - shipping_cost - packaging_cost
    profit = net - purchase_cost
    margin = None
    if gross != ZERO:
        margin = (profit / gross * HUNDRED).quantize(TENTH, rounding=ROUND_HALF_UP)

    return CostResult(
        gross=gross,
        commission=commission,
        payment_fee=payment_fee,
        shipping_cost=shipping_cost,
        packaging_cost=packaging_cost,
        net_proceeds=net,
        purchase_cost=purchase_cost,
        profit=profit,
        margin=margin,
    )


def required_price(
    target_profit: Decimal,
    fees: Fees,
    *,
    shipping_income: Decimal = ZERO,
    shipping_cost: Decimal = ZERO,
    packaging_cost: Decimal = ZERO,
    purchase_cost: Decimal = ZERO,
) -> Decimal:
    """Lowest asking price (in cents) at which profit is at least `target_profit`.

    The price is first estimated algebraically, then corrected cent by cent
    for rounding effects. Because profit changes by at most one cent per
    extra cent of price, this lands exactly on the target profit.
    """
    target = money(target_profit)
    rate = fees.total_rate
    if rate >= 1:
        raise ValueError("Fee percentage of 100% or more: no price can reach the target.")

    shipping_income = money(shipping_income)
    fixed_costs = money(fees.fixed_fee) + money(shipping_cost) + money(packaging_cost) + money(
        purchase_cost
    )
    gross_estimate = (target + fixed_costs) / (1 - rate)
    price = max(
        (gross_estimate - shipping_income).quantize(CENT, rounding=ROUND_CEILING), ZERO
    )

    def profit_at(p):
        return calculate(
            CostInput(p, shipping_income, shipping_cost, packaging_cost, purchase_cost), fees
        ).profit

    # Step down while it still works, then up until the target is reached.
    while price > ZERO and profit_at(price - CENT) >= target:
        price -= CENT
    while profit_at(price) < target:
        price += CENT
    return price
