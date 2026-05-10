from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from money import cents_to_float, format_money as money, row_money_to_cents

EPSILON = 0.005


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value

    text = str(value).strip()

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()


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


def public_ref_or_fallback(row: dict[str, Any], prefix: str) -> str:
    public_ref = str(row.get("public_ref") or "").strip()

    if public_ref:
        return public_ref

    row_id = row.get("id")

    if row_id is None:
        return f"{prefix}-SEM-REF"

    return f"{prefix}-LEGADO-{int(row_id):06d}"


def valor_titulo_reais(row: dict[str, Any]) -> float:
    return cents_to_float(row_money_to_cents(row, "valor_original_centavos", "valor_original"))


def valor_recebimento_reais(row: dict[str, Any]) -> float:
    return cents_to_float(row_money_to_cents(row, "valor_centavos", "valor"))


def calcular_situacao_financeira(
    *,
    saldo: float,
    total_recebido: float,
    vencimento: date,
    data_base: date,
) -> str:
    if saldo <= EPSILON:
        return "Quitado"

    if total_recebido > EPSILON and vencimento < data_base:
        return "Parcial vencido"

    if total_recebido > EPSILON:
        return "Parcial"

    if vencimento < data_base:
        return "Vencido"

    return "Aberto"


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

    for comp, days, days_in_month, seg_start, seg_end in iter_month_slices(
        start,
        end,
    ):
        row = taxas.get(comp)
        status = "Oficial"

        if row:
            ipca = row.get("ipca_pct")
            tl = row.get("taxa_legal_pct")

            if ipca is None:
                if usar_prov:
                    ipca = ipca_prov
                    status = "Provisória"
                    provisorias.add(comp)
                else:
                    ipca = 0.0
                    status = "Faltando"
                    faltando.add(comp)

            if tl is None:
                if usar_prov:
                    tl = tl_prov
                    status = "Provisória"
                    provisorias.add(comp)
                else:
                    tl = 0.0
                    status = "Faltando"
                    faltando.add(comp)

            row_status = str(row.get("status", "")).lower()

            if row_status.startswith("provis"):
                status = "Provisória"
                provisorias.add(comp)
            elif row_status.startswith("parcial"):
                status = "Parcial"

        else:
            if usar_prov:
                ipca = ipca_prov
                tl = tl_prov
                status = "Provisória"
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
        valor = valor_titulo_reais(d)

        estados[int(d["id"])] = {
            "id": int(d["id"]),
            "public_ref": public_ref_or_fallback(d, "TIT"),
            "lote_ref": d.get("lote_ref") or "",
            "devedor_id": int(d["devedor_id"]),
            "devedor": d.get("devedor", ""),
            "grupo_id": d.get("grupo_id"),
            "grupo": d.get("grupo") or "Geral",
            "tipo": d.get("tipo", ""),
            "competencia": d.get("competencia") or competencia(venc),
            "descricao": d.get("descricao", ""),
            "status_administrativo": d.get("status") or "Aberta",
            "data_vencimento": venc,
            "valor_original": valor,
            "saldo_atualizado": valor,
            "principal_puro": valor,
            "last_date": venc,
            "encargos_adicionados": 0.0,
            "total_recebido": 0.0,
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

    def aplicar_em_divida(
        state: dict[str, Any],
        pagamento: dict[str, Any],
        valor: float,
        data_pg: date,
    ) -> float:
        atualizar_divida_ate(state, data_pg)

        if valor <= 0 or state["saldo_atualizado"] <= 0:
            return valor

        usado = min(valor, state["saldo_atualizado"])
        state["saldo_atualizado"] -= usado
        state["total_recebido"] += usado

        abatimento_principal = min(usado, state["principal_puro"])
        state["principal_puro"] = max(
            0.0,
            state["principal_puro"] - abatimento_principal,
        )

        alocacoes.append(
            {
                "pagamento_id": int(pagamento["id"]),
                "pagamento_ref": public_ref_or_fallback(pagamento, "REC"),
                "data_pagamento": data_pg.isoformat(),
                "devedor": state["devedor"],
                "grupo": state["grupo"],
                "divida_id": state["id"],
                "divida_ref": state["public_ref"],
                "titulo_ref": state["public_ref"],
                "lote_ref": state.get("lote_ref") or "",
                "divida": state["descricao"],
                "titulo": state["descricao"],
                "valor_alocado": usado,
                "tipo_alocacao": "Baixa",
            }
        )

        return valor - usado

    for p in pagamentos_ordenados:
        data_pg = parse_date(p["data_pagamento"])
        valor_restante = valor_recebimento_reais(p)

        divida_id = p.get("divida_id")
        grupo_id = p.get("grupo_id")

        if divida_id:
            state = estados.get(int(divida_id))

            if state:
                valor_restante = aplicar_em_divida(
                    state,
                    p,
                    valor_restante,
                    data_pg,
                )

        else:
            candidatos = []

            for s in estados.values():
                if s["devedor_id"] != int(p["devedor_id"]):
                    continue

                if s["data_vencimento"] > data_pg:
                    continue

                if s["saldo_atualizado"] <= 0:
                    continue

                if grupo_id and int(s.get("grupo_id") or 0) != int(grupo_id):
                    continue

                candidatos.append(s)

            candidatos = sorted(
                candidatos,
                key=lambda s: (s["data_vencimento"], s["id"]),
            )

            for state in candidatos:
                if valor_restante <= 0:
                    break

                valor_restante = aplicar_em_divida(
                    state,
                    p,
                    valor_restante,
                    data_pg,
                )

        if valor_restante > EPSILON:
            grupo_desc = p.get("grupo") if p.get("grupo_id") else "Todos os grupos"

            alocacoes.append(
                {
                    "pagamento_id": int(p["id"]),
                    "pagamento_ref": public_ref_or_fallback(p, "REC"),
                    "data_pagamento": data_pg.isoformat(),
                    "devedor": p.get("devedor", ""),
                    "grupo": grupo_desc,
                    "divida_id": None,
                    "divida_ref": None,
                    "titulo_ref": None,
                    "lote_ref": None,
                    "divida": "Excedente não alocado",
                    "titulo": "Excedente não alocado",
                    "valor_alocado": -valor_restante,
                    "tipo_alocacao": "Excedente",
                }
            )

    for state in estados.values():
        atualizar_divida_ate(state, data_base)

    linhas = []
    total_original = 0.0
    total_principal = 0.0
    total_atualizado = 0.0
    total_encargos = 0.0
    total_titulos_vencidos = 0
    total_titulos_quitados = 0
    total_titulos_parciais = 0
    provisorias: set[str] = set()
    faltando: set[str] = set()

    for s in sorted(
        estados.values(),
        key=lambda x: (x["devedor"], x["data_vencimento"], x["id"]),
    ):
        saldo = max(0.0, s["saldo_atualizado"])
        principal = max(0.0, min(s["principal_puro"], saldo))
        encargos = max(0.0, saldo - principal)

        situacao_financeira = calcular_situacao_financeira(
            saldo=saldo,
            total_recebido=float(s["total_recebido"]),
            vencimento=s["data_vencimento"],
            data_base=data_base,
        )

        if situacao_financeira == "Quitado":
            total_titulos_quitados += 1
        elif situacao_financeira in {"Parcial", "Parcial vencido"}:
            total_titulos_parciais += 1

        if s["data_vencimento"] < data_base and saldo > EPSILON:
            total_titulos_vencidos += 1

        total_original += s["valor_original"]
        total_principal += principal
        total_atualizado += saldo
        total_encargos += encargos

        provisorias.update(s["provisorias"])
        faltando.update(s["faltando"])

        linhas.append(
            {
                "id": s["id"],
                "public_ref": s["public_ref"],
                "titulo_ref": s["public_ref"],
                "lote_ref": s.get("lote_ref") or "",
                "devedor": s["devedor"],
                "grupo": s["grupo"],
                "tipo": s["tipo"],
                "competencia": s["competencia"],
                "descricao": s["descricao"],
                "vencimento": s["data_vencimento"].isoformat(),
                "valor_original": s["valor_original"],
                "principal_aberto_estimado": principal,
                "encargos": encargos,
                "saldo_atualizado": saldo,
                "total_recebido": s["total_recebido"],
                "situacao_financeira": situacao_financeira,
                "status_administrativo": s["status_administrativo"],
                "competencias_provisorias": ", ".join(sorted(s["provisorias"])),
                "competencias_faltando": ", ".join(sorted(s["faltando"])),
            }
        )

    pagamentos_total = sum(valor_recebimento_reais(p) for p in pagamentos_validos)
    excedente_nao_alocado = sum(
        abs(float(a["valor_alocado"]))
        for a in alocacoes
        if float(a["valor_alocado"]) < 0
    )

    return {
        "resumo": {
            "data_base": data_base.isoformat(),
            "total_original_vencido": total_original,
            "pagamentos_considerados": pagamentos_total,
            "principal_aberto_estimado": total_principal,
            "encargos": total_encargos,
            "total_atualizado": total_atualizado,
            "excedente_nao_alocado": excedente_nao_alocado,
            "creditos_excedentes": excedente_nao_alocado,
            "titulos_vencidos": total_titulos_vencidos,
            "titulos_quitados": total_titulos_quitados,
            "titulos_parciais": total_titulos_parciais,
            "competencias_provisorias": ", ".join(sorted(provisorias)),
            "competencias_faltando": ", ".join(sorted(faltando)),
        },
        "dividas": linhas,
        "titulos": linhas,
        "alocacoes": alocacoes,
        "baixas": alocacoes,
    }
