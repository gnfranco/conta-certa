from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import bcb
import database as db
from calculos import calcular_carteira, money
from reports import gerar_excel, gerar_pdf

st.set_page_config(
    page_title="Conta Certa",
    page_icon="💸",
    layout="wide",
)

db.init_db()


TIPOS_TITULO = [
    "Mensalidade",
    "Décimo terceiro",
    "Férias",
    "Empréstimo",
    "Reembolso",
    "Serviço",
    "Outros",
]


def df_or_empty(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def unique_keep_order(values: list[str]) -> list[str]:
    seen = set()
    out = []

    for v in values:
        value = (v or "").strip()

        if not value:
            continue

        key = value.lower()

        if key not in seen:
            seen.add(key)
            out.append(value)

    return out


def option_index(options: list[str], value: str | None, default: int = 0) -> int:
    if value is None:
        return default

    try:
        return options.index(value)
    except ValueError:
        return default


def parse_iso_date(value: str | date) -> date:
    if isinstance(value, date):
        return value

    return date.fromisoformat(str(value)[:10])


def format_date_br(value: str | date | None) -> str:
    if not value:
        return ""

    try:
        return parse_iso_date(value).strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def format_number(v: float | int | None) -> str:
    if v is None:
        return ""

    return money(float(v))


def make_unique_labels(labels: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    result = []

    for label in labels:
        counts[label] = counts.get(label, 0) + 1

        if counts[label] == 1:
            result.append(label)
        else:
            result.append(f"{label} ({counts[label]})")

    return result


def devedor_label(devedor: dict) -> str:
    nome = str(devedor.get("nome") or "").strip()
    documento = str(devedor.get("documento") or "").strip()

    if documento:
        return f"{nome} — {documento}"

    return nome


def select_devedor(label: str, include_all: bool = False, key: str | None = None):
    devedores = db.list_devedores()

    if include_all:
        options = [{"id": None, "nome": "Todos", "documento": ""}] + devedores
    else:
        options = devedores

    if not options:
        st.warning("Cadastre pelo menos um devedor primeiro.")
        return None

    labels = ["Todos" if d["id"] is None else devedor_label(d) for d in options]
    labels = make_unique_labels(labels)

    chosen = st.selectbox(label, labels, key=key)

    return options[labels.index(chosen)]["id"]


def group_options_for_devedor(
    devedor_id: int,
    include_suggestions: bool = True,
) -> list[str]:
    grupos = db.list_grupos(devedor_id)
    existentes = [g["nome"] for g in grupos]

    if include_suggestions:
        return unique_keep_order(
            [db.DEFAULT_GROUP_NAME] + existentes + db.SUGGESTED_GROUPS
        )

    return unique_keep_order([db.DEFAULT_GROUP_NAME] + existentes)


def max_data_movimentacao_devedor(devedor_id: int) -> date:
    datas = [date.today()]

    for p in db.list_pagamentos(devedor_id=devedor_id):
        datas.append(parse_iso_date(p["data_pagamento"]))

    for d in db.list_dividas(devedor_id=devedor_id, incluir_canceladas=True):
        datas.append(parse_iso_date(d["data_vencimento"]))

    return max(datas)


def divida_tem_pagamento_alocado(divida_id: int) -> bool:
    """
    Verifica se um título já recebeu recebimento.

    Como as baixas ainda são calculadas dinamicamente, combinamos:
    1. recebimentos lançados diretamente no título;
    2. resultado calculado de baixas automáticas.
    """
    if db.count_pagamentos_diretos_divida(divida_id) > 0:
        return True

    divida = db.get_divida(divida_id)

    if not divida:
        return False

    devedor_id = int(divida["devedor_id"])
    data_limite = max_data_movimentacao_devedor(devedor_id)

    resultado = calcular_carteira(
        db.list_dividas(devedor_id=devedor_id, incluir_canceladas=True),
        db.list_pagamentos(devedor_id=devedor_id),
        db.taxas_dict(),
        db.get_settings(),
        data_limite,
        devedor_id=devedor_id,
    )

    for alocacao in resultado["alocacoes"]:
        if int(alocacao.get("divida_id") or 0) != int(divida_id):
            continue

        if float(alocacao.get("valor_alocado") or 0) > 0:
            return True

    return False


def selected_row_index(event) -> int | None:
    try:
        rows = event.selection.rows
    except Exception:
        rows = []

    if not rows:
        return None

    return int(rows[0])


def build_titulo_calc_map(resultado: dict) -> dict[int, dict]:
    return {
        int(t["id"]): t for t in resultado.get("titulos", resultado.get("dividas", []))
    }


def build_titulos_view(
    titulos: list[dict],
    resultado: dict,
    data_base: date,
) -> tuple[pd.DataFrame, list[dict]]:
    calc_map = build_titulo_calc_map(resultado)
    rows = []
    records = []

    for titulo in titulos:
        titulo_id = int(titulo["id"])
        calc = calc_map.get(titulo_id)

        vencimento = parse_iso_date(titulo["data_vencimento"])
        status_admin = titulo.get("status") or "Aberta"

        if status_admin == "Cancelada":
            situacao = "Cancelado"
            principal = None
            encargos = None
            saldo = None
            total_recebido = None
        elif calc:
            situacao = calc.get("situacao_financeira") or "Aberto"
            principal = calc.get("principal_aberto_estimado")
            encargos = calc.get("encargos")
            saldo = calc.get("saldo_atualizado")
            total_recebido = calc.get("total_recebido")
        elif vencimento > data_base:
            situacao = "A vencer"
            principal = float(titulo["valor_original"])
            encargos = 0.0
            saldo = float(titulo["valor_original"])
            total_recebido = 0.0
        else:
            situacao = "Aberto"
            principal = float(titulo["valor_original"])
            encargos = 0.0
            saldo = float(titulo["valor_original"])
            total_recebido = 0.0

        row = {
            "Ref.": titulo.get("public_ref") or "",
            "Devedor": titulo.get("devedor") or "",
            "Grupo": titulo.get("grupo") or db.DEFAULT_GROUP_NAME,
            "Tipo": titulo.get("tipo") or "",
            "Competência": titulo.get("competencia") or "",
            "Descrição": titulo.get("descricao") or "",
            "Vencimento": format_date_br(titulo.get("data_vencimento")),
            "Valor original": format_number(float(titulo["valor_original"])),
            "Recebido": format_number(total_recebido)
            if total_recebido is not None
            else "",
            "Principal aberto": format_number(principal)
            if principal is not None
            else "",
            "Encargos": format_number(encargos) if encargos is not None else "",
            "Saldo atualizado": format_number(saldo) if saldo is not None else "",
            "Situação": situacao,
            "Status adm.": status_admin,
        }

        rows.append(row)
        records.append(titulo)

    return pd.DataFrame(rows), records


def build_recebimentos_view(
    recebimentos: list[dict],
) -> tuple[pd.DataFrame, list[dict]]:
    rows = []

    for p in recebimentos:
        if p.get("divida_descricao"):
            destino = (
                f"{p.get('divida_public_ref') or 'Título'} — "
                f"{p.get('divida_descricao')}"
            )
            modo = "Título específico"
        elif p.get("grupo"):
            destino = f"Grupo: {p.get('grupo')}"
            modo = "Automático por grupo"
        else:
            destino = "Todos os grupos"
            modo = "Automático geral"

        rows.append(
            {
                "Ref.": p.get("public_ref") or "",
                "Data": format_date_br(p.get("data_pagamento")),
                "Devedor": p.get("devedor") or "",
                "Valor": format_number(float(p["valor"])),
                "Modo": modo,
                "Destino": destino,
                "Histórico": p.get("descricao") or "",
                "Comprovante": p.get("comprovante_ref") or "",
            }
        )

    return pd.DataFrame(rows), recebimentos


def build_baixas_view(baixas: list[dict]) -> pd.DataFrame:
    rows = []

    for b in baixas:
        rows.append(
            {
                "Recebimento": b.get("pagamento_ref") or "",
                "Data": format_date_br(b.get("data_pagamento")),
                "Devedor": b.get("devedor") or "",
                "Grupo": b.get("grupo") or "",
                "Título": b.get("titulo_ref") or b.get("divida_ref") or "",
                "Histórico": b.get("titulo") or b.get("divida") or "",
                "Tipo": b.get("tipo_alocacao") or "Baixa",
                "Valor": format_number(float(b.get("valor_alocado") or 0)),
            }
        )

    return pd.DataFrame(rows)


def filter_records_by_search(
    records: list[dict], text: str, fields: list[str]
) -> list[dict]:
    term = (text or "").strip().lower()

    if not term:
        return records

    filtered = []

    for record in records:
        haystack = " ".join(
            str(record.get(field, "") or "") for field in fields
        ).lower()

        if term in haystack:
            filtered.append(record)

    return filtered


def apply_titulos_filters(
    titulos: list[dict],
    *,
    devedor: str,
    grupo: str,
    status: str,
    busca: str,
) -> list[dict]:
    filtered = titulos

    if devedor != "Todos":
        filtered = [t for t in filtered if t.get("devedor") == devedor]

    if grupo != "Todos":
        filtered = [
            t for t in filtered if (t.get("grupo") or db.DEFAULT_GROUP_NAME) == grupo
        ]

    if status != "Todos":
        filtered = [t for t in filtered if (t.get("status") or "Aberta") == status]

    filtered = filter_records_by_search(
        filtered,
        busca,
        [
            "public_ref",
            "devedor",
            "grupo",
            "tipo",
            "competencia",
            "descricao",
            "status",
        ],
    )

    return filtered


def apply_recebimentos_filters(
    recebimentos: list[dict],
    *,
    devedor: str,
    busca: str,
) -> list[dict]:
    filtered = recebimentos

    if devedor != "Todos":
        filtered = [p for p in filtered if p.get("devedor") == devedor]

    filtered = filter_records_by_search(
        filtered,
        busca,
        [
            "public_ref",
            "devedor",
            "grupo",
            "divida_public_ref",
            "divida_descricao",
            "descricao",
            "comprovante_ref",
        ],
    )

    return filtered


def devedor_options_from_records(records: list[dict]) -> list[str]:
    return ["Todos"] + sorted(
        {str(r.get("devedor") or "") for r in records if r.get("devedor")}
    )


def grupo_options_from_records(records: list[dict]) -> list[str]:
    return ["Todos"] + sorted(
        {str(r.get("grupo") or db.DEFAULT_GROUP_NAME) for r in records}
    )


st.title("Conta Certa")
st.caption(
    "Controle local de títulos a receber, recebimentos parciais e atualização monetária por IPCA + Taxa Legal."
)

with st.sidebar:
    st.header("Configuração")

    data_base = st.date_input("Data-base do cálculo", value=date.today())
    settings = db.get_settings()

    usar_prov = st.selectbox(
        "Usar taxa provisória quando faltar mês?",
        ["Sim", "Não"],
        index=0 if settings.get("usar_provisorio", "Sim") == "Sim" else 1,
    )

    ipca_prov = st.number_input(
        "IPCA provisório mensal (%)",
        value=float(settings.get("ipca_provisorio_pct", "0.60").replace(",", ".")),
        step=0.01,
        format="%.4f",
    )

    tl_prov = st.number_input(
        "Taxa Legal provisória mensal (%)",
        value=float(
            settings.get("taxa_legal_provisoria_pct", "0.50").replace(",", ".")
        ),
        step=0.01,
        format="%.4f",
    )

    if st.button("Salvar configurações"):
        db.set_setting("usar_provisorio", usar_prov)
        db.set_setting("ipca_provisorio_pct", str(ipca_prov))
        db.set_setting("taxa_legal_provisoria_pct", str(tl_prov))
        st.success("Configurações salvas.")
        st.rerun()

tabs = st.tabs(
    [
        "Dashboard",
        "Devedores",
        "Títulos",
        "Recebimentos",
        "Índices",
        "Demonstrativos",
    ]
)


with tabs[0]:
    st.subheader("Dashboard")

    devedor_id = select_devedor("Ver devedor", include_all=True, key="dash_devedor")

    resultado = calcular_carteira(
        db.list_dividas(devedor_id=None),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=devedor_id,
    )

    resumo = resultado["resumo"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Principal aberto", money(resumo["principal_aberto_estimado"]))
    c2.metric("Encargos", money(resumo["encargos"]))
    c3.metric("Total atualizado", money(resumo["total_atualizado"]))
    c4.metric("Recebimentos considerados", money(resumo["pagamentos_considerados"]))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Títulos vencidos", int(resumo.get("titulos_vencidos", 0)))
    c6.metric("Títulos parciais", int(resumo.get("titulos_parciais", 0)))
    c7.metric("Títulos quitados", int(resumo.get("titulos_quitados", 0)))
    c8.metric("Créditos/excedentes", money(resumo.get("creditos_excedentes", 0.0)))

    if resumo["competencias_faltando"]:
        st.error(f"Índices faltando: {resumo['competencias_faltando']}")

    if resumo["competencias_provisorias"]:
        st.warning(f"Índices provisórios usados: {resumo['competencias_provisorias']}")

    st.markdown("### Títulos atualizados")

    df_titulos_dashboard = df_or_empty(resultado.get("titulos", resultado["dividas"]))

    if not df_titulos_dashboard.empty:
        dashboard_rows = []

        for _, r in df_titulos_dashboard.iterrows():
            dashboard_rows.append(
                {
                    "Ref.": r.get("titulo_ref") or r.get("public_ref") or "",
                    "Devedor": r.get("devedor") or "",
                    "Grupo": r.get("grupo") or "",
                    "Tipo": r.get("tipo") or "",
                    "Competência": r.get("competencia") or "",
                    "Descrição": r.get("descricao") or "",
                    "Vencimento": format_date_br(r.get("vencimento")),
                    "Principal aberto": format_number(
                        r.get("principal_aberto_estimado")
                    ),
                    "Encargos": format_number(r.get("encargos")),
                    "Saldo atualizado": format_number(r.get("saldo_atualizado")),
                    "Situação": r.get("situacao_financeira") or "",
                    "Status adm.": r.get("status_administrativo") or "",
                }
            )

        st.dataframe(
            pd.DataFrame(dashboard_rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nenhum título vencido até a data-base.")

    st.markdown("### Baixas e excedentes")

    df_baixas = build_baixas_view(resultado.get("baixas", resultado["alocacoes"]))

    if not df_baixas.empty:
        st.dataframe(df_baixas, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum recebimento considerado.")


with tabs[1]:
    st.subheader("Devedores")

    with st.expander("Novo devedor", expanded=True):
        with st.form("form_devedor"):
            nome = st.text_input("Nome")
            documento = st.text_input("Documento/identificação (opcional)")
            contato = st.text_input("Contato (opcional)")
            obs = st.text_area("Observações")

            submitted = st.form_submit_button("Cadastrar devedor")

            if submitted:
                if not nome.strip():
                    st.error("Informe o nome.")
                else:
                    db.add_devedor(nome, documento, contato, obs)
                    st.success("Devedor cadastrado.")
                    st.rerun()

    st.markdown("### Devedores cadastrados")

    devs = db.list_devedores()

    if devs:
        dev_rows = []

        for d in devs:
            dev_rows.append(
                {
                    "Nome": d.get("nome") or "",
                    "Documento": d.get("documento") or "",
                    "Contato": d.get("contato") or "",
                    "Observações": d.get("observacoes") or "",
                    "Criado em": d.get("created_at") or "",
                }
            )

        dev_event = st.dataframe(
            pd.DataFrame(dev_rows),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="devedores_table",
        )

        idx = selected_row_index(dev_event)

        if idx is not None:
            devedor = devs[idx]

            st.markdown(f"#### {devedor['nome']}")
            st.caption("Devedor selecionado.")

            with st.expander("Ações do devedor"):
                confirmar = st.checkbox(
                    "Confirmo que desejo desativar este devedor",
                    key="confirm_desativar_devedor",
                )

                if st.button("Desativar devedor", disabled=not confirmar):
                    db.delete_devedor(int(devedor["id"]))
                    st.success("Devedor desativado.")
                    st.rerun()
    else:
        st.info("Nenhum devedor cadastrado.")


with tabs[2]:
    st.subheader("Títulos")

    devedores = db.list_devedores()

    if devedores:
        with st.expander("Novo título a receber", expanded=False):
            with st.form("form_divida"):
                labels_base = [devedor_label(d) for d in devedores]
                labels = make_unique_labels(labels_base)
                escolhido = st.selectbox("Devedor", labels)
                devedor = devedores[labels.index(escolhido)]

                grupo_options = group_options_for_devedor(
                    devedor["id"],
                    include_suggestions=True,
                )

                grupo_escolhido = st.selectbox(
                    "Grupo",
                    grupo_options,
                    index=grupo_options.index(db.DEFAULT_GROUP_NAME)
                    if db.DEFAULT_GROUP_NAME in grupo_options
                    else 0,
                )

                novo_grupo = st.text_input(
                    "Criar novo grupo, se necessário",
                    placeholder="Ex.: Mensalidades 2026, Acordo antigo, Contrato X",
                )

                tipo = st.selectbox("Tipo", TIPOS_TITULO)

                descricao = st.text_input("Descrição", value="")
                competencia_titulo = st.text_input(
                    "Competência",
                    placeholder="Ex.: 2026-04, 2025, 2024-2025",
                )
                valor = st.number_input(
                    "Valor original",
                    min_value=0.0,
                    step=100.0,
                    format="%.2f",
                )
                vencimento = st.date_input("Data de vencimento", value=date.today())
                obs = st.text_area("Observações do título")

                submitted = st.form_submit_button("Cadastrar título")

                if submitted:
                    if valor <= 0:
                        st.error("Informe valor maior que zero.")
                    elif not descricao.strip():
                        st.error("Informe descrição.")
                    else:
                        nome_grupo = novo_grupo.strip() or grupo_escolhido
                        grupo_id = db.get_or_create_grupo(devedor["id"], nome_grupo)

                        db.add_divida(
                            devedor["id"],
                            descricao,
                            tipo,
                            valor,
                            vencimento.isoformat(),
                            obs,
                            grupo_id=grupo_id,
                            competencia=competencia_titulo,
                        )

                        st.success("Título cadastrado.")
                        st.rerun()

    st.markdown("### Carteira de títulos")

    divs_all = db.list_dividas(incluir_canceladas=True)

    resultado_titulos = calcular_carteira(
        db.list_dividas(devedor_id=None, incluir_canceladas=True),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=None,
    )

    if divs_all:
        fc1, fc2, fc3, fc4 = st.columns([1.3, 1.2, 1.1, 2.0])

        with fc1:
            filtro_devedor = st.selectbox(
                "Devedor",
                devedor_options_from_records(divs_all),
                key="titulos_filtro_devedor",
            )

        with fc2:
            filtro_grupo = st.selectbox(
                "Grupo",
                grupo_options_from_records(divs_all),
                key="titulos_filtro_grupo",
            )

        with fc3:
            filtro_status = st.selectbox(
                "Status adm.",
                ["Todos"] + list(db.ADMIN_STATUSES),
                key="titulos_filtro_status",
            )

        with fc4:
            busca_titulo = st.text_input(
                "Buscar",
                placeholder="Ref., descrição, grupo, competência...",
                key="titulos_busca",
            )

        divs_filtered = apply_titulos_filters(
            divs_all,
            devedor=filtro_devedor,
            grupo=filtro_grupo,
            status=filtro_status,
            busca=busca_titulo,
        )

        df_view, filtered_records = build_titulos_view(
            divs_filtered,
            resultado_titulos,
            data_base,
        )

        if not df_view.empty:
            titulos_event = st.dataframe(
                df_view,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="titulos_table",
            )

            idx = selected_row_index(titulos_event)

            if idx is not None:
                divida = filtered_records[idx]
                divida_id = int(divida["id"])
                tem_pagamento = divida_tem_pagamento_alocado(divida_id)

                st.markdown(f"### Título {divida.get('public_ref') or ''}")
                st.caption(
                    f"{divida.get('devedor')} · {divida.get('grupo') or db.DEFAULT_GROUP_NAME}"
                )

                if tem_pagamento:
                    st.warning(
                        "Este título já recebeu baixa/recebimento. "
                        "Valor original e vencimento ficam bloqueados; "
                        "apenas metadados podem ser alterados."
                    )
                else:
                    st.info(
                        "Este título ainda não recebeu baixa/recebimento. "
                        "Valor original e vencimento podem ser alterados."
                    )

                grupos_edit = group_options_for_devedor(
                    int(divida["devedor_id"]),
                    include_suggestions=True,
                )

                grupo_atual = divida.get("grupo") or db.DEFAULT_GROUP_NAME

                if grupo_atual not in grupos_edit:
                    grupos_edit.append(grupo_atual)

                tipos = list(TIPOS_TITULO)
                tipo_atual = divida.get("tipo") or "Outros"

                if tipo_atual not in tipos:
                    tipos.append(tipo_atual)

                status_options = list(db.ADMIN_STATUSES)
                status_atual = divida.get("status") or "Aberta"

                if status_atual not in status_options:
                    status_options.append(status_atual)

                with st.form("form_editar_divida"):
                    ec1, ec2 = st.columns(2)

                    with ec1:
                        grupo_edit = st.selectbox(
                            "Grupo",
                            grupos_edit,
                            index=option_index(grupos_edit, grupo_atual),
                            key="editar_divida_grupo",
                        )

                    with ec2:
                        novo_grupo_edit = st.text_input(
                            "Criar novo grupo, se necessário",
                            placeholder="Ex.: Mensalidades 2026, Acordo antigo",
                            key="editar_divida_novo_grupo",
                        )

                    ec3, ec4 = st.columns(2)

                    with ec3:
                        tipo_edit = st.selectbox(
                            "Tipo",
                            tipos,
                            index=option_index(tipos, tipo_atual),
                            key="editar_divida_tipo",
                        )

                    with ec4:
                        competencia_edit = st.text_input(
                            "Competência",
                            value=divida.get("competencia") or "",
                            key="editar_divida_competencia",
                        )

                    descricao_edit = st.text_input(
                        "Descrição",
                        value=divida.get("descricao") or "",
                        key="editar_divida_descricao",
                    )

                    ec5, ec6, ec7 = st.columns(3)

                    with ec5:
                        valor_edit = st.number_input(
                            "Valor original",
                            min_value=0.0,
                            value=float(divida["valor_original"]),
                            step=100.0,
                            format="%.2f",
                            disabled=tem_pagamento,
                            key="editar_divida_valor",
                        )

                    with ec6:
                        vencimento_edit = st.date_input(
                            "Data de vencimento",
                            value=parse_iso_date(divida["data_vencimento"]),
                            disabled=tem_pagamento,
                            key="editar_divida_vencimento",
                        )

                    with ec7:
                        status_edit = st.selectbox(
                            "Status administrativo",
                            status_options,
                            index=option_index(status_options, status_atual),
                            key="editar_divida_status",
                        )

                    obs_edit = st.text_area(
                        "Observações",
                        value=divida.get("observacoes") or "",
                        key="editar_divida_obs",
                    )

                    submitted_edit = st.form_submit_button("Salvar alterações")

                    if submitted_edit:
                        if not descricao_edit.strip():
                            st.error("Informe descrição.")
                        else:
                            try:
                                nome_grupo = novo_grupo_edit.strip() or grupo_edit
                                grupo_id = db.get_or_create_grupo(
                                    int(divida["devedor_id"]),
                                    nome_grupo,
                                )

                                db.update_divida(
                                    divida_id,
                                    grupo_id=grupo_id,
                                    descricao=descricao_edit,
                                    tipo=tipo_edit,
                                    competencia=competencia_edit,
                                    observacoes=obs_edit,
                                    status=status_edit,
                                    valor_original=valor_edit,
                                    data_vencimento=vencimento_edit.isoformat(),
                                    permitir_alterar_valor_vencimento=not tem_pagamento,
                                )

                                st.success("Título atualizado.")
                                st.rerun()

                            except Exception as e:
                                st.error(f"Não foi possível atualizar o título: {e}")

                with st.expander("Ações administrativas do título"):
                    if status_atual == "Cancelada":
                        st.info("Este título já está cancelado.")
                    else:
                        confirmar_cancelamento = st.checkbox(
                            "Confirmo que desejo cancelar este título",
                            key="confirm_cancelar_titulo",
                        )

                        if st.button(
                            "Cancelar título",
                            disabled=not confirmar_cancelamento,
                            key="btn_cancelar_titulo",
                        ):
                            try:
                                db.delete_divida(divida_id)
                                st.success("Título cancelado.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Não foi possível cancelar o título: {e}")
            else:
                st.caption("Selecione uma linha da tabela para ver detalhes e editar.")
        else:
            st.info("Nenhum título encontrado com os filtros atuais.")
    else:
        st.info("Nenhum título cadastrado.")


with tabs[3]:
    st.subheader("Recebimentos")

    devedores = db.list_devedores()

    if devedores:
        with st.expander("Novo recebimento", expanded=False):
            with st.form("form_pagamento"):
                labels_base = [devedor_label(d) for d in devedores]
                labels = make_unique_labels(labels_base)
                escolhido = st.selectbox("Devedor", labels, key="pag_devedor")
                devedor = devedores[labels.index(escolhido)]

                modo = st.radio(
                    "Modo de alocação",
                    [
                        "Automático",
                        "Título específico",
                    ],
                    horizontal=True,
                )

                divida_id = None
                grupo_id = None

                if modo == "Automático":
                    grupos = db.list_grupos(devedor["id"])
                    grupo_labels = ["Todos os grupos"] + [g["nome"] for g in grupos]
                    grupo_escolhido = st.selectbox(
                        "Grupo opcional para alocação automática",
                        grupo_labels,
                    )

                    if grupo_escolhido != "Todos os grupos":
                        grupos_por_nome = {g["nome"]: int(g["id"]) for g in grupos}
                        grupo_id = grupos_por_nome[grupo_escolhido]

                    st.caption(
                        "Sem grupo selecionado, o recebimento baixa o título vencido mais antigo do devedor. "
                        "Com grupo selecionado, baixa o título vencido mais antigo dentro daquele grupo."
                    )

                else:
                    dividas_devedor = db.list_dividas(devedor_id=devedor["id"])

                    if not dividas_devedor:
                        st.warning("Este devedor ainda não tem títulos abertos.")
                    else:
                        divida_labels = [
                            (
                                f"{d.get('public_ref') or 'Título'} · "
                                f"{d['grupo']} · {d['descricao']} · "
                                f"venc. {format_date_br(d['data_vencimento'])} · "
                                f"{format_number(float(d['valor_original']))}"
                            )
                            for d in dividas_devedor
                        ]

                        divida_escolhida = st.selectbox(
                            "Título que o recebimento deve baixar",
                            divida_labels,
                        )

                        divida_id = dividas_devedor[
                            divida_labels.index(divida_escolhida)
                        ]["id"]

                    st.caption(
                        "Neste modo, o recebimento baixa exatamente o título selecionado."
                    )

                data_pag = st.date_input("Data do recebimento", value=date.today())
                valor = st.number_input(
                    "Valor recebido",
                    min_value=0.0,
                    step=100.0,
                    format="%.2f",
                )
                descricao = st.text_input("Histórico", value="PIX recebido")
                comprovante = st.text_input(
                    "Referência do comprovante/arquivo (opcional)"
                )

                submitted = st.form_submit_button("Registrar recebimento")

                if submitted:
                    if valor <= 0:
                        st.error("Informe valor maior que zero.")
                    elif modo == "Título específico" and not divida_id:
                        st.error("Escolha um título específico.")
                    else:
                        db.add_pagamento(
                            devedor["id"],
                            divida_id,
                            data_pag.isoformat(),
                            valor,
                            descricao,
                            comprovante,
                            grupo_id=grupo_id,
                        )

                        st.success("Recebimento registrado.")
                        st.rerun()

    st.markdown("### Recebimentos cadastrados")

    pags_all = db.list_pagamentos()

    if pags_all:
        pc1, pc2 = st.columns([1.2, 2.0])

        with pc1:
            filtro_devedor_rec = st.selectbox(
                "Devedor",
                devedor_options_from_records(pags_all),
                key="recebimentos_filtro_devedor",
            )

        with pc2:
            busca_rec = st.text_input(
                "Buscar",
                placeholder="Ref., histórico, comprovante, destino...",
                key="recebimentos_busca",
            )

        pags_filtered = apply_recebimentos_filters(
            pags_all,
            devedor=filtro_devedor_rec,
            busca=busca_rec,
        )

        df_rec_view, rec_records = build_recebimentos_view(pags_filtered)

        if not df_rec_view.empty:
            rec_event = st.dataframe(
                df_rec_view,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="recebimentos_table",
            )

            idx = selected_row_index(rec_event)

            if idx is not None:
                pagamento = rec_records[idx]
                pagamento_id = int(pagamento["id"])
                devedor_id_pagamento = int(pagamento["devedor_id"])

                st.markdown(f"### Recebimento {pagamento.get('public_ref') or ''}")
                st.caption(
                    "Alterar um recebimento recalcula baixas e saldos. "
                    "Por enquanto, o devedor do recebimento não é alterado nesta tela."
                )

                modo_atual = (
                    "Título específico" if pagamento.get("divida_id") else "Automático"
                )

                with st.form("form_editar_pagamento"):
                    modo_edit = st.radio(
                        "Modo de alocação",
                        ["Automático", "Título específico"],
                        index=0 if modo_atual == "Automático" else 1,
                        horizontal=True,
                        key="editar_pagamento_modo",
                    )

                    divida_id_edit = None
                    grupo_id_edit = None

                    if modo_edit == "Automático":
                        grupos = db.list_grupos(devedor_id_pagamento)
                        grupo_labels = ["Todos os grupos"] + [g["nome"] for g in grupos]

                        grupo_atual = pagamento.get("grupo") or "Todos os grupos"

                        grupo_edit = st.selectbox(
                            "Grupo opcional para alocação automática",
                            grupo_labels,
                            index=option_index(grupo_labels, grupo_atual),
                            key="editar_pagamento_grupo",
                        )

                        if grupo_edit != "Todos os grupos":
                            grupos_por_nome = {g["nome"]: int(g["id"]) for g in grupos}
                            grupo_id_edit = grupos_por_nome[grupo_edit]

                    else:
                        dividas_devedor = db.list_dividas(
                            devedor_id=devedor_id_pagamento
                        )

                        if not dividas_devedor:
                            st.warning("Este devedor não tem títulos abertos.")
                        else:
                            divida_labels = [
                                (
                                    f"{d.get('public_ref') or 'Título'} · "
                                    f"{d['grupo']} · {d['descricao']} · "
                                    f"venc. {format_date_br(d['data_vencimento'])} · "
                                    f"{format_number(float(d['valor_original']))}"
                                )
                                for d in dividas_devedor
                            ]

                            divida_ids = [int(d["id"]) for d in dividas_devedor]
                            divida_atual_id = (
                                int(pagamento["divida_id"])
                                if pagamento.get("divida_id")
                                else None
                            )

                            if divida_atual_id in divida_ids:
                                idx_divida = divida_ids.index(divida_atual_id)
                            else:
                                idx_divida = 0

                            divida_edit = st.selectbox(
                                "Título que o recebimento deve baixar",
                                divida_labels,
                                index=idx_divida,
                                key="editar_pagamento_divida",
                            )

                            divida_id_edit = dividas_devedor[
                                divida_labels.index(divida_edit)
                            ]["id"]

                    pc3, pc4 = st.columns(2)

                    with pc3:
                        data_pag_edit = st.date_input(
                            "Data do recebimento",
                            value=parse_iso_date(pagamento["data_pagamento"]),
                            key="editar_pagamento_data",
                        )

                    with pc4:
                        valor_edit = st.number_input(
                            "Valor recebido",
                            min_value=0.0,
                            value=float(pagamento["valor"]),
                            step=100.0,
                            format="%.2f",
                            key="editar_pagamento_valor",
                        )

                    descricao_edit = st.text_input(
                        "Histórico",
                        value=pagamento.get("descricao") or "",
                        key="editar_pagamento_descricao",
                    )

                    comprovante_edit = st.text_input(
                        "Referência do comprovante/arquivo",
                        value=pagamento.get("comprovante_ref") or "",
                        key="editar_pagamento_comprovante",
                    )

                    submitted_pagamento_edit = st.form_submit_button(
                        "Salvar alterações"
                    )

                    if submitted_pagamento_edit:
                        if valor_edit <= 0:
                            st.error("Informe valor maior que zero.")
                        elif modo_edit == "Título específico" and not divida_id_edit:
                            st.error("Escolha um título específico.")
                        else:
                            try:
                                db.update_pagamento(
                                    pagamento_id,
                                    devedor_id=devedor_id_pagamento,
                                    divida_id=divida_id_edit,
                                    grupo_id=grupo_id_edit,
                                    data_pagamento=data_pag_edit.isoformat(),
                                    valor=valor_edit,
                                    descricao=descricao_edit,
                                    comprovante_ref=comprovante_edit,
                                )

                                st.success("Recebimento atualizado.")
                                st.rerun()

                            except Exception as e:
                                st.error(
                                    f"Não foi possível atualizar o recebimento: {e}"
                                )

                with st.expander("Ações do recebimento"):
                    confirmar_exclusao = st.checkbox(
                        "Confirmo que desejo excluir este recebimento",
                        key="confirm_excluir_recebimento",
                    )

                    if st.button(
                        "Excluir recebimento",
                        disabled=not confirmar_exclusao,
                        key="btn_excluir_recebimento",
                    ):
                        try:
                            db.delete_pagamento(pagamento_id)
                            st.success("Recebimento excluído.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Não foi possível excluir o recebimento: {e}")
            else:
                st.caption("Selecione uma linha da tabela para ver detalhes e editar.")
        else:
            st.info("Nenhum recebimento encontrado com os filtros atuais.")
    else:
        st.info("Nenhum recebimento registrado.")


with tabs[4]:
    st.subheader("Índices IPCA + Taxa Legal")

    st.write(
        "Atualize os índices oficiais pela API SGS do Banco Central ou cadastre manualmente."
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        inicio = st.date_input("Buscar de", value=date(2024, 8, 1), key="taxa_inicio")

    with c2:
        fim = st.date_input("Buscar até", value=date.today(), key="taxa_fim")

    with c3:
        st.write("")
        st.write("")

        if st.button("Atualizar via BCB"):
            try:
                df = bcb.buscar_ipca_e_taxa_legal(inicio, fim)

                for _, row in df.iterrows():
                    db.upsert_taxa(
                        competencia=row["competencia"],
                        ipca_pct=None
                        if pd.isna(row.get("ipca_pct"))
                        else float(row["ipca_pct"]),
                        taxa_legal_pct=None
                        if pd.isna(row.get("taxa_legal_pct"))
                        else float(row["taxa_legal_pct"]),
                        fonte=row["fonte"],
                        status=row["status"],
                    )

                st.success(f"{len(df)} competência(s) atualizada(s).")
                st.rerun()

            except Exception as e:
                st.error(f"Falha ao buscar no BCB: {e}")

    with st.expander("Cadastrar/alterar índice manualmente"):
        with st.form("form_taxa"):
            comp = st.text_input(
                "Competência (YYYY-MM)",
                value=f"{date.today().year:04d}-{date.today().month:02d}",
            )

            ipca = st.number_input(
                "IPCA mensal (%)",
                value=0.0,
                step=0.01,
                format="%.4f",
            )

            tl = st.number_input(
                "Taxa Legal mensal (%)",
                value=0.0,
                step=0.01,
                format="%.6f",
            )

            status = st.selectbox("Status", ["Oficial", "Provisória", "Parcial"])
            fonte = st.text_input("Fonte", value="Manual")

            submitted = st.form_submit_button("Salvar índice")

            if submitted:
                db.upsert_taxa(comp.strip(), ipca, tl, fonte, status)
                st.success("Índice salvo.")
                st.rerun()

    taxas = db.list_taxas()

    if taxas:
        taxa_rows = []

        for t in taxas:
            taxa_rows.append(
                {
                    "Competência": t.get("competencia") or "",
                    "IPCA (%)": ""
                    if t.get("ipca_pct") is None
                    else f"{float(t['ipca_pct']):.4f}".replace(".", ","),
                    "Taxa Legal (%)": ""
                    if t.get("taxa_legal_pct") is None
                    else f"{float(t['taxa_legal_pct']):.6f}".replace(".", ","),
                    "Fonte": t.get("fonte") or "",
                    "Status": t.get("status") or "",
                    "Atualizado em": t.get("updated_at") or "",
                }
            )

        taxa_event = st.dataframe(
            pd.DataFrame(taxa_rows),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="taxas_table",
        )

        idx = selected_row_index(taxa_event)

        if idx is not None:
            taxa = taxas[idx]
            st.markdown(f"#### Índice {taxa.get('competencia')}")

            with st.expander("Ações do índice"):
                confirmar_taxa = st.checkbox(
                    "Confirmo que desejo excluir este índice",
                    key="confirm_excluir_taxa",
                )

                if st.button("Excluir índice", disabled=not confirmar_taxa):
                    db.delete_taxa(int(taxa["id"]))
                    st.success("Índice excluído.")
                    st.rerun()
    else:
        st.info("Nenhum índice cadastrado ainda.")


with tabs[5]:
    st.subheader("Demonstrativos")

    devedor_id = select_devedor("Demonstrativo de", include_all=True, key="rel_devedor")

    resultado = calcular_carteira(
        db.list_dividas(devedor_id=None),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=devedor_id,
    )

    resumo = resultado["resumo"]

    st.write(
        f"Total atualizado em {data_base.isoformat()}: "
        f"**{money(resumo['total_atualizado'])}**"
    )

    st.write(
        f"Principal aberto: **{money(resumo['principal_aberto_estimado'])}** · "
        f"Encargos: **{money(resumo['encargos'])}** · "
        f"Recebimentos considerados: **{money(resumo['pagamentos_considerados'])}**"
    )

    excel_bytes = gerar_excel(resultado, db.list_taxas())

    st.download_button(
        "Baixar demonstrativo Excel",
        data=excel_bytes,
        file_name=f"demonstrativo_conta_certa_{data_base.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    try:
        pdf_bytes = gerar_pdf(resultado, titulo="Demonstrativo Conta Certa")

        st.download_button(
            "Baixar demonstrativo PDF",
            data=pdf_bytes,
            file_name=f"demonstrativo_conta_certa_{data_base.isoformat()}.pdf",
            mime="application/pdf",
        )

    except Exception as e:
        st.warning(f"Não foi possível gerar PDF: {e}")
