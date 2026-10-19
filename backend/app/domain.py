from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

Money = Decimal
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InquiryInput(Input):
    customer_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=20000)


class LineInput(Input):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, le=1000000, max_digits=10, decimal_places=3)
    unit: str = Field(min_length=1, max_length=20)
    unit_price: Decimal | None = Field(
        default=None, ge=0, le=100000000, max_digits=11, decimal_places=2
    )


class DraftInput(Input):
    expected_revision: int = Field(ge=0)
    lines: list[LineInput] = Field(min_length=1, max_length=100)
    discount: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    payment_terms: str = Field(min_length=1, max_length=300)
    comments: str = Field(default="", max_length=2000)


class Approval(Input):
    revision: int = Field(gt=0)


def calculate(lines: list[dict], discount: Decimal, vat_rate: Decimal) -> dict:
    """Цены без НДС. Округление каждой строки до копеек, НДС от суммы строк."""
    subtotal = Decimal(0)
    net = Decimal(0)
    result = []
    for line in lines:
        gross = money(Decimal(line["unit_price"]) * Decimal(line["quantity"]))
        reduction = money(gross * discount / 100)
        amount = gross - reduction
        subtotal += gross
        net += amount
        result.append(
            {**line, "gross": str(gross), "discount_amount": str(reduction), "amount": str(amount)}
        )
    vat = money(net * vat_rate / 100)
    return {
        "lines": result,
        "subtotal": str(subtotal),
        "discount": str(discount),
        "discount_amount": str(subtotal - net),
        "net": str(net),
        "vat_rate": str(vat_rate),
        "vat": str(vat),
        "total": str(net + vat),
        "currency": "RUB",
    }
