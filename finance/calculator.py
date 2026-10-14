"""Kosten- en winstcalculator.

Pure functies zonder database, zodat de rekenregels los te testen zijn.

Rekenregels
-----------
- Alle bedragen zijn `Decimal`; floats worden geweigerd.
- Commissie en betaalkosten worden berekend over het totaal dat de koper
  betaalt (verkoopprijs + verzendopbrengst), zoals eBay dat doet.
- Elke kostenpost wordt afzonderlijk afgerond op hele centen met
  ROUND_HALF_UP. Netto-opbrengst en winst zijn sommen van afgeronde posten,
  dus er ontstaan geen "zwevende" halve centen.
- Marge = winst / bruto-opbrengst * 100, afgerond op 0,1 procentpunt.
  Bij een bruto-opbrengst van nul is de marge `None`.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def money(value) -> Decimal:
    """Rond af op centen volgens de vaste afrondingsregel."""
    return _dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _dec(value) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Gebruik Decimal of str voor bedragen, geen float.")
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
    """Laagste vraagprijs (in centen) waarbij de winst minstens `target_profit` is.

    Eerst wordt de prijs algebraïsch geschat; daarna wordt per cent
    gecorrigeerd voor afrondingseffecten. Omdat de winst per extra cent
    met hooguit één cent verandert, levert dit precies de doelwinst op.
    """
    target = money(target_profit)
    rate = fees.total_rate
    if rate >= 1:
        raise ValueError("Kostenpercentage van 100% of meer: geen prijs mogelijk.")

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

    # Omlaag zolang het nog net kan, daarna omhoog tot de doelwinst gehaald is.
    while price > ZERO and profit_at(price - CENT) >= target:
        price -= CENT
    while profit_at(price) < target:
        price += CENT
    return price
