from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext
from typing import Any

getcontext().prec = 28
CENT = Decimal("0.01")


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Converte entradas comuns de dinheiro para Decimal em reais."""
    if value is None or value == "":
        return default

    if isinstance(value, Decimal):
        return value

    if isinstance(value, int):
        return Decimal(value)

    if isinstance(value, float):
        return Decimal(str(value))

    text = str(value).strip()
    if not text:
        return default

    text = text.replace("R$", "").replace(" ", "")

    # Formato brasileiro: 1.234,56
    if "," in text:
        text = text.replace(".", "").replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def decimal_to_cents(value: Any) -> int:
    """Converte valor em reais para centavos inteiros."""
    dec = to_decimal(value)
    cents = (dec * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def cents_to_decimal(cents: Any) -> Decimal:
    if cents is None or cents == "":
        return Decimal("0")
    return (Decimal(int(cents)) / Decimal("100")).quantize(CENT)


def cents_to_float(cents: Any) -> float:
    return float(cents_to_decimal(cents))


def format_money(value: Any) -> str:
    """Formata valor em reais como R$ 1.234,56."""
    dec = to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    formatted = f"{dec:,.2f}"
    return "R$ " + formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_cents(cents: Any) -> str:
    return format_money(cents_to_decimal(cents))


def row_money_to_cents(row: dict[str, Any], cents_field: str, legacy_field: str) -> int:
    """Lê campo em centavos quando existir, senão usa campo legado em reais."""
    if row.get(cents_field) is not None:
        return int(row[cents_field])
    return decimal_to_cents(row.get(legacy_field, 0))
