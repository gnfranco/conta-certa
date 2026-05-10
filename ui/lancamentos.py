from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

import database as db
from calculos import calcular_carteira
from ui.components import (
    render_danger_action,
    render_empty_state,
    render_section_header,
    render_subsection_header,
    render_table,
    selected_row_index,
    set_devedor_foco,
)
from ui.formatters import (
    competencia_from_date,
    devedor_label,
    format_date_br,
    format_money,
    public_ref,
    safe_text,
)


TIPOS_TITULO = [
    "Mensalidade",
    "Décimo terceiro",
    "Férias",
    "Empréstimo",
    "Reembolso",
    "Serviço",
    "Outros",
]


def unique_keep_order(values: list[str]) -> list[str]:
    seen = set()
    out = []

    for value in values:
        text = safe_text(value)

        if not text:
            continue

        key = text.lower()

        if key not in seen:
            seen.add(key)
            out.append(text)

    return out


def make_unique_labels(labels: list[str]) -> list[str]:
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


def option_index(options: list[str], value: str | None, default: int = 0) -> int:
    if value is None:
        return default

    try:
        return options.index(value)
    except ValueError:
        return default


def parse_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value

    if value:
        return date.fromisoformat(str(value)[:10])

    return date.today()


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


def calcular_resultado_global(data_base: date) -> dict[str, Any]:
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
    return calcular_carteira(
        db.list_dividas(devedor_id=None),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=devedor_id,
    )


def build_titulo_calc_map(resultado: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(t["id"]): t for t in resultado.get("titulos", resultado.get("dividas", []))
    }


def build_titulos_view(
    titulos: list[dict[str, Any]],
    resultado: dict[str, Any],
    data_base: date,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    calc_map = build_titulo_calc_map(resultado)
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    for titulo in titulos:
        titulo_id = int(titulo["id"])
        calc = calc_map.get(titulo_id)

        vencimento = parse_date(titulo.get("data_vencimento"))
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

        rows.append(
            {
                "Ref.": public_ref(titulo.get("public_ref")),
                "Lote": public_ref(titulo.get("lote_ref")),
                "Devedor": titulo.get("devedor") or "",
                "Grupo": titulo.get("grupo") or db.DEFAULT_GROUP_NAME,
                "Tipo": titulo.get("tipo") or "",
                "Competência": titulo.get("competencia") or "",
                "Descrição": titulo.get("descricao") or "",
                "Vencimento": format_date_br(titulo.get("data_vencimento")),
                "Original": format_money(titulo.get("valor_original")),
                "Recebido": format_money(total_recebido)
                if total_recebido is not None
                else "",
                "Principal": format_money(principal) if principal is not None else "",
                "Encargos": format_money(encargos) if encargos is not None else "",
                "Saldo": format_money(saldo) if saldo is not None else "",
                "Situação": situacao,
                "Status adm.": status_admin,
            }
        )
        records.append(titulo)

    return pd.DataFrame(rows), records


def build_recebimentos_view(
    recebimentos: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []

    for recebimento in recebimentos:
        if recebimento.get("divida_descricao"):
            destino = (
                f"{recebimento.get('divida_public_ref') or 'Título'} — "
                f"{recebimento.get('divida_descricao')}"
            )
            modo = "Título específico"
        elif recebimento.get("grupo"):
            destino = f"Grupo: {recebimento.get('grupo')}"
            modo = "Automático por grupo"
        else:
            destino = "Todos os grupos"
            modo = "Automático geral"

        rows.append(
            {
                "Ref.": public_ref(recebimento.get("public_ref")),
                "Data": format_date_br(recebimento.get("data_pagamento")),
                "Devedor": recebimento.get("devedor") or "",
                "Valor": format_money(recebimento.get("valor")),
                "Modo": modo,
                "Destino": destino,
                "Histórico": recebimento.get("descricao") or "",
                "Comprovante": recebimento.get("comprovante_ref") or "",
            }
        )

    return pd.DataFrame(rows), recebimentos


def filter_records_by_search(
    records: list[dict[str, Any]],
    text: str,
    fields: list[str],
) -> list[dict[str, Any]]:
    term = safe_text(text).lower()

    if not term:
        return records

    filtered: list[dict[str, Any]] = []

    for record in records:
        haystack = " ".join(
            str(record.get(field, "") or "") for field in fields
        ).lower()

        if term in haystack:
            filtered.append(record)

    return filtered


def devedor_options_from_records(records: list[dict[str, Any]]) -> list[str]:
    return ["Todos"] + sorted(
        {str(r.get("devedor") or "") for r in records if r.get("devedor")}
    )


def grupo_options_from_records(records: list[dict[str, Any]]) -> list[str]:
    return ["Todos"] + sorted(
        {str(r.get("grupo") or db.DEFAULT_GROUP_NAME) for r in records}
    )


def apply_titulos_filters(
    titulos: list[dict[str, Any]],
    *,
    devedor: str,
    grupo: str,
    status: str,
    busca: str,
) -> list[dict[str, Any]]:
    filtered = titulos

    if devedor != "Todos":
        filtered = [t for t in filtered if t.get("devedor") == devedor]

    if grupo != "Todos":
        filtered = [
            t for t in filtered if (t.get("grupo") or db.DEFAULT_GROUP_NAME) == grupo
        ]

    if status != "Todos":
        filtered = [t for t in filtered if (t.get("status") or "Aberta") == status]

    return filter_records_by_search(
        filtered,
        busca,
        [
            "public_ref",
            "lote_ref",
            "devedor",
            "grupo",
            "tipo",
            "competencia",
            "descricao",
            "status",
        ],
    )


def apply_recebimentos_filters(
    recebimentos: list[dict[str, Any]],
    *,
    devedor: str,
    busca: str,
) -> list[dict[str, Any]]:
    filtered = recebimentos

    if devedor != "Todos":
        filtered = [p for p in filtered if p.get("devedor") == devedor]

    return filter_records_by_search(
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


def max_data_movimentacao_devedor(devedor_id: int) -> date:
    datas = [date.today()]

    for p in db.list_pagamentos(devedor_id=devedor_id):
        if p.get("data_pagamento"):
            datas.append(parse_date(p["data_pagamento"]))

    for d in db.list_dividas(devedor_id=devedor_id, incluir_canceladas=True):
        if d.get("data_vencimento"):
            datas.append(parse_date(d["data_vencimento"]))

    return max(datas)


def titulo_tem_baixa_alocada(titulo_id: int) -> bool:
    if db.count_pagamentos_diretos_divida(titulo_id) > 0:
        return True

    titulo = db.get_divida(titulo_id)

    if not titulo:
        return False

    devedor_id = int(titulo["devedor_id"])
    data_limite = max_data_movimentacao_devedor(devedor_id)
    resultado = calcular_resultado_devedor(devedor_id, data_limite)

    for baixa in resultado.get("baixas", resultado.get("alocacoes", [])):
        if int(baixa.get("divida_id") or 0) != int(titulo_id):
            continue

        if float(baixa.get("valor_alocado") or 0) > 0:
            return True

    return False


def render_novo_titulo_form(default_devedor_id: int | None = None) -> None:
    devedores = db.list_devedores()

    if not devedores:
        render_empty_state(
            "Nenhum devedor cadastrado",
            "Use a opção '+ Novo devedor' no seletor lateral para cadastrar o primeiro devedor.",
        )
        return

    with st.form("lanc_form_novo_titulo"):
        labels_base = [devedor_label(d) for d in devedores]
        labels = make_unique_labels(labels_base)

        default_index = 0

        if default_devedor_id is not None:
            for i, d in enumerate(devedores):
                if int(d["id"]) == int(default_devedor_id):
                    default_index = i
                    break

        escolhido = st.selectbox(
            "Devedor",
            labels,
            index=default_index,
            key="lanc_novo_titulo_devedor",
        )
        devedor = devedores[labels.index(escolhido)]
        devedor_id = int(devedor["id"])

        grupo_options = group_options_for_devedor(
            devedor_id,
            include_suggestions=True,
        )

        c1, c2 = st.columns(2)

        with c1:
            grupo_escolhido = st.selectbox(
                "Grupo",
                grupo_options,
                index=option_index(grupo_options, db.DEFAULT_GROUP_NAME),
                key="lanc_novo_titulo_grupo",
            )

        with c2:
            novo_grupo = st.text_input(
                "Criar novo grupo, se necessário",
                placeholder="Ex.: Mensalidades 2026",
                key="lanc_novo_titulo_novo_grupo",
            )

        c3, c4 = st.columns(2)

        with c3:
            tipo = st.selectbox(
                "Tipo",
                TIPOS_TITULO,
                key="lanc_novo_titulo_tipo",
            )

        with c4:
            vencimento = st.date_input(
                "Data de vencimento",
                value=date.today(),
                key="lanc_novo_titulo_vencimento",
            )

        competencia = st.text_input(
            "Competência",
            value=competencia_from_date(vencimento),
            placeholder="Ex.: 2026-04, 2025, 2024-2025",
            key="lanc_novo_titulo_competencia",
        )

        descricao = st.text_input(
            "Descrição",
            key="lanc_novo_titulo_descricao",
        )

        c5, c6 = st.columns(2)

        with c5:
            valor = st.number_input(
                "Valor original",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                key="lanc_novo_titulo_valor",
            )

        with c6:
            observacoes = st.text_area(
                "Observações",
                key="lanc_novo_titulo_observacoes",
            )

        submitted = st.form_submit_button("Cadastrar título")

        if submitted:
            if valor <= 0:
                st.error("Informe valor maior que zero.")
                return

            if not descricao.strip():
                st.error("Informe descrição.")
                return

            nome_grupo = novo_grupo.strip() or grupo_escolhido
            grupo_id = db.get_or_create_grupo(devedor_id, nome_grupo)

            db.add_divida(
                devedor_id,
                descricao,
                tipo,
                valor,
                vencimento.isoformat(),
                observacoes,
                grupo_id=grupo_id,
                competencia=competencia,
            )

            set_devedor_foco(devedor_id)
            st.success("Título cadastrado.")
            st.rerun()


def render_novo_recebimento_form(default_devedor_id: int | None = None) -> None:
    devedores = db.list_devedores()

    if not devedores:
        render_empty_state(
            "Nenhum devedor cadastrado",
            "Use a opção '+ Novo devedor' no seletor lateral para cadastrar o primeiro devedor.",
        )
        return

    labels_base = [devedor_label(d) for d in devedores]
    labels = make_unique_labels(labels_base)

    default_index = 0

    if default_devedor_id is not None:
        for i, d in enumerate(devedores):
            if int(d["id"]) == int(default_devedor_id):
                default_index = i
                break

    escolhido = st.selectbox(
        "Devedor",
        labels,
        index=default_index,
        key="lanc_novo_recebimento_devedor",
    )
    devedor = devedores[labels.index(escolhido)]
    devedor_id = int(devedor["id"])

    modo = st.radio(
        "Como aplicar o recebimento?",
        ["Automático", "Automático por grupo", "Título específico"],
        horizontal=True,
        key="lanc_novo_recebimento_modo",
    )

    divida_id = None
    grupo_id = None

    if modo == "Automático":
        st.caption(
            "O recebimento será aplicado nos títulos vencidos mais antigos do devedor."
        )

    elif modo == "Automático por grupo":
        grupos = db.list_grupos(devedor_id)
        grupo_labels = [g["nome"] for g in grupos]

        if not grupo_labels:
            st.warning("Este devedor ainda não tem grupos.")
        else:
            grupo_escolhido = st.selectbox(
                "Grupo para aplicação automática",
                grupo_labels,
                key="lanc_novo_recebimento_grupo",
            )
            grupos_por_nome = {g["nome"]: int(g["id"]) for g in grupos}
            grupo_id = grupos_por_nome[grupo_escolhido]

        st.caption(
            "O recebimento será aplicado no título vencido mais antigo dentro do grupo selecionado."
        )

    else:
        titulos_devedor = db.list_dividas(devedor_id=devedor_id)

        if not titulos_devedor:
            st.warning("Este devedor ainda não tem títulos abertos.")
        else:
            titulo_labels = [
                (
                    f"{t.get('public_ref') or 'Título'} · "
                    f"{t.get('grupo') or db.DEFAULT_GROUP_NAME} · "
                    f"{t.get('descricao') or ''} · "
                    f"venc. {format_date_br(t.get('data_vencimento'))} · "
                    f"{format_money(t.get('valor_original'))}"
                )
                for t in titulos_devedor
            ]

            titulo_escolhido = st.selectbox(
                "Título que o recebimento deve baixar",
                titulo_labels,
                key="lanc_novo_recebimento_titulo",
            )
            divida_id = titulos_devedor[titulo_labels.index(titulo_escolhido)]["id"]

        st.caption("O recebimento será aplicado exatamente no título selecionado.")

    st.divider()

    with st.form("lanc_form_novo_recebimento"):
        c1, c2 = st.columns(2)

        with c1:
            data_pagamento = st.date_input(
                "Data do recebimento",
                value=date.today(),
                key="lanc_novo_recebimento_data",
            )

        with c2:
            valor = st.number_input(
                "Valor recebido",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                key="lanc_novo_recebimento_valor",
            )

        descricao = st.text_input(
            "Histórico",
            value="PIX recebido",
            key="lanc_novo_recebimento_descricao",
        )

        comprovante = st.text_input(
            "Referência do comprovante/arquivo",
            key="lanc_novo_recebimento_comprovante",
        )

        submitted = st.form_submit_button("Registrar recebimento")

        if submitted:
            if valor <= 0:
                st.error("Informe valor maior que zero.")
                return

            if modo == "Título específico" and not divida_id:
                st.error("Escolha um título específico.")
                return

            if modo == "Automático por grupo" and not grupo_id:
                st.error("Escolha um grupo.")
                return

            db.add_pagamento(
                devedor_id,
                divida_id,
                data_pagamento.isoformat(),
                valor,
                descricao,
                comprovante,
                grupo_id=grupo_id,
            )

            set_devedor_foco(devedor_id)
            st.success("Recebimento registrado.")
            st.rerun()


def render_titulo_editor(titulo: dict[str, Any]) -> None:
    titulo_id = int(titulo["id"])
    tem_baixa = titulo_tem_baixa_alocada(titulo_id)

    render_subsection_header(
        f"Título {titulo.get('public_ref') or ''}",
        f"{titulo.get('devedor') or ''} · "
        f"{titulo.get('grupo') or db.DEFAULT_GROUP_NAME} · "
        f"{titulo.get('descricao') or ''}",
    )

    if tem_baixa:
        st.warning(
            "Este título já recebeu baixa/recebimento. "
            "Valor original e vencimento ficam bloqueados; apenas metadados podem ser alterados."
        )
    else:
        st.info(
            "Este título ainda não recebeu baixa/recebimento. "
            "Valor original e vencimento podem ser alterados."
        )

    grupos_edit = group_options_for_devedor(int(titulo["devedor_id"]))
    grupo_atual = titulo.get("grupo") or db.DEFAULT_GROUP_NAME

    if grupo_atual not in grupos_edit:
        grupos_edit.append(grupo_atual)

    tipos = list(TIPOS_TITULO)
    tipo_atual = titulo.get("tipo") or "Outros"

    if tipo_atual not in tipos:
        tipos.append(tipo_atual)

    status_options = list(db.ADMIN_STATUSES)
    status_atual = titulo.get("status") or "Aberta"

    if status_atual not in status_options:
        status_options.append(status_atual)

    with st.form(f"lanc_form_editar_titulo_{titulo_id}"):
        c1, c2 = st.columns(2)

        with c1:
            grupo_edit = st.selectbox(
                "Grupo",
                grupos_edit,
                index=option_index(grupos_edit, grupo_atual),
                key=f"lanc_editar_titulo_grupo_{titulo_id}",
            )

        with c2:
            novo_grupo = st.text_input(
                "Criar novo grupo, se necessário",
                placeholder="Ex.: Acordo antigo",
                key=f"lanc_editar_titulo_novo_grupo_{titulo_id}",
            )

        c3, c4 = st.columns(2)

        with c3:
            tipo_edit = st.selectbox(
                "Tipo",
                tipos,
                index=option_index(tipos, tipo_atual),
                key=f"lanc_editar_titulo_tipo_{titulo_id}",
            )

        with c4:
            competencia_edit = st.text_input(
                "Competência",
                value=titulo.get("competencia") or "",
                key=f"lanc_editar_titulo_competencia_{titulo_id}",
            )

        descricao_edit = st.text_input(
            "Descrição",
            value=titulo.get("descricao") or "",
            key=f"lanc_editar_titulo_descricao_{titulo_id}",
        )

        c5, c6, c7 = st.columns(3)

        with c5:
            valor_edit = st.number_input(
                "Valor original",
                min_value=0.0,
                value=float(titulo["valor_original"]),
                step=100.0,
                format="%.2f",
                disabled=tem_baixa,
                key=f"lanc_editar_titulo_valor_{titulo_id}",
            )

        with c6:
            vencimento_edit = st.date_input(
                "Data de vencimento",
                value=parse_date(titulo["data_vencimento"]),
                disabled=tem_baixa,
                key=f"lanc_editar_titulo_vencimento_{titulo_id}",
            )

        with c7:
            status_edit = st.selectbox(
                "Status administrativo",
                status_options,
                index=option_index(status_options, status_atual),
                key=f"lanc_editar_titulo_status_{titulo_id}",
            )

        observacoes_edit = st.text_area(
            "Observações",
            value=titulo.get("observacoes") or "",
            key=f"lanc_editar_titulo_observacoes_{titulo_id}",
        )

        submitted = st.form_submit_button("Salvar alterações")

        if submitted:
            if not descricao_edit.strip():
                st.error("Informe descrição.")
                return

            try:
                nome_grupo = novo_grupo.strip() or grupo_edit
                grupo_id = db.get_or_create_grupo(
                    int(titulo["devedor_id"]),
                    nome_grupo,
                )

                db.update_divida(
                    titulo_id,
                    grupo_id=grupo_id,
                    descricao=descricao_edit,
                    tipo=tipo_edit,
                    competencia=competencia_edit,
                    observacoes=observacoes_edit,
                    status=status_edit,
                    valor_original=valor_edit,
                    data_vencimento=vencimento_edit.isoformat(),
                    permitir_alterar_valor_vencimento=not tem_baixa,
                )

                st.success("Título atualizado.")
                st.rerun()

            except Exception as e:
                st.error(f"Não foi possível atualizar o título: {e}")

    with st.expander("Ações administrativas do título"):
        if status_atual == "Cancelada":
            st.info("Este título já está cancelado.")
        else:
            if render_danger_action(
                label="Cancelar título",
                confirmation_label="Confirmo que desejo cancelar este título",
                key_prefix=f"lanc_cancelar_titulo_{titulo_id}",
            ):
                try:
                    db.delete_divida(titulo_id)
                    st.success("Título cancelado.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Não foi possível cancelar o título: {e}")


def render_recebimento_editor(recebimento: dict[str, Any]) -> None:
    recebimento_id = int(recebimento["id"])
    devedor_id = int(recebimento["devedor_id"])

    render_subsection_header(
        f"Recebimento {recebimento.get('public_ref') or ''}",
        "Alterar um recebimento recalcula baixas e saldos.",
    )

    modo_atual = "Título específico" if recebimento.get("divida_id") else "Automático"

    with st.form(f"lanc_form_editar_recebimento_{recebimento_id}"):
        modo_edit = st.radio(
            "Modo de alocação",
            ["Automático", "Automático por grupo", "Título específico"],
            index=2
            if modo_atual == "Título específico"
            else 1
            if recebimento.get("grupo_id")
            else 0,
            horizontal=True,
            key=f"lanc_editar_recebimento_modo_{recebimento_id}",
        )

        divida_id_edit = None
        grupo_id_edit = None

        if modo_edit == "Automático":
            st.caption("Aplicar nos títulos vencidos mais antigos do devedor.")

        elif modo_edit == "Automático por grupo":
            grupos = db.list_grupos(devedor_id)
            grupo_labels = [g["nome"] for g in grupos]

            grupo_atual = recebimento.get("grupo") or (
                grupo_labels[0] if grupo_labels else ""
            )

            if grupo_labels:
                grupo_edit = st.selectbox(
                    "Grupo para alocação automática",
                    grupo_labels,
                    index=option_index(grupo_labels, grupo_atual),
                    key=f"lanc_editar_recebimento_grupo_{recebimento_id}",
                )
                grupos_por_nome = {g["nome"]: int(g["id"]) for g in grupos}
                grupo_id_edit = grupos_por_nome[grupo_edit]
            else:
                st.warning("Este devedor ainda não tem grupos.")

        else:
            titulos_devedor = db.list_dividas(devedor_id=devedor_id)

            if not titulos_devedor:
                st.warning("Este devedor não tem títulos abertos.")
            else:
                titulo_labels = [
                    (
                        f"{t.get('public_ref') or 'Título'} · "
                        f"{t.get('grupo') or db.DEFAULT_GROUP_NAME} · "
                        f"{t.get('descricao') or ''} · "
                        f"venc. {format_date_br(t.get('data_vencimento'))} · "
                        f"{format_money(t.get('valor_original'))}"
                    )
                    for t in titulos_devedor
                ]

                titulo_ids = [int(t["id"]) for t in titulos_devedor]
                titulo_atual_id = (
                    int(recebimento["divida_id"])
                    if recebimento.get("divida_id")
                    else None
                )

                idx_titulo = (
                    titulo_ids.index(titulo_atual_id)
                    if titulo_atual_id in titulo_ids
                    else 0
                )

                titulo_edit = st.selectbox(
                    "Título que o recebimento deve baixar",
                    titulo_labels,
                    index=idx_titulo,
                    key=f"lanc_editar_recebimento_titulo_{recebimento_id}",
                )
                divida_id_edit = titulos_devedor[titulo_labels.index(titulo_edit)]["id"]

        c1, c2 = st.columns(2)

        with c1:
            data_pagamento_edit = st.date_input(
                "Data do recebimento",
                value=parse_date(recebimento["data_pagamento"]),
                key=f"lanc_editar_recebimento_data_{recebimento_id}",
            )

        with c2:
            valor_edit = st.number_input(
                "Valor recebido",
                min_value=0.0,
                value=float(recebimento["valor"]),
                step=100.0,
                format="%.2f",
                key=f"lanc_editar_recebimento_valor_{recebimento_id}",
            )

        descricao_edit = st.text_input(
            "Histórico",
            value=recebimento.get("descricao") or "",
            key=f"lanc_editar_recebimento_descricao_{recebimento_id}",
        )

        comprovante_edit = st.text_input(
            "Referência do comprovante/arquivo",
            value=recebimento.get("comprovante_ref") or "",
            key=f"lanc_editar_recebimento_comprovante_{recebimento_id}",
        )

        submitted = st.form_submit_button("Salvar alterações")

        if submitted:
            if valor_edit <= 0:
                st.error("Informe valor maior que zero.")
                return

            if modo_edit == "Título específico" and not divida_id_edit:
                st.error("Escolha um título específico.")
                return

            if modo_edit == "Automático por grupo" and not grupo_id_edit:
                st.error("Escolha um grupo.")
                return

            try:
                db.update_pagamento(
                    recebimento_id,
                    devedor_id=devedor_id,
                    divida_id=divida_id_edit,
                    grupo_id=grupo_id_edit,
                    data_pagamento=data_pagamento_edit.isoformat(),
                    valor=valor_edit,
                    descricao=descricao_edit,
                    comprovante_ref=comprovante_edit,
                )

                st.success("Recebimento atualizado.")
                st.rerun()

            except Exception as e:
                st.error(f"Não foi possível atualizar o recebimento: {e}")

    with st.expander("Ações do recebimento"):
        if render_danger_action(
            label="Excluir recebimento",
            confirmation_label="Confirmo que desejo excluir este recebimento",
            key_prefix=f"lanc_excluir_recebimento_{recebimento_id}",
        ):
            try:
                db.delete_pagamento(recebimento_id)
                st.success("Recebimento excluído.")
                st.rerun()
            except Exception as e:
                st.error(f"Não foi possível excluir o recebimento: {e}")


def render_titulos_section(data_base: date) -> None:
    render_section_header(
        "Carteira de títulos",
        "Consulte, filtre e selecione um título para editar.",
    )

    titulos = db.list_dividas(incluir_canceladas=True)

    if not titulos:
        st.info("Nenhum título cadastrado.")
        return

    resultado = calcular_resultado_global(data_base)

    c1, c2, c3, c4 = st.columns([1.3, 1.2, 1.1, 2.0])

    with c1:
        filtro_devedor = st.selectbox(
            "Devedor",
            devedor_options_from_records(titulos),
            key="lanc_titulos_filtro_devedor",
        )

    with c2:
        filtro_grupo = st.selectbox(
            "Grupo",
            grupo_options_from_records(titulos),
            key="lanc_titulos_filtro_grupo",
        )

    with c3:
        filtro_status = st.selectbox(
            "Status adm.",
            ["Todos"] + list(db.ADMIN_STATUSES),
            key="lanc_titulos_filtro_status",
        )

    with c4:
        busca = st.text_input(
            "Buscar",
            placeholder="Ref., lote, descrição, grupo, competência...",
            key="lanc_titulos_busca",
        )

    filtered = apply_titulos_filters(
        titulos,
        devedor=filtro_devedor,
        grupo=filtro_grupo,
        status=filtro_status,
        busca=busca,
    )

    df_view, records = build_titulos_view(filtered, resultado, data_base)

    event = render_table(
        df_view,
        key="lanc_titulos_table",
        selectable=True,
        empty_message="Nenhum título encontrado com os filtros atuais.",
    )

    idx = selected_row_index(event)

    if idx is not None:
        render_titulo_editor(records[idx])
    elif not df_view.empty:
        st.caption("Selecione uma linha para ver detalhes e editar.")


def render_recebimentos_section() -> None:
    render_section_header(
        "Recebimentos",
        "Consulte, filtre e selecione um recebimento para editar.",
    )

    recebimentos = db.list_pagamentos()

    if not recebimentos:
        st.info("Nenhum recebimento registrado.")
        return

    c1, c2 = st.columns([1.2, 2.0])

    with c1:
        filtro_devedor = st.selectbox(
            "Devedor",
            devedor_options_from_records(recebimentos),
            key="lanc_recebimentos_filtro_devedor",
        )

    with c2:
        busca = st.text_input(
            "Buscar",
            placeholder="Ref., histórico, comprovante, destino...",
            key="lanc_recebimentos_busca",
        )

    filtered = apply_recebimentos_filters(
        recebimentos,
        devedor=filtro_devedor,
        busca=busca,
    )

    df_view, records = build_recebimentos_view(filtered)

    event = render_table(
        df_view,
        key="lanc_recebimentos_table",
        selectable=True,
        empty_message="Nenhum recebimento encontrado com os filtros atuais.",
    )

    idx = selected_row_index(event)

    if idx is not None:
        render_recebimento_editor(records[idx])
    elif not df_view.empty:
        st.caption("Selecione uma linha para ver detalhes e editar.")


def render_lancamentos(data_base: date) -> None:
    """
    Renderiza a página de lançamentos.

    Esta página agora concentra lançamentos financeiros:
    - cadastrar título;
    - registrar recebimento;
    - consultar/editar títulos;
    - consultar/editar recebimentos.

    O cadastro de devedor fica no seletor lateral de 'Devedor em foco'.
    """
    st.subheader("Lançamentos")

    st.caption(
        "Cadastre títulos e recebimentos. Para criar um novo devedor, use "
        "a opção '+ Novo devedor' no seletor lateral de Devedor em foco."
    )

    default_devedor_id = st.session_state.get("devedor_foco_id")

    tab_titulo, tab_recebimento = st.tabs(["Novo título", "Novo recebimento"])

    with tab_titulo:
        render_novo_titulo_form(default_devedor_id=default_devedor_id)

    with tab_recebimento:
        render_novo_recebimento_form(default_devedor_id=default_devedor_id)

    st.divider()

    render_titulos_section(data_base)

    st.divider()

    render_recebimentos_section()
