from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from calculos import money


def parse_iso_date(value: str | date | datetime | None) -> date | None:
    """
    Converte valores comuns de data para date.

    Aceita:
    - date
    - datetime
    - string ISO: YYYY-MM-DD
    - string ISO com horário: YYYY-MM-DD HH:MM:SS ou YYYY-MM-DDTHH:MM:SS
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    if not text:
        return None

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    """
    Converte valores comuns de data/hora para datetime.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()

    if not text:
        return None

    normalized = text.replace("T", " ")

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def format_date_br(value: str | date | datetime | None) -> str:
    """
    Formata data como DD/MM/YYYY.
    """
    parsed = parse_iso_date(value)

    if parsed is None:
        return "" if value is None else str(value)

    return parsed.strftime("%d/%m/%Y")


def format_datetime_br(value: str | datetime | None) -> str:
    """
    Formata data/hora como DD/MM/YYYY HH:MM.
    """
    parsed = parse_iso_datetime(value)

    if parsed is None:
        return "" if value is None else str(value)

    return parsed.strftime("%d/%m/%Y %H:%M")


def format_competencia(value: str | None) -> str:
    """
    Formata competência para exibição.

    Mantém valores especiais como:
    - 2025
    - 2024-2025

    Converte YYYY-MM para MM/YYYY.
    """
    if not value:
        return ""

    text = str(value).strip()

    parts = text.split("-")

    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2:
        return f"{parts[1]}/{parts[0]}"

    return text


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """
    Converte valores numéricos para Decimal com segurança.

    Aceita:
    - int
    - float
    - Decimal
    - string com ponto
    - string com vírgula decimal
    - string monetária simples
    """
    if value is None or value == "":
        return default

    if isinstance(value, Decimal):
        return value

    text = str(value).strip()

    if not text:
        return default

    text = text.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        try:
            return Decimal(str(float(value)))
        except Exception:
            return default


def format_money(value: Any, empty: str = "") -> str:
    """
    Formata valor monetário em reais.

    Usa a função money() do módulo calculos para manter consistência visual.
    """
    if value is None or value == "":
        return empty

    try:
        return money(float(value))
    except Exception:
        return empty


def format_number(value: Any, decimals: int = 2, empty: str = "") -> str:
    """
    Formata número com vírgula decimal no padrão brasileiro.
    """
    if value is None or value == "":
        return empty

    try:
        number = float(value)
    except Exception:
        return empty

    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_percent(value: Any, decimals: int = 4, empty: str = "") -> str:
    """
    Formata percentual com vírgula decimal.
    """
    if value is None or value == "":
        return empty

    return format_number(value, decimals=decimals, empty=empty)


def format_int(value: Any, empty: str = "0") -> str:
    """
    Formata inteiro para exibição.
    """
    if value is None or value == "":
        return empty

    try:
        return str(int(value))
    except Exception:
        return empty


def safe_text(value: Any, empty: str = "") -> str:
    """
    Retorna texto seguro para exibição.
    """
    if value is None:
        return empty

    text = str(value).strip()

    if not text:
        return empty

    return text


def truncate_text(value: Any, max_len: int = 60, empty: str = "") -> str:
    """
    Encurta texto longo sem quebrar a visualização da tabela.
    """
    text = safe_text(value, empty=empty)

    if len(text) <= max_len:
        return text

    return text[: max_len - 1].rstrip() + "…"


def status_badge_text(value: Any) -> str:
    """
    Normaliza status para exibição.
    """
    text = safe_text(value)

    if not text:
        return "—"

    return text


def devedor_label(devedor: dict[str, Any]) -> str:
    """
    Label humano para seletor de devedor.
    Não expõe ID interno.
    """
    nome = safe_text(devedor.get("nome"))
    documento = safe_text(devedor.get("documento"))

    if documento:
        return f"{nome} — {documento}"

    return nome


def public_ref(value: Any, fallback: str = "") -> str:
    """
    Exibe referência pública como TIT-..., REC-..., LOT-...
    """
    text = safe_text(value)

    if text:
        return text

    return fallback


def competencia_from_date(value: str | date | datetime | None) -> str:
    """
    Gera competência YYYY-MM a partir de uma data.
    """
    parsed = parse_iso_date(value)

    if parsed is None:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}"

    return f"{parsed.year:04d}-{parsed.month:02d}"


def month_name_pt(month: int) -> str:
    """
    Nome do mês em português.
    """
    nomes = {
        1: "janeiro",
        2: "fevereiro",
        3: "março",
        4: "abril",
        5: "maio",
        6: "junho",
        7: "julho",
        8: "agosto",
        9: "setembro",
        10: "outubro",
        11: "novembro",
        12: "dezembro",
    }

    return nomes.get(int(month), "")


def competencia_label(value: str | None) -> str:
    """
    Retorna competência em forma mais humana quando possível.

    Ex:
    - 2026-04 -> abril/2026
    - 2025 -> 2025
    - 2024-2025 -> 2024-2025
    """
    if not value:
        return ""

    text = str(value).strip()
    parts = text.split("-")

    if len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2:
        try:
            year = int(parts[0])
            month = int(parts[1])
            return f"{month_name_pt(month)}/{year}"
        except Exception:
            return text

    return text


def clean_filename(value: str) -> str:
    """
    Gera parte segura de nome de arquivo.
    """
    text = safe_text(value, empty="arquivo")

    replacements = {
        " ": "_",
        "/": "-",
        "\\": "-",
        ":": "-",
        "*": "",
        "?": "",
        '"': "",
        "<": "",
        ">": "",
        "|": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    while "__" in text:
        text = text.replace("__", "_")

    return text.strip("_") or "arquivo"
