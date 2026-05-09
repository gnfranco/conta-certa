from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def money(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def competencia(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def iter_month_slices(start: date, end: date):
    cur = start
    while cur < end:
        nm = next_month(date(cur.year, cur.month, 1))
        stop = min(end, nm)
        days = (stop - cur).days
        days_in_month = calendar.monthrange(cur.year, cur.month)[1]
        yield competencia(cur), days, days_in_month, cur, stop
        cur = stop


def str_to_bool(v: str | bool | None) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in {"sim", "s", "yes", "true", "1"}


def get_float_setting(settings: dict[str, str], key: str, default: float) -> float:
    try:
        return float(str(settings.get(key, default)).replace(",", "."))
    except Exception:
        return default


@dataclass
class FactorResult:
    factor: float
    detalhe: list[dict[str, Any]] = field(default_factory=list)
    competencias_faltando: set[str] = field(default_factory=set)
    competencias_provisorias: set[str] = field(default_factory=set)


def fator_periodo(
    start: date,
    end: date,
    taxas: dict[str, dict[str, Any]],
    settings: dict[str, str],
) -> FactorResult:
    if end <= start:
        return FactorResult(factor=1.0)

    usar_prov = str_to_bool(settings.get("usar_provisorio", "Sim"))
    ipca_prov = get_float_setting(settings, "ipca_provisorio_pct", 0.0)
    tl_prov = get_float_setting(settings, "taxa_legal_provisoria_pct", 0.0)

    total_factor = 1.0
    detalhe: list[dict[str, Any]] = []
    faltando: set[str] = set()
    provisorias: set[str] = set()

    for comp, days, days_in_month, seg_start, seg_end in iter_month_slices(start, end):
        row = taxas.get(comp)
        status = "Oficial"

        if row:
            ipca = row.get("ipca_pct")
            tl = row.get("taxa_legal_pct")
            if ipca is None:
                if usar_prov:
                    ipca = ipca_prov
                    status = "Provisoria"
                    provisorias.add(comp)
                else:
                    ipca = 0.0
                    status = "Faltando"
                    faltando.add(comp)
            if tl is None:
                if usar_prov:
                    tl = tl_prov
                    status = "Provisoria"
                    provisorias.add(comp)
                else:
                    tl = 0.0
                    status = "Faltando"
                    faltando.add(comp)
            if str(row.get("status", "")).lower().startswith("provis"):
                provisorias.add(comp)
                status = "Provisoria"
        else:
            if usar_prov:
                ipca = ipca_prov
                tl = tl_prov
                status = "Provisoria"
                provisorias.add(comp)
            else:
                ipca = 0.0
                tl = 0.0
                status = "Faltando"
                faltando.add(comp)

        monthly_factor = (1 + float(ipca) / 100.0) * (1 + float(tl) / 100.0)
        prorated_factor = monthly_factor ** (days / days_in_month)
        total_factor *= prorated_factor

        detalhe.append(
            {
                "competencia": comp,
                "dias": days,
                "dias_mes": days_in_month,
                "de": seg_start.isoformat(),
                "ate": seg_end.isoformat(),
                "ipca_pct": float(ipca),
                "taxa_legal_pct": float(tl),
                "fator_mensal": monthly_factor,
                "fator_prorata": prorated_factor,
                "status": status,
            }
        )

    return FactorResult(
        factor=total_factor,
        detalhe=detalhe,
        competencias_faltando=faltando,
        competencias_provisorias=provisorias,
    )


def calcular_carteira(
    dividas: list[dict[str, Any]],
    pagamentos: list[dict[str, Any]],
    taxas: dict[str, dict[str, Any]],
    settings: dict[str, str],
    data_base: date,
    devedor_id: int | None = None,
) -> dict[str, Any]:
    dividas_validas = []
    for d in dividas:
        if devedor_id and int(d["devedor_id"]) != int(devedor_id):
            continue
        if d.get("status") == "Cancelada":
            continue
        venc = parse_date(d["data_vencimento"])
        if venc <= data_base:
            dividas_validas.append(d)

    pagamentos_validos = []
    for p in pagamentos:
        if devedor_id and int(p["devedor_id"]) != int(devedor_id):
            continue
        if parse_date(p["data_pagamento"]) <= data_base:
            pagamentos_validos.append(p)

    estados: dict[int, dict[str, Any]] = {}
    for d in dividas_validas:
        venc = parse_date(d["data_vencimento"])
        valor = float(d["valor_original"])
        estados[int(d["id"])] = {
            "id": int(d["id"]),
            "devedor_id": int(d["devedor_id"]),
            "devedor": d.get("devedor", ""),
            "descricao": d.get("descricao", ""),
            "tipo": d.get("tipo", ""),
            "data_vencimento": venc,
            "valor_original": valor,
            "saldo_atualizado": valor,
            "principal_puro": valor,
            "last_date": venc,
            "encargos_adicionados": 0.0,
            "provisorias": set(),
            "faltando": set(),
        }

    pagamentos_ordenados = sorted(
        pagamentos_validos,
        key=lambda p: (parse_date(p["data_pagamento"]), int(p["id"])),
    )

    alocacoes: list[dict[str, Any]] = []

    def atualizar_divida_ate(state: dict[str, Any], ate: date) -> None:
        if state["saldo_atualizado"] <= 0:
            state["last_date"] = max(state["last_date"], ate)
            return
        if ate <= state["last_date"]:
            return
        fr = fator_periodo(state["last_date"], ate, taxas, settings)
        antes = state["saldo_atualizado"]
        depois = antes * fr.factor
        state["saldo_atualizado"] = depois
        state["encargos_adicionados"] += max(0.0, depois - antes)
        state["last_date"] = ate
        state["provisorias"].update(fr.competencias_provisorias)
        state["faltando"].update(fr.competencias_faltando)

    def aplicar_em_divida(state: dict[str, Any], valor: float, data_pg: date, pagamento_id: int) -> float:
        atualizar_divida_ate(state, data_pg)
        if valor <= 0 or state["saldo_atualizado"] <= 0:
            return valor

        usado = min(valor, state["saldo_atualizado"])
        state["saldo_atualizado"] -= usado
        state["principal_puro"] = max(0.0, state["principal_puro"] - min(usado, state["principal_puro"]))

        alocacoes.append(
            {
                "pagamento_id": pagamento_id,
                "data_pagamento": data_pg.isoformat(),
                "devedor": state["devedor"],
                "divida_id": state["id"],
                "divida": state["descricao"],
                "valor_alocado": usado,
            }
        )
        return valor - usado

    for p in pagamentos_ordenados:
        data_pg = parse_date(p["data_pagamento"])
        valor_restante = float(p["valor"])
        divida_id = p.get("divida_id")

        if divida_id:
            state = estados.get(int(divida_id))
            if state:
                valor_restante = aplicar_em_divida(state, valor_restante, data_pg, int(p["id"]))
        else:
            candidatos = sorted(
                [
                    s for s in estados.values()
                    if s["devedor_id"] == int(p["devedor_id"])
                    and s["data_vencimento"] <= data_pg
                    and s["saldo_atualizado"] > 0
                ],
                key=lambda s: (s["data_vencimento"], s["id"]),
            )
            for state in candidatos:
                if valor_restante <= 0:
                    break
                valor_restante = aplicar_em_divida(state, valor_restante, data_pg, int(p["id"]))

        if valor_restante > 0.005:
            alocacoes.append(
                {
                    "pagamento_id": int(p["id"]),
                    "data_pagamento": data_pg.isoformat(),
                    "devedor": p.get("devedor", ""),
                    "divida_id": None,
                    "divida": "Excedente nao alocado",
                    "valor_alocado": -valor_restante,
                }
            )

    for state in estados.values():
        atualizar_divida_ate(state, data_base)

    linhas = []
    total_original = 0.0
    total_principal = 0.0
    total_atualizado = 0.0
    total_encargos = 0.0
    provisorias: set[str] = set()
    faltando: set[str] = set()

    for s in sorted(estados.values(), key=lambda x: (x["data_vencimento"], x["id"])):
        saldo = max(0.0, s["saldo_atualizado"])
        principal = max(0.0, min(s["principal_puro"], saldo))
        encargos = max(0.0, saldo - principal)

        total_original += s["valor_original"]
        total_principal += principal
        total_atualizado += saldo
        total_encargos += encargos
        provisorias.update(s["provisorias"])
        faltando.update(s["faltando"])

        linhas.append(
            {
                "id": s["id"],
                "devedor": s["devedor"],
                "tipo": s["tipo"],
                "descricao": s["descricao"],
                "vencimento": s["data_vencimento"].isoformat(),
                "valor_original": s["valor_original"],
                "principal_aberto_estimado": principal,
                "encargos": encargos,
                "saldo_atualizado": saldo,
                "competencias_provisorias": ", ".join(sorted(s["provisorias"])),
                "competencias_faltando": ", ".join(sorted(s["faltando"])),
            }
        )

    pagamentos_total = sum(float(p["valor"]) for p in pagamentos_validos)

    return {
        "resumo": {
            "data_base": data_base.isoformat(),
            "total_original_vencido": total_original,
            "pagamentos_considerados": pagamentos_total,
            "principal_aberto_estimado": total_principal,
            "encargos": total_encargos,
            "total_atualizado": total_atualizado,
            "competencias_provisorias": ", ".join(sorted(provisorias)),
            "competencias_faltando": ", ".join(sorted(faltando)),
        },
        "dividas": linhas,
        "alocacoes": alocacoes,
    }
