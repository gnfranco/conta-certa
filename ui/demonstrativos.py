from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st

import database as db
from calculos import calcular_carteira
from reports import gerar_excel, gerar_pdf
from ui.components import (
    get_devedor_by_id,
    get_devedor_foco_id,
    render_alertas_indices,
    render_download_buttons,
    render_empty_state,
    render_resumo_financeiro,
    render_section_header,
    render_table,
    select_devedor,
)
from ui.formatters import (
    clean_filename,
    format_date_br,
    format_datetime_br,
    format_money,
    format_percent,
    safe_text,
)


def calcular_resultado_demonstrativo(
    *,
    data_base: date,
    devedor_id: int | None,
) -> dict[str, Any]:
    """
    Calcula o demonstrativo para todos os devedores ou para um devedor específico.
    """
    return calcular_carteira(
        db.list_dividas(devedor_id=None),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=devedor_id,
    )


def nome_demonstrativo(devedor_id: int | None) -> str:
    """
    Nome humano do escopo do demonstrativo.
    """
    if devedor_id is None:
        return "Carteira completa"

    devedor = get_devedor_by_id(devedor_id)

    if not devedor:
        return "Devedor"

    return safe_text(devedor.get("nome"), empty="Devedor")


def titulo_pdf(devedor_id: int | None) -> str:
    """
    Título usado no PDF.
    """
    if devedor_id is None:
        return "Demonstrativo Conta Certa — Carteira completa"

    return f"Demonstrativo Conta Certa — {nome_demonstrativo(devedor_id)}"


def nome_arquivo_base(
    *,
    devedor_id: int | None,
    data_base: date,
) -> str:
    """
    Nome base seguro para arquivos de exportação.
    """
    escopo = nome_demonstrativo(devedor_id)
    data_str = data_base.isoformat()

    return clean_filename(f"demonstrativo_conta_certa_{escopo}_{data_str}")


def resumo_preview_rows(resultado: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Resumo em formato tabular para conferência na tela.
    """
    resumo = resultado["resumo"]

    return [
        {
            "Campo": "Data-base",
            "Valor": format_date_br(resumo.get("data_base")),
        },
        {
            "Campo": "Total original vencido",
            "Valor": format_money(resumo.get("total_original_vencido")),
        },
        {
            "Campo": "Recebimentos considerados",
            "Valor": format_money(resumo.get("pagamentos_considerados")),
        },
        {
            "Campo": "Principal aberto",
            "Valor": format_money(resumo.get("principal_aberto_estimado")),
        },
        {
            "Campo": "Encargos IPCA + Taxa Legal",
            "Valor": format_money(resumo.get("encargos")),
        },
        {
            "Campo": "Total atualizado",
            "Valor": format_money(resumo.get("total_atualizado")),
        },
        {
            "Campo": "Créditos/excedentes",
            "Valor": format_money(resumo.get("creditos_excedentes")),
        },
        {
            "Campo": "Títulos vencidos",
            "Valor": str(int(resumo.get("titulos_vencidos", 0) or 0)),
        },
        {
            "Campo": "Títulos parciais",
            "Valor": str(int(resumo.get("titulos_parciais", 0) or 0)),
        },
        {
            "Campo": "Títulos quitados",
            "Valor": str(int(resumo.get("titulos_quitados", 0) or 0)),
        },
        {
            "Campo": "Competências provisórias",
            "Valor": safe_text(resumo.get("competencias_provisorias")),
        },
        {
            "Campo": "Competências faltando",
            "Valor": safe_text(resumo.get("competencias_faltando")),
        },
        {
            "Campo": "Emitido em",
            "Valor": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        },
    ]


def titulos_preview(resultado: dict[str, Any]) -> pd.DataFrame:
    """
    Prévia dos títulos que entrarão no demonstrativo.
    """
    titulos = resultado.get("titulos", resultado.get("dividas", []))
    rows: list[dict[str, Any]] = []

    for titulo in titulos:
        rows.append(
            {
                "Ref.": titulo.get("titulo_ref") or titulo.get("public_ref") or "",
                "Devedor": titulo.get("devedor") or "",
                "Grupo": titulo.get("grupo") or "",
                "Tipo": titulo.get("tipo") or "",
                "Competência": titulo.get("competencia") or "",
                "Descrição": titulo.get("descricao") or "",
                "Vencimento": format_date_br(titulo.get("vencimento")),
                "Original": format_money(titulo.get("valor_original")),
                "Recebido": format_money(titulo.get("total_recebido")),
                "Principal": format_money(titulo.get("principal_aberto_estimado")),
                "Encargos": format_money(titulo.get("encargos")),
                "Saldo": format_money(titulo.get("saldo_atualizado")),
                "Situação": titulo.get("situacao_financeira") or "",
                "Status adm.": titulo.get("status_administrativo") or "",
            }
        )

    return pd.DataFrame(rows)


def baixas_preview(resultado: dict[str, Any]) -> pd.DataFrame:
    """
    Prévia das baixas, recebimentos e excedentes que entrarão no demonstrativo.
    """
    baixas = resultado.get("baixas", resultado.get("alocacoes", []))
    rows: list[dict[str, Any]] = []

    for baixa in baixas:
        rows.append(
            {
                "Recebimento": baixa.get("pagamento_ref") or "",
                "Data": format_date_br(baixa.get("data_pagamento")),
                "Devedor": baixa.get("devedor") or "",
                "Grupo": baixa.get("grupo") or "",
                "Título": baixa.get("titulo_ref") or baixa.get("divida_ref") or "",
                "Lote": baixa.get("lote_ref") or "",
                "Histórico": baixa.get("titulo") or baixa.get("divida") or "",
                "Tipo": baixa.get("tipo_alocacao") or "Baixa",
                "Valor": format_money(baixa.get("valor_alocado")),
            }
        )

    return pd.DataFrame(rows)


def indices_preview(taxas: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Prévia dos índices cadastrados.
    """
    rows: list[dict[str, Any]] = []

    for taxa in taxas:
        rows.append(
            {
                "Competência": taxa.get("competencia") or "",
                "IPCA (%)": format_percent(taxa.get("ipca_pct"), decimals=4),
                "Taxa Legal (%)": format_percent(
                    taxa.get("taxa_legal_pct"),
                    decimals=6,
                ),
                "Fonte": taxa.get("fonte") or "",
                "Status": taxa.get("status") or "",
                "Atualizado em": format_datetime_br(taxa.get("updated_at")),
            }
        )

    return pd.DataFrame(rows)


def render_criterios_demonstrativo() -> None:
    """
    Mostra os critérios de cálculo ao usuário antes da emissão.
    """
    with st.expander("Critérios do demonstrativo", expanded=False):
        st.write(
            "O demonstrativo considera os títulos vencidos até a data-base informada, "
            "os recebimentos registrados até a mesma data e a atualização por IPCA + Taxa Legal."
        )
        st.write(
            "Quando uma competência ainda não possui índice oficial cadastrado, o sistema pode "
            "usar índice provisório, conforme a configuração local."
        )
        st.write(
            "Recebimentos são aplicados conforme o modo registrado: automático geral, automático "
            "por grupo ou título específico."
        )


def gerar_arquivos_demonstrativo(
    *,
    resultado: dict[str, Any],
    taxas: list[dict[str, Any]],
    devedor_id: int | None,
    data_base: date,
) -> tuple[bytes, bytes | None, str, str]:
    """
    Gera Excel e PDF do demonstrativo.

    Retorna:
    - excel_bytes
    - pdf_bytes ou None
    - excel_filename
    - pdf_filename
    """
    base = nome_arquivo_base(devedor_id=devedor_id, data_base=data_base)

    excel_bytes = gerar_excel(resultado, taxas)

    pdf_bytes = None

    try:
        pdf_bytes = gerar_pdf(
            resultado,
            titulo=titulo_pdf(devedor_id),
        )
    except Exception as e:
        st.warning(f"Não foi possível gerar PDF: {e}")

    return (
        excel_bytes,
        pdf_bytes,
        f"{base}.xlsx",
        f"{base}.pdf",
    )


def render_preview_demonstrativo(
    *,
    resultado: dict[str, Any],
    taxas: list[dict[str, Any]],
) -> None:
    """
    Mostra uma prévia navegável do conteúdo que será exportado.
    """
    tab_resumo, tab_titulos, tab_baixas, tab_indices = st.tabs(
        ["Resumo", "Títulos", "Baixas", "Índices"]
    )

    with tab_resumo:
        render_table(
            pd.DataFrame(resumo_preview_rows(resultado)),
            key="demonstrativos_preview_resumo",
            selectable=False,
            empty_message="Resumo indisponível.",
        )

    with tab_titulos:
        df_titulos = titulos_preview(resultado)

        render_table(
            df_titulos,
            key="demonstrativos_preview_titulos",
            selectable=False,
            empty_message="Nenhum título considerado neste demonstrativo.",
        )

    with tab_baixas:
        df_baixas = baixas_preview(resultado)

        render_table(
            df_baixas,
            key="demonstrativos_preview_baixas",
            selectable=False,
            empty_message="Nenhuma baixa considerada neste demonstrativo.",
        )

    with tab_indices:
        df_indices = indices_preview(taxas)

        render_table(
            df_indices,
            key="demonstrativos_preview_indices",
            selectable=False,
            empty_message="Nenhum índice cadastrado.",
        )


def render_demonstrativos(data_base: date) -> None:
    """
    Renderiza a página de demonstrativos.

    A tela permite:
    - escolher escopo: carteira completa ou devedor específico;
    - conferir resumo;
    - ver prévia dos títulos, baixas e índices;
    - baixar Excel e PDF.
    """
    st.subheader("Demonstrativos")

    devedor_padrao = get_devedor_foco_id()

    devedor_id = select_devedor(
        "Escopo do demonstrativo",
        include_all=True,
        key="demonstrativos_devedor",
        default_devedor_id=devedor_padrao,
    )

    if devedor_id is not None:
        devedor = get_devedor_by_id(devedor_id)

        if not devedor:
            render_empty_state(
                "Devedor não encontrado",
                "Selecione outro devedor ou verifique se ele ainda está ativo.",
            )
            return

    resultado = calcular_resultado_demonstrativo(
        data_base=data_base,
        devedor_id=devedor_id,
    )

    taxas = db.list_taxas()
    resumo = resultado["resumo"]

    render_section_header(
        "Resumo do demonstrativo",
        f"Escopo: {nome_demonstrativo(devedor_id)} · Data-base: {format_date_br(data_base)}",
    )

    render_resumo_financeiro(resumo)
    render_alertas_indices(resumo)
    render_criterios_demonstrativo()

    st.divider()

    render_section_header(
        "Prévia",
        "Confira os dados antes de baixar o demonstrativo.",
    )

    render_preview_demonstrativo(resultado=resultado, taxas=taxas)

    st.divider()

    render_section_header("Exportar")

    excel_bytes, pdf_bytes, excel_filename, pdf_filename = gerar_arquivos_demonstrativo(
        resultado=resultado,
        taxas=taxas,
        devedor_id=devedor_id,
        data_base=data_base,
    )

    render_download_buttons(
        excel_bytes=excel_bytes,
        pdf_bytes=pdf_bytes,
        excel_filename=excel_filename,
        pdf_filename=pdf_filename,
    )
