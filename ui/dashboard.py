from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

import database as db
from calculos import calcular_carteira
from ui.components import (
    render_alertas_indices,
    render_empty_state,
    render_resumo_financeiro,
    render_section_header,
    render_table,
    selected_row_index,
    set_devedor_foco,
)
from ui.formatters import format_date_br, format_money, safe_text


def calcular_resultado_global(data_base: date) -> dict[str, Any]:
    """
    Calcula a carteira completa na data-base.
    """
    return calcular_carteira(
        db.list_dividas(devedor_id=None),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=None,
    )


def calcular_resultado_devedor(
    devedor_id: int,
    data_base: date,
) -> dict[str, Any]:
    """
    Calcula a carteira de um devedor específico na data-base.
    """
    return calcular_carteira(
        db.list_dividas(devedor_id=None),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=devedor_id,
    )


def ultimo_recebimento_devedor(devedor_id: int) -> str:
    """
    Retorna a data do último recebimento do devedor, formatada para exibição.
    """
    pagamentos = db.list_pagamentos(devedor_id=devedor_id)

    if not pagamentos:
        return ""

    datas = []

    for p in pagamentos:
        data_pagamento = p.get("data_pagamento")

        if data_pagamento:
            datas.append(str(data_pagamento)[:10])

    if not datas:
        return ""

    return format_date_br(max(datas))


def situacao_devedor(resumo: dict[str, Any]) -> str:
    """
    Define uma situação simples para a carteira do devedor.
    """
    total = float(resumo.get("total_atualizado") or 0)
    vencidos = int(resumo.get("titulos_vencidos", 0) or 0)
    parciais = int(resumo.get("titulos_parciais", 0) or 0)
    creditos = float(resumo.get("creditos_excedentes", 0) or 0)

    if total <= 0.005 and creditos > 0:
        return "Com crédito"

    if total <= 0.005:
        return "Sem saldo em aberto"

    if vencidos > 0:
        return "Em atraso"

    if parciais > 0:
        return "Parcial"

    return "Em aberto"


def carteira_por_devedor_rows(
    devedores: list[dict[str, Any]],
    data_base: date,
) -> list[dict[str, Any]]:
    """
    Monta a visão gerencial da carteira por devedor.

    A chave _devedor_id é interna e não deve ser exibida na tabela.
    """
    rows: list[dict[str, Any]] = []

    for devedor in devedores:
        devedor_id = int(devedor["id"])
        resultado = calcular_resultado_devedor(devedor_id, data_base)
        resumo = resultado["resumo"]

        situacao = situacao_devedor(resumo)

        rows.append(
            {
                "Devedor": safe_text(devedor.get("nome")),
                "Principal aberto": format_money(
                    resumo.get("principal_aberto_estimado")
                ),
                "Encargos": format_money(resumo.get("encargos")),
                "Total atualizado": format_money(resumo.get("total_atualizado")),
                "Títulos vencidos": int(resumo.get("titulos_vencidos", 0) or 0),
                "Títulos parciais": int(resumo.get("titulos_parciais", 0) or 0),
                "Recebimentos": format_money(resumo.get("pagamentos_considerados")),
                "Créditos/excedentes": format_money(resumo.get("creditos_excedentes")),
                "Último recebimento": ultimo_recebimento_devedor(devedor_id),
                "Situação": situacao,
                "_devedor_id": devedor_id,
                "_total_atualizado": float(resumo.get("total_atualizado") or 0),
                "_titulos_vencidos": int(resumo.get("titulos_vencidos", 0) or 0),
            }
        )

    rows.sort(
        key=lambda r: (
            r["Situação"] != "Em atraso",
            -r["_total_atualizado"],
            r["Devedor"],
        )
    )

    return rows


def carteira_view_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Remove campos internos antes de renderizar a tabela.
    """
    public_rows = []

    for row in rows:
        public_rows.append({k: v for k, v in row.items() if not str(k).startswith("_")})

    return pd.DataFrame(public_rows)


def atencao_rows(carteira_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Monta uma lista curta de itens que merecem atenção.
    """
    rows = []

    for item in carteira_rows:
        if item["_titulos_vencidos"] <= 0 and item["_total_atualizado"] <= 0.005:
            continue

        if item["Situação"] in {"Sem saldo em aberto", "Com crédito"}:
            continue

        rows.append(
            {
                "Devedor": item["Devedor"],
                "Total atualizado": item["Total atualizado"],
                "Títulos vencidos": item["Títulos vencidos"],
                "Último recebimento": item["Último recebimento"],
                "Situação": item["Situação"],
                "_devedor_id": item["_devedor_id"],
                "_prioridade": (
                    0
                    if item["Situação"] == "Em atraso"
                    else 1
                    if item["Situação"] == "Parcial"
                    else 2
                ),
            }
        )

    rows.sort(key=lambda r: (r["_prioridade"], r["Devedor"]))

    return rows[:10]


def atencao_view_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    public_rows = []

    for row in rows:
        public_rows.append({k: v for k, v in row.items() if not str(k).startswith("_")})

    return pd.DataFrame(public_rows)


def baixas_view(resultado: dict[str, Any], limit: int = 20) -> pd.DataFrame:
    """
    Monta uma visão simples das últimas baixas/recebimentos considerados.
    """
    baixas = resultado.get("baixas", resultado.get("alocacoes", []))
    rows = []

    for b in baixas:
        rows.append(
            {
                "Data": format_date_br(b.get("data_pagamento")),
                "Recebimento": b.get("pagamento_ref") or "",
                "Devedor": b.get("devedor") or "",
                "Grupo": b.get("grupo") or "",
                "Título": b.get("titulo_ref") or b.get("divida_ref") or "",
                "Histórico": b.get("titulo") or b.get("divida") or "",
                "Tipo": b.get("tipo_alocacao") or "Baixa",
                "Valor": format_money(b.get("valor_alocado")),
            }
        )

    rows = rows[-limit:]
    rows.reverse()

    return pd.DataFrame(rows)


def titulos_vencidos_view(resultado: dict[str, Any], limit: int = 20) -> pd.DataFrame:
    """
    Monta uma visão dos principais títulos vencidos/em aberto.
    """
    titulos = resultado.get("titulos", resultado.get("dividas", []))
    rows = []

    for t in titulos:
        situacao = safe_text(t.get("situacao_financeira"))

        if situacao not in {"Vencido", "Parcial vencido"}:
            continue

        saldo = float(t.get("saldo_atualizado") or 0)

        if saldo <= 0.005:
            continue

        rows.append(
            {
                "Ref.": t.get("titulo_ref") or t.get("public_ref") or "",
                "Devedor": t.get("devedor") or "",
                "Grupo": t.get("grupo") or "",
                "Competência": t.get("competencia") or "",
                "Descrição": t.get("descricao") or "",
                "Vencimento": format_date_br(t.get("vencimento")),
                "Principal": format_money(t.get("principal_aberto_estimado")),
                "Encargos": format_money(t.get("encargos")),
                "Saldo": format_money(t.get("saldo_atualizado")),
                "Situação": situacao,
            }
        )

    rows = rows[:limit]

    return pd.DataFrame(rows)


def render_dashboard(data_base: date) -> None:
    """
    Renderiza a aba Visão geral.

    Esta tela deve responder:
    - quanto há em aberto;
    - quem está devendo;
    - quais casos precisam de atenção;
    - quais foram os últimos movimentos.
    """
    st.subheader("Visão geral da carteira")

    resultado_global = calcular_resultado_global(data_base)
    resumo = resultado_global["resumo"]

    render_resumo_financeiro(resumo)
    render_alertas_indices(resumo)

    st.divider()

    devedores = db.list_devedores()

    if not devedores:
        render_empty_state(
            "Nenhum devedor cadastrado",
            "Cadastre um devedor para começar a lançar títulos e recebimentos.",
        )
        return

    carteira_rows = carteira_por_devedor_rows(devedores, data_base)

    render_section_header(
        "Atenção necessária",
        "Devedores com títulos vencidos, saldos em aberto ou pagamentos parciais.",
    )

    rows_atencao = atencao_rows(carteira_rows)

    if rows_atencao:
        event_atencao = render_table(
            atencao_view_dataframe(rows_atencao),
            key="dashboard_atencao_table",
            selectable=True,
            empty_message="Nenhum item de atenção no momento.",
        )

        idx_atencao = selected_row_index(event_atencao)

        if idx_atencao is not None:
            devedor_id = rows_atencao[idx_atencao]["_devedor_id"]
            set_devedor_foco(devedor_id)
            st.success(
                "Devedor selecionado. Abra a aba **Devedor** para ver a linha do tempo e os detalhes."
            )
    else:
        st.success("Nenhum devedor com atraso ou saldo relevante no momento.")

    st.divider()

    render_section_header(
        "Carteira por devedor",
        "Clique em uma linha para selecionar o devedor em foco.",
    )

    event = render_table(
        carteira_view_dataframe(carteira_rows),
        key="dashboard_carteira_table",
        selectable=True,
        empty_message="Nenhum devedor encontrado.",
    )

    idx = selected_row_index(event)

    if idx is not None:
        devedor_id = carteira_rows[idx]["_devedor_id"]
        set_devedor_foco(devedor_id)
        st.info(
            "Devedor selecionado. Abra a aba **Devedor** para ver a linha do tempo e os detalhes."
        )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        render_section_header("Títulos vencidos")

        df_vencidos = titulos_vencidos_view(resultado_global)

        if not df_vencidos.empty:
            render_table(
                df_vencidos,
                key="dashboard_titulos_vencidos_table",
                selectable=False,
                empty_message="Nenhum título vencido.",
                height=360,
            )
        else:
            st.success("Nenhum título vencido na data-base.")

    with col2:
        render_section_header("Últimas baixas e excedentes")

        df_baixas = baixas_view(resultado_global)

        if not df_baixas.empty:
            render_table(
                df_baixas,
                key="dashboard_baixas_table",
                selectable=False,
                empty_message="Nenhuma baixa ou recebimento considerado.",
                height=360,
            )
        else:
            st.info("Nenhuma baixa ou recebimento considerado.")
