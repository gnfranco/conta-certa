from __future__ import annotations

import streamlit as st


PAGE_CARTEIRA = "Carteira"
PAGE_DEVEDOR = "Devedor"
PAGE_LANCAMENTOS = "Novo lançamento"
PAGE_INDICES = "Índices"
PAGE_DEMONSTRATIVOS = "Demonstrativos"
PAGE_CONFIGURACOES = "Configurações"

PAGE_SESSION_KEY = "pagina_atual"

PAGE_ORDER = [
    PAGE_CARTEIRA,
    PAGE_DEVEDOR,
    PAGE_LANCAMENTOS,
    PAGE_INDICES,
    PAGE_DEMONSTRATIVOS,
    PAGE_CONFIGURACOES,
]

PAGE_META = {
    PAGE_CARTEIRA: {
        "label": "Carteira",
        "icon": "📊",
        "help": "Visão geral dos devedores, saldos e itens que precisam de atenção.",
    },
    PAGE_DEVEDOR: {
        "label": "Devedor",
        "icon": "👤",
        "help": "Workspace do devedor em foco, com linha do tempo, títulos e recebimentos.",
    },
    PAGE_LANCAMENTOS: {
        "label": "Novo lançamento",
        "icon": "➕",
        "help": "Cadastro rápido de devedores, títulos e recebimentos.",
    },
    PAGE_INDICES: {
        "label": "Índices",
        "icon": "📈",
        "help": "Gestão de IPCA, Taxa Legal e índices provisórios.",
    },
    PAGE_DEMONSTRATIVOS: {
        "label": "Demonstrativos",
        "icon": "📄",
        "help": "Prévia e exportação de demonstrativos em Excel e PDF.",
    },
    PAGE_CONFIGURACOES: {
        "label": "Configurações",
        "icon": "⚙️",
        "help": "Configurações locais, banco de dados e critérios de cálculo.",
    },
}


def ensure_navigation_session() -> None:
    """
    Inicializa a página atual da sessão.
    """
    if PAGE_SESSION_KEY not in st.session_state:
        st.session_state[PAGE_SESSION_KEY] = PAGE_CARTEIRA

    if st.session_state[PAGE_SESSION_KEY] not in PAGE_ORDER:
        st.session_state[PAGE_SESSION_KEY] = PAGE_CARTEIRA


def navigate_to(page: str) -> None:
    """
    Define a página atual.
    """
    if page not in PAGE_ORDER:
        raise ValueError(f"Página inválida: {page}")

    st.session_state[PAGE_SESSION_KEY] = page


def get_current_page() -> str:
    """
    Retorna a página atual da sessão.
    """
    ensure_navigation_session()
    return str(st.session_state[PAGE_SESSION_KEY])


def page_label(page: str) -> str:
    """
    Label humano da página.
    """
    return PAGE_META.get(page, {}).get("label", page)


def page_icon(page: str) -> str:
    """
    Ícone da página.
    """
    return PAGE_META.get(page, {}).get("icon", "")


def page_help(page: str) -> str:
    """
    Texto de ajuda da página.
    """
    return PAGE_META.get(page, {}).get("help", "")


def _inject_navigation_css() -> None:
    """
    Ajustes leves para o menu lateral.

    O item ativo usa estilo inline para ficar estável entre versões/temas
    do Streamlit. Este CSS cuida principalmente do espaçamento geral.
    """
    st.markdown(
        """
        <style>
        div[data-testid="stSidebar"] .cc-nav-title {
            font-size: 0.92rem;
            font-weight: 700;
            margin: 0.25rem 0 0.45rem 0;
            color: rgba(250, 250, 250, 0.92);
        }

        div[data-testid="stSidebar"] .cc-nav-help {
            margin-top: 0.70rem;
            margin-bottom: 0.10rem;
            padding: 0.65rem 0.75rem;
            border-radius: 0.60rem;
            background: rgba(255, 255, 255, 0.055);
            color: rgba(250, 250, 250, 0.74);
            font-size: 0.82rem;
            line-height: 1.38;
        }

        div[data-testid="stSidebar"] div.stButton {
            margin-bottom: 0.32rem;
        }

        div[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] {
            margin-bottom: 0;
        }

        div[data-testid="stSidebar"] div.stButton > button {
            min-height: 2.45rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_active_nav_item(page: str) -> None:
    """
    Renderiza item ativo com espaçamento estável.

    O wrapper externo evita que o próximo botão seja puxado para perto
    do item selecionado.
    """
    icon = page_icon(page)
    label = page_label(page)

    st.markdown(
        f"""
        <div style="
            width: 100%;
            box-sizing: border-box;
            margin: 0 0 0.32rem 0;
            padding: 0;
        ">
            <div style="
                box-sizing: border-box;
                width: 100%;
                min-height: 2.45rem;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.45rem;
                padding: 0.52rem 0.75rem;
                border-radius: 0.50rem;
                border: 1px solid rgba(255, 75, 75, 0.70);
                border-left: 5px solid #ff4b4b;
                background: rgba(255, 75, 75, 0.15);
                color: rgba(255, 255, 255, 0.98);
                font-weight: 700;
                line-height: 1.2;
            ">
                <span style="font-size: 1.02rem;">{icon}</span>
                <span>{label}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_navigation_sidebar() -> str:
    """
    Renderiza a navegação principal no sidebar.

    Usa botões para páginas inativas e um bloco destacado para a página ativa.
    """
    ensure_navigation_session()
    _inject_navigation_css()

    current_page = get_current_page()

    st.markdown(
        '<div class="cc-nav-title">Navegação</div>',
        unsafe_allow_html=True,
    )

    for page in PAGE_ORDER:
        icon = page_icon(page)
        label = page_label(page)

        if page == current_page:
            render_active_nav_item(page)
            continue

        if st.button(
            f"{icon}  {label}",
            key=f"nav_button_{page}",
            width="stretch",
        ):
            navigate_to(page)
            st.rerun()

    help_text = page_help(current_page)

    if help_text:
        st.markdown(
            f'<div class="cc-nav-help">{help_text}</div>',
            unsafe_allow_html=True,
        )

    return get_current_page()


def render_navigation_buttons(
    *,
    show_labels: bool = True,
    key_prefix: str = "nav_buttons",
) -> str | None:
    """
    Renderiza botões horizontais de navegação.

    Disponível para atalhos futuros dentro das páginas.
    """
    cols = st.columns(len(PAGE_ORDER))

    for col, page in zip(cols, PAGE_ORDER):
        label = page_label(page) if show_labels else page
        icon = page_icon(page)

        if col.button(
            f"{icon} {label}",
            key=f"{key_prefix}_{page}",
            width="stretch",
        ):
            navigate_to(page)
            return page

    return None


def render_page_context_hint(page: str | None = None) -> None:
    """
    Mostra uma breve dica da página atual.
    """
    current = page or get_current_page()
    help_text = page_help(current)

    if help_text:
        st.caption(help_text)
