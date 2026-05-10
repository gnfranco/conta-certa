from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

import bcb
import database as db
from ui.components import (
    render_danger_action,
    render_empty_state,
    render_section_header,
    render_subsection_header,
    render_table,
    selected_row_index,
)
from ui.formatters import format_datetime_br, format_percent, safe_text


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or pd.isna(value)


def _float_or_none(value: Any) -> float | None:
    if _is_missing(value):
        return None

    try:
        return float(value)
    except Exception:
        return None


def _format_taxa(value: Any, decimals: int = 4) -> str:
    if _is_missing(value):
        return ""

    return format_percent(value, decimals=decimals)


def _status_counts(taxas: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(taxas),
        "oficiais": 0,
        "provisorias": 0,
        "parciais": 0,
        "incompletas": 0,
    }

    for taxa in taxas:
        status = safe_text(taxa.get("status")).lower()

        if status.startswith("oficial"):
            counts["oficiais"] += 1
        elif status.startswith("provis"):
            counts["provisorias"] += 1
        elif status.startswith("parcial"):
            counts["parciais"] += 1

        if taxa.get("ipca_pct") is None or taxa.get("taxa_legal_pct") is None:
            counts["incompletas"] += 1

    return counts


def _taxas_view(taxas: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for taxa in taxas:
        rows.append(
            {
                "Competência": taxa.get("competencia") or "",
                "IPCA (%)": _format_taxa(taxa.get("ipca_pct"), decimals=4),
                "Taxa Legal (%)": _format_taxa(
                    taxa.get("taxa_legal_pct"),
                    decimals=6,
                ),
                "Fonte": taxa.get("fonte") or "",
                "Status": taxa.get("status") or "",
                "Atualizado em": format_datetime_br(taxa.get("updated_at")),
            }
        )

    return pd.DataFrame(rows)


def _default_competencia(data_base: date | None = None) -> str:
    ref = data_base or date.today()
    return f"{ref.year:04d}-{ref.month:02d}"


def _selected_taxa_defaults(
    taxa: dict[str, Any] | None,
    data_base: date | None = None,
) -> dict[str, Any]:
    if not taxa:
        return {
            "competencia": _default_competencia(data_base),
            "ipca_disponivel": True,
            "ipca_pct": 0.0,
            "taxa_legal_disponivel": True,
            "taxa_legal_pct": 0.0,
            "status": "Oficial",
            "fonte": "Manual",
        }

    return {
        "competencia": taxa.get("competencia") or _default_competencia(data_base),
        "ipca_disponivel": taxa.get("ipca_pct") is not None,
        "ipca_pct": float(taxa.get("ipca_pct") or 0.0),
        "taxa_legal_disponivel": taxa.get("taxa_legal_pct") is not None,
        "taxa_legal_pct": float(taxa.get("taxa_legal_pct") or 0.0),
        "status": taxa.get("status") or "Oficial",
        "fonte": taxa.get("fonte") or "Manual",
    }


def render_indices_resumo(taxas: list[dict[str, Any]]) -> None:
    counts = _status_counts(taxas)

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric("Competências", counts["total"])
    c2.metric("Oficiais", counts["oficiais"])
    c3.metric("Provisórias", counts["provisorias"])
    c4.metric("Parciais", counts["parciais"])
    c5.metric("Incompletas", counts["incompletas"])


def render_atualizacao_bcb(data_base: date | None = None) -> None:
    render_section_header(
        "Atualização pelo Banco Central",
        "Busca IPCA e Taxa Legal pela API SGS do Banco Central, quando disponíveis.",
    )

    c1, c2, c3 = st.columns([1, 1, 1])

    with c1:
        inicio = st.date_input(
            "Buscar de",
            value=date(2024, 8, 1),
            key="indices_busca_inicio",
        )

    with c2:
        fim = st.date_input(
            "Buscar até",
            value=data_base or date.today(),
            key="indices_busca_fim",
        )

    with c3:
        st.write("")
        st.write("")

        atualizar = st.button(
            "Atualizar via BCB",
            width="stretch",
            key="indices_btn_atualizar_bcb",
        )

    if not atualizar:
        return

    if fim < inicio:
        st.error("A data final não pode ser anterior à data inicial.")
        return

    try:
        df = bcb.buscar_ipca_e_taxa_legal(inicio, fim)

        if df.empty:
            st.info("Nenhuma competência retornada pelo BCB nesse período.")
            return

        atualizadas = 0

        for _, row in df.iterrows():
            db.upsert_taxa(
                competencia=row["competencia"],
                ipca_pct=None
                if pd.isna(row.get("ipca_pct"))
                else float(row["ipca_pct"]),
                taxa_legal_pct=None
                if pd.isna(row.get("taxa_legal_pct"))
                else float(row["taxa_legal_pct"]),
                fonte=row.get("fonte") or "BCB SGS",
                status=row.get("status") or "Oficial",
            )
            atualizadas += 1

        st.success(f"{atualizadas} competência(s) atualizada(s).")
        st.rerun()

    except Exception as e:
        st.error(f"Falha ao buscar índices no BCB: {e}")


def render_form_taxa_manual(
    *,
    taxa_selecionada: dict[str, Any] | None = None,
    data_base: date | None = None,
) -> None:
    defaults = _selected_taxa_defaults(taxa_selecionada, data_base)

    titulo = (
        f"Alterar índice {defaults['competencia']}"
        if taxa_selecionada
        else "Cadastrar/alterar índice manualmente"
    )

    render_section_header(
        titulo,
        "Use esta área para corrigir, completar ou lançar índices provisórios.",
    )

    with st.form("indices_form_taxa_manual"):
        competencia = st.text_input(
            "Competência (YYYY-MM)",
            value=defaults["competencia"],
            key="indices_manual_competencia",
        )

        c1, c2 = st.columns(2)

        with c1:
            ipca_disponivel = st.checkbox(
                "IPCA disponível",
                value=bool(defaults["ipca_disponivel"]),
                key="indices_manual_ipca_disponivel",
            )

            ipca = st.number_input(
                "IPCA mensal (%)",
                value=float(defaults["ipca_pct"]),
                step=0.01,
                format="%.4f",
                disabled=not ipca_disponivel,
                key="indices_manual_ipca",
            )

        with c2:
            taxa_legal_disponivel = st.checkbox(
                "Taxa Legal disponível",
                value=bool(defaults["taxa_legal_disponivel"]),
                key="indices_manual_tl_disponivel",
            )

            taxa_legal = st.number_input(
                "Taxa Legal mensal (%)",
                value=float(defaults["taxa_legal_pct"]),
                step=0.01,
                format="%.6f",
                disabled=not taxa_legal_disponivel,
                key="indices_manual_tl",
            )

        status_options = ["Oficial", "Provisória", "Parcial"]

        status_atual = defaults["status"]

        if status_atual not in status_options:
            status_options.append(status_atual)

        c3, c4 = st.columns(2)

        with c3:
            status = st.selectbox(
                "Status",
                status_options,
                index=status_options.index(status_atual),
                key="indices_manual_status",
            )

        with c4:
            fonte = st.text_input(
                "Fonte",
                value=defaults["fonte"],
                key="indices_manual_fonte",
            )

        submitted = st.form_submit_button("Salvar índice")

        if not submitted:
            return

        competencia_limpa = competencia.strip()

        if not competencia_limpa:
            st.error("Informe a competência.")
            return

        if len(competencia_limpa) != 7 or competencia_limpa[4] != "-":
            st.error("Use competência no formato YYYY-MM, por exemplo 2026-05.")
            return

        ipca_final = float(ipca) if ipca_disponivel else None
        taxa_legal_final = float(taxa_legal) if taxa_legal_disponivel else None

        if ipca_final is None or taxa_legal_final is None:
            status = "Parcial"

        db.upsert_taxa(
            competencia=competencia_limpa,
            ipca_pct=ipca_final,
            taxa_legal_pct=taxa_legal_final,
            fonte=fonte.strip() or "Manual",
            status=status,
        )

        st.success("Índice salvo.")
        st.rerun()


def render_tabela_indices(taxas: list[dict[str, Any]]) -> dict[str, Any] | None:
    render_section_header(
        "Índices cadastrados",
        "Selecione uma competência para editar ou excluir.",
    )

    if not taxas:
        render_empty_state(
            "Nenhum índice cadastrado",
            "Atualize pelo BCB ou cadastre uma competência manualmente.",
        )
        return None

    df = _taxas_view(taxas)

    event = render_table(
        df,
        key="indices_table",
        selectable=True,
        empty_message="Nenhum índice cadastrado.",
    )

    idx = selected_row_index(event)

    if idx is None:
        st.caption("Selecione uma linha para editar ou excluir o índice.")
        return None

    return taxas[idx]


def render_exclusao_taxa(taxa: dict[str, Any] | None) -> None:
    if not taxa:
        return

    competencia = taxa.get("competencia") or ""

    render_subsection_header(
        f"Ações do índice {competencia}",
        "Excluir um índice remove a competência da base local. Cálculos podem passar a usar taxa provisória ou acusar índice faltante.",
    )

    with st.expander("Excluir índice", expanded=False):
        if render_danger_action(
            label="Excluir índice",
            confirmation_label=f"Confirmo que desejo excluir o índice {competencia}",
            key_prefix=f"indices_excluir_{competencia}",
        ):
            try:
                db.delete_taxa(int(taxa["id"]))
                st.success("Índice excluído.")
                st.rerun()
            except Exception as e:
                st.error(f"Não foi possível excluir o índice: {e}")


def render_indices(data_base: date | None = None) -> None:
    """
    Renderiza a página de índices.

    Esta tela cuida das competências mensais usadas nos cálculos:
    - atualização via BCB;
    - cadastro/alteração manual;
    - listagem;
    - exclusão controlada.
    """
    st.subheader("Índices IPCA + Taxa Legal")

    st.write(
        "Mantenha os índices mensais usados para atualizar títulos vencidos. "
        "Quando uma competência ainda não tiver valor oficial, você pode lançar valor provisório "
        "ou deixar parcial para que o sistema avise nos cálculos."
    )

    taxas = db.list_taxas()

    render_indices_resumo(taxas)

    st.divider()

    render_atualizacao_bcb(data_base)

    st.divider()

    taxa_selecionada = render_tabela_indices(taxas)

    st.divider()

    render_form_taxa_manual(
        taxa_selecionada=taxa_selecionada,
        data_base=data_base,
    )

    render_exclusao_taxa(taxa_selecionada)
