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
from ui.navigation import (
    PAGE_CARTEIRA,
    PAGE_CONFIGURACOES,
    PAGE_DEMONSTRATIVOS,
    PAGE_DEVEDOR,
    PAGE_INDICES,
    PAGE_LANCAMENTOS,
    render_navigation_sidebar,
)


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


def render_indices_provisorios_form(*, compact: bool = False) -> None:
    """
    Renderiza configuração de índices provisórios.

    Usado tanto na sidebar quanto na página Configurações.
    """
    settings = db.get_settings()

    usar_prov = st.selectbox(
        "Usar taxa provisória quando faltar mês?",
        ["Sim", "Não"],
        index=0 if settings.get("usar_provisorio", "Sim") == "Sim" else 1,
        key="app_usar_provisorio" if compact else "config_usar_provisorio",
    )

    ipca_prov = st.number_input(
        "IPCA provisório mensal (%)",
        value=setting_float(settings, "ipca_provisorio_pct", 0.60),
        step=0.01,
        format="%.4f",
        key="app_ipca_provisorio" if compact else "config_ipca_provisorio",
    )

    taxa_legal_prov = st.number_input(
        "Taxa Legal provisória mensal (%)",
        value=setting_float(settings, "taxa_legal_provisoria_pct", 0.50),
        step=0.01,
        format="%.4f",
        key="app_taxa_legal_provisoria" if compact else "config_taxa_legal_provisoria",
    )

    if st.button(
        "Salvar configurações",
        key="app_salvar_configuracoes" if compact else "config_salvar_configuracoes",
        width="stretch",
    ):
        db.set_setting("usar_provisorio", usar_prov)
        db.set_setting("ipca_provisorio_pct", str(ipca_prov))
        db.set_setting("taxa_legal_provisoria_pct", str(taxa_legal_prov))
        st.success("Configurações salvas.")
        st.rerun()


def render_sidebar() -> tuple[date, str]:
    """
    Renderiza a sidebar global do aplicativo.

    Ordem pensada para uso diário:
    1. devedor em foco;
    2. navegação;
    3. data-base do cálculo;
    4. índices provisórios.

    Retorna:
    - data-base usada nos cálculos;
    - página atual selecionada.
    """
    data_base_atual = st.session_state.get("app_data_base", date.today())

    with st.sidebar:
        st.header("Conta Certa")

        st.subheader("Devedor em foco")
        render_devedor_foco_sidebar(
            data_base=data_base_atual,
            show_summary=True,
        )

        st.divider()

        pagina = render_navigation_sidebar()

        st.divider()

        st.subheader("Data-base do cálculo")
        data_base = st.date_input(
            "Data usada para atualizar saldos e demonstrativos",
            value=data_base_atual,
            key="app_data_base",
            help=(
                "Normalmente use a data de hoje. "
                "Altere para consultar quanto a carteira valia em outra data, "
                "gerar demonstrativos retroativos ou simular uma data futura."
            ),
        )

        st.caption(
            "Use hoje para cobrança atual. Use outra data para demonstrativo "
            "retroativo, fechamento ou simulação."
        )

        st.divider()

        with st.expander("Índices provisórios", expanded=False):
            render_indices_provisorios_form(compact=True)

        st.divider()

        st.caption(
            "Banco local: `data/cobrancas.db`, salvo se `COBRANCA_DB` estiver definido."
        )

    return data_base, pagina


def render_configuracoes(data_base: date) -> None:
    """
    Página simples de configurações gerais.
    """
    st.subheader("Configurações")

    st.markdown("### Cálculo")

    render_indices_provisorios_form(compact=False)

    st.divider()

    st.markdown("### Data-base")

    st.write(
        "A data-base define até quando o sistema calcula atualização monetária, "
        "recebimentos considerados, saldos, encargos e demonstrativos."
    )

    st.write(
        "Na rotina normal, deixe como a data de hoje. Para conferência ou documentos, "
        "você pode alterar para uma data passada ou futura."
    )

    st.caption(f"Data-base atual da sessão: {data_base.isoformat()}")

    st.divider()

    st.markdown("### Banco de dados local")

    st.write(
        "Por padrão, o Conta Certa usa o banco SQLite em "
        "`data/cobrancas.db`. Para usar outro arquivo, defina a variável "
        "de ambiente `COBRANCA_DB` antes de iniciar o app."
    )

    st.code("COBRANCA_DB=/caminho/para/cobrancas.db streamlit run app.py")

    st.divider()

    st.markdown("### Recomendações")

    st.write(
        "Antes de testar mudanças importantes com dados reais, faça backup do banco."
    )

    st.code("cp data/cobrancas.db data/cobrancas.backup.db")


def main() -> None:
    db.init_db()
    ensure_devedor_foco_session()

    render_page_header(
        "Conta Certa",
        "Carteira local de títulos a receber, recebimentos parciais, atualização monetária e demonstrativos.",
    )

    data_base, pagina = render_sidebar()

    if pagina == PAGE_CARTEIRA:
        render_dashboard(data_base)

    elif pagina == PAGE_DEVEDOR:
        render_workspace_devedor(data_base)

    elif pagina == PAGE_LANCAMENTOS:
        render_lancamentos(data_base)

    elif pagina == PAGE_INDICES:
        render_indices(data_base)

    elif pagina == PAGE_DEMONSTRATIVOS:
        render_demonstrativos(data_base)

    elif pagina == PAGE_CONFIGURACOES:
        render_configuracoes(data_base)

    else:
        st.error(f"Página desconhecida: {pagina}")


if __name__ == "__main__":
    main()
