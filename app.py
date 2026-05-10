from __future__ import annotations

from datetime import date

import streamlit as st

import database as db
from ui.components import (
    ensure_devedor_foco_session,
    render_devedor_foco_sidebar,
    render_page_header,
)
from ui.dashboard import render_dashboard
from ui.devedor_workspace import render_workspace_devedor
from ui.demonstrativos import render_demonstrativos
from ui.indices import render_indices
from ui.lancamentos import render_lancamentos


st.set_page_config(
    page_title="Conta Certa",
    page_icon="💸",
    layout="wide",
)


def setting_float(settings: dict[str, str], key: str, default: float) -> float:
    """
    Lê configuração numérica salva como texto.

    Aceita vírgula ou ponto decimal.
    """
    try:
        return float(str(settings.get(key, default)).replace(",", "."))
    except Exception:
        return default


def render_sidebar() -> date:
    """
    Renderiza a sidebar global do aplicativo.

    Retorna a data-base usada nos cálculos da sessão.
    """
    with st.sidebar:
        st.header("Contexto")

        data_base = st.date_input(
            "Data-base do cálculo",
            value=date.today(),
            key="app_data_base",
        )

        render_devedor_foco_sidebar()

        st.divider()

        st.header("Índices provisórios")

        settings = db.get_settings()

        usar_prov = st.selectbox(
            "Usar taxa provisória quando faltar mês?",
            ["Sim", "Não"],
            index=0 if settings.get("usar_provisorio", "Sim") == "Sim" else 1,
            key="app_usar_provisorio",
        )

        ipca_prov = st.number_input(
            "IPCA provisório mensal (%)",
            value=setting_float(settings, "ipca_provisorio_pct", 0.60),
            step=0.01,
            format="%.4f",
            key="app_ipca_provisorio",
        )

        taxa_legal_prov = st.number_input(
            "Taxa Legal provisória mensal (%)",
            value=setting_float(settings, "taxa_legal_provisoria_pct", 0.50),
            step=0.01,
            format="%.4f",
            key="app_taxa_legal_provisoria",
        )

        if st.button("Salvar configurações", key="app_salvar_configuracoes"):
            db.set_setting("usar_provisorio", usar_prov)
            db.set_setting("ipca_provisorio_pct", str(ipca_prov))
            db.set_setting("taxa_legal_provisoria_pct", str(taxa_legal_prov))
            st.success("Configurações salvas.")
            st.rerun()

        st.divider()

        st.caption(
            "Os dados ficam no banco SQLite local configurado em `data/cobrancas.db`, "
            "salvo se a variável `COBRANCA_DB` estiver definida."
        )

    return data_base


def main() -> None:
    db.init_db()
    ensure_devedor_foco_session()

    render_page_header(
        "Conta Certa",
        "Controle local de títulos a receber, recebimentos parciais e atualização monetária por IPCA + Taxa Legal.",
    )

    data_base = render_sidebar()

    tabs = st.tabs(
        [
            "Visão geral",
            "Devedor",
            "Lançamentos",
            "Índices",
            "Demonstrativos",
        ]
    )

    with tabs[0]:
        render_dashboard(data_base)

    with tabs[1]:
        render_workspace_devedor(data_base)

    with tabs[2]:
        render_lancamentos(data_base)

    with tabs[3]:
        render_indices(data_base)

    with tabs[4]:
        render_demonstrativos(data_base)


if __name__ == "__main__":
    main()
