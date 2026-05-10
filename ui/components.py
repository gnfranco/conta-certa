from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
import streamlit as st

import database as db
from ui.formatters import devedor_label, format_money, safe_text


def make_unique_labels(labels: list[str]) -> list[str]:
    """
    Garante labels únicos para selectbox sem expor IDs internos.

    Ex:
    ["BDN", "BDN"] -> ["BDN", "BDN (2)"]
    """
    counts: dict[str, int] = {}
    result: list[str] = []

    for label in labels:
        text = safe_text(label, empty="Sem nome")
        counts[text] = counts.get(text, 0) + 1

        if counts[text] == 1:
            result.append(text)
        else:
            result.append(f"{text} ({counts[text]})")

    return result


def selected_row_index(event: Any) -> int | None:
    """
    Extrai a linha selecionada de um st.dataframe com selection_mode='single-row'.
    """
    try:
        rows = event.selection.rows
    except Exception:
        rows = []

    if not rows:
        return None

    return int(rows[0])


def dataframe_from_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """
    Cria DataFrame vazio com segurança quando não houver linhas.
    """
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def normalize_dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Evita problemas do PyArrow/Streamlit quando uma coluna mistura string, número e vazio.

    Para tabelas de apresentação, é mais seguro converter object columns para string.
    As tabelas do Conta Certa já são formatadas para leitura humana.
    """
    if df.empty:
        return df

    normalized = df.copy()

    for col in normalized.columns:
        if normalized[col].dtype == "object":
            normalized[col] = normalized[col].fillna("").astype(str)

    return normalized


def render_table(
    data: pd.DataFrame | list[dict[str, Any]],
    *,
    key: str,
    selectable: bool = False,
    empty_message: str = "Nenhum registro encontrado.",
    height: int | None = None,
) -> Any:
    """
    Renderiza uma tabela padronizada.

    Retorna o evento do st.dataframe quando selectable=True.
    """
    df = data if isinstance(data, pd.DataFrame) else dataframe_from_rows(data)

    if df.empty:
        st.info(empty_message)
        return None

    df = normalize_dataframe_for_display(df)

    kwargs: dict[str, Any] = {
        "data": df,
        "width": "stretch",
        "hide_index": True,
        "key": key,
    }

    if height is not None:
        kwargs["height"] = height

    if selectable:
        kwargs["on_select"] = "rerun"
        kwargs["selection_mode"] = "single-row"

    return st.dataframe(**kwargs)


def render_metric_cards(cards: Iterable[tuple[str, Any]], columns: int = 4) -> None:
    """
    Renderiza cards de métricas em colunas.

    cards:
    [
        ("Principal aberto", "R$ 6.000,00"),
        ("Encargos", "R$ 120,00"),
    ]
    """
    cards_list = list(cards)

    if not cards_list:
        return

    for start in range(0, len(cards_list), columns):
        chunk = cards_list[start : start + columns]
        cols = st.columns(len(chunk))

        for col, (label, value) in zip(cols, chunk):
            col.metric(label, value)


def render_resumo_financeiro(resumo: dict[str, Any]) -> None:
    """
    Cards financeiros padrão usados em visão geral e workspace do devedor.
    """
    render_metric_cards(
        [
            ("Principal aberto", format_money(resumo.get("principal_aberto_estimado"))),
            ("Encargos", format_money(resumo.get("encargos"))),
            ("Total atualizado", format_money(resumo.get("total_atualizado"))),
            ("Recebimentos", format_money(resumo.get("pagamentos_considerados"))),
            ("Títulos vencidos", int(resumo.get("titulos_vencidos", 0) or 0)),
            ("Títulos parciais", int(resumo.get("titulos_parciais", 0) or 0)),
            ("Títulos quitados", int(resumo.get("titulos_quitados", 0) or 0)),
            ("Créditos/excedentes", format_money(resumo.get("creditos_excedentes"))),
        ],
        columns=4,
    )


def render_alertas_indices(resumo: dict[str, Any]) -> None:
    """
    Mostra alertas de índices faltantes/provisórios.
    """
    faltando = safe_text(resumo.get("competencias_faltando"))
    provisorias = safe_text(resumo.get("competencias_provisorias"))

    if faltando:
        st.error(f"Índices faltando: {faltando}")

    if provisorias:
        st.warning(f"Índices provisórios usados: {provisorias}")


def render_page_header(title: str, caption: str | None = None) -> None:
    """
    Cabeçalho padrão de página/tela.
    """
    st.title(title)

    if caption:
        st.caption(caption)


def render_section_header(title: str, caption: str | None = None) -> None:
    """
    Cabeçalho padrão de seção.
    """
    st.markdown(f"### {title}")

    if caption:
        st.caption(caption)


def render_subsection_header(title: str, caption: str | None = None) -> None:
    """
    Cabeçalho padrão de subseção.
    """
    st.markdown(f"#### {title}")

    if caption:
        st.caption(caption)


def render_empty_state(
    title: str,
    message: str,
    *,
    icon: str = "ℹ️",
) -> None:
    """
    Estado vazio mais amigável do que apenas tabela vazia.
    """
    st.info(f"{icon} **{title}**\n\n{message}")


def render_status_message(status: str) -> None:
    """
    Mensagem visual simples para status financeiro.
    """
    text = safe_text(status, empty="Sem status")

    if text in {"Vencido", "Parcial vencido", "Em atraso"}:
        st.error(text)
    elif text in {"Parcial", "Em aberto", "Aberto", "A vencer"}:
        st.warning(text)
    elif text in {"Quitado", "Sem saldo em aberto"}:
        st.success(text)
    elif text in {"Cancelado", "Cancelada"}:
        st.info(text)
    else:
        st.caption(text)


def select_devedor(
    label: str,
    *,
    include_all: bool = False,
    key: str | None = None,
    default_devedor_id: int | None = None,
) -> int | None:
    """
    Selectbox padronizado de devedor.

    Não expõe ID interno para o usuário.
    Retorna o ID interno selecionado.
    """
    devedores = db.list_devedores()

    if include_all:
        options: list[dict[str, Any]] = [
            {"id": None, "nome": "Todos", "documento": ""}
        ] + devedores
    else:
        options = devedores

    if not options:
        st.warning("Cadastre pelo menos um devedor primeiro.")
        return None

    labels = ["Todos" if d.get("id") is None else devedor_label(d) for d in options]
    labels = make_unique_labels(labels)

    default_index = 0

    if default_devedor_id is not None:
        for i, d in enumerate(options):
            if d.get("id") == default_devedor_id:
                default_index = i
                break

    chosen = st.selectbox(
        label,
        labels,
        index=default_index,
        key=key,
    )

    return options[labels.index(chosen)]["id"]


def get_devedor_by_id(devedor_id: int | None) -> dict[str, Any] | None:
    """
    Busca um devedor na lista ativa.
    """
    if devedor_id is None:
        return None

    for d in db.list_devedores():
        if int(d["id"]) == int(devedor_id):
            return d

    return None


def ensure_devedor_foco_session() -> None:
    """
    Inicializa st.session_state['devedor_foco_id'] com o primeiro devedor ativo.
    """
    if "devedor_foco_id" in st.session_state:
        return

    devedores = db.list_devedores()

    st.session_state["devedor_foco_id"] = int(devedores[0]["id"]) if devedores else None


def set_devedor_foco(devedor_id: int | None) -> None:
    """
    Define o devedor em foco da sessão.
    """
    st.session_state["devedor_foco_id"] = devedor_id


def get_devedor_foco_id() -> int | None:
    """
    Retorna o devedor em foco da sessão.
    """
    ensure_devedor_foco_session()
    return st.session_state.get("devedor_foco_id")


def render_devedor_foco_sidebar() -> int | None:
    """
    Renderiza o seletor de devedor em foco na sidebar.

    Retorna o devedor_id selecionado.
    """
    ensure_devedor_foco_session()

    devedores = db.list_devedores()

    if not devedores:
        st.info("Nenhum devedor cadastrado.")
        st.session_state["devedor_foco_id"] = None
        return None

    labels = make_unique_labels([devedor_label(d) for d in devedores])

    default_idx = 0
    foco_id = st.session_state.get("devedor_foco_id")

    if foco_id is not None:
        for i, d in enumerate(devedores):
            if int(d["id"]) == int(foco_id):
                default_idx = i
                break

    escolhido = st.selectbox(
        "Devedor em foco",
        labels,
        index=default_idx,
        key="sidebar_devedor_foco",
    )

    devedor_id = int(devedores[labels.index(escolhido)]["id"])
    st.session_state["devedor_foco_id"] = devedor_id

    return devedor_id


def render_devedor_identity(devedor: dict[str, Any]) -> None:
    """
    Cabeçalho humano para o workspace do devedor.
    """
    st.markdown(f"## {safe_text(devedor.get('nome'), empty='Devedor')}")

    details = []

    documento = safe_text(devedor.get("documento"))
    contato = safe_text(devedor.get("contato"))
    observacoes = safe_text(devedor.get("observacoes"))

    if documento:
        details.append(f"Documento: {documento}")

    if contato:
        details.append(f"Contato: {contato}")

    if details:
        st.caption(" · ".join(details))

    if observacoes:
        with st.expander("Observações do devedor", expanded=False):
            st.write(observacoes)


def render_quick_actions(
    *,
    key_prefix: str = "quick_action",
) -> str | None:
    """
    Renderiza botões de ação rápida.

    Retorna:
    - "novo_titulo"
    - "novo_recebimento"
    - "demonstrativo"
    - "linha_tempo"
    - None
    """
    c1, c2, c3, c4 = st.columns(4)

    if c1.button("+ Novo título", width="stretch", key=f"{key_prefix}_novo_titulo"):
        return "novo_titulo"

    if c2.button(
        "+ Registrar recebimento",
        width="stretch",
        key=f"{key_prefix}_novo_recebimento",
    ):
        return "novo_recebimento"

    if c3.button(
        "Gerar demonstrativo",
        width="stretch",
        key=f"{key_prefix}_demonstrativo",
    ):
        return "demonstrativo"

    if c4.button(
        "Ver linha do tempo",
        width="stretch",
        key=f"{key_prefix}_linha_tempo",
    ):
        return "linha_tempo"

    return None


def render_confirmation_checkbox(
    label: str,
    *,
    key: str,
) -> bool:
    """
    Checkbox padronizado para ações destrutivas.
    """
    return st.checkbox(label, key=key)


def render_danger_action(
    *,
    label: str,
    confirmation_label: str,
    key_prefix: str,
) -> bool:
    """
    Renderiza uma ação destrutiva com confirmação explícita.

    Retorna True quando o botão foi pressionado com confirmação marcada.
    """
    confirmed = render_confirmation_checkbox(
        confirmation_label,
        key=f"{key_prefix}_confirm",
    )

    return st.button(
        label,
        disabled=not confirmed,
        key=f"{key_prefix}_button",
    )


def render_download_buttons(
    *,
    excel_bytes: bytes | None = None,
    pdf_bytes: bytes | None = None,
    excel_filename: str = "demonstrativo.xlsx",
    pdf_filename: str = "demonstrativo.pdf",
) -> None:
    """
    Botões padronizados de download.
    """
    cols = st.columns(2)

    with cols[0]:
        if excel_bytes is not None:
            st.download_button(
                "Baixar Excel",
                data=excel_bytes,
                file_name=excel_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )

    with cols[1]:
        if pdf_bytes is not None:
            st.download_button(
                "Baixar PDF",
                data=pdf_bytes,
                file_name=pdf_filename,
                mime="application/pdf",
                width="stretch",
            )


def render_info_box(title: str, body: str) -> None:
    """
    Caixa simples de informação.
    """
    st.info(f"**{title}**\n\n{body}")


def render_warning_box(title: str, body: str) -> None:
    """
    Caixa simples de alerta.
    """
    st.warning(f"**{title}**\n\n{body}")


def render_success_box(title: str, body: str) -> None:
    """
    Caixa simples de sucesso.
    """
    st.success(f"**{title}**\n\n{body}")


def render_error_box(title: str, body: str) -> None:
    """
    Caixa simples de erro.
    """
    st.error(f"**{title}**\n\n{body}")
