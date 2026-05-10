from __future__ import annotations

from datetime import date
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
    render_danger_action,
    render_devedor_identity,
    render_download_buttons,
    render_empty_state,
    render_quick_actions,
    render_resumo_financeiro,
    render_section_header,
    render_subsection_header,
    render_table,
    selected_row_index,
    set_devedor_foco,
)
from ui.formatters import (
    clean_filename,
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


def option_index(options: list[str], value: str | None, default: int = 0) -> int:
    if value is None:
        return default

    try:
        return options.index(value)
    except ValueError:
        return default


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


def max_data_movimentacao_devedor(devedor_id: int) -> date:
    datas = [date.today()]

    for p in db.list_pagamentos(devedor_id=devedor_id):
        if p.get("data_pagamento"):
            datas.append(date.fromisoformat(str(p["data_pagamento"])[:10]))

    for d in db.list_dividas(devedor_id=devedor_id, incluir_canceladas=True):
        if d.get("data_vencimento"):
            datas.append(date.fromisoformat(str(d["data_vencimento"])[:10]))

    return max(datas)


def titulo_tem_baixa_alocada(titulo_id: int) -> bool:
    """
    Verifica se um título já recebeu baixa/recebimento.

    Enquanto as baixas ainda podem ser recalculadas dinamicamente, usamos:
    - recebimentos diretos no título;
    - cálculo da carteira até a última movimentação do devedor.
    """
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

        vencimento = date.fromisoformat(str(titulo["data_vencimento"])[:10])
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
                "Ref.": public_ref(p.get("public_ref")),
                "Data": format_date_br(p.get("data_pagamento")),
                "Valor": format_money(p.get("valor")),
                "Modo": modo,
                "Destino": destino,
                "Histórico": p.get("descricao") or "",
                "Comprovante": p.get("comprovante_ref") or "",
            }
        )

    return pd.DataFrame(rows), recebimentos


def build_baixas_view(baixas: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for b in baixas:
        rows.append(
            {
                "Recebimento": b.get("pagamento_ref") or "",
                "Data": format_date_br(b.get("data_pagamento")),
                "Grupo": b.get("grupo") or "",
                "Título": b.get("titulo_ref") or b.get("divida_ref") or "",
                "Lote": b.get("lote_ref") or "",
                "Histórico": b.get("titulo") or b.get("divida") or "",
                "Tipo": b.get("tipo_alocacao") or "Baixa",
                "Valor": format_money(b.get("valor_alocado")),
            }
        )

    return pd.DataFrame(rows)


def timeline_devedor(
    devedor_id: int,
    data_base: date,
    resultado: dict[str, Any],
) -> pd.DataFrame:
    eventos: list[dict[str, Any]] = []

    titulos = db.list_dividas(devedor_id=devedor_id, incluir_canceladas=True)
    recebimentos = db.list_pagamentos(devedor_id=devedor_id)
    calc_map = build_titulo_calc_map(resultado)

    for titulo in titulos:
        titulo_id = int(titulo["id"])
        calc = calc_map.get(titulo_id)

        saldo = ""
        situacao = titulo.get("status") or "Aberta"

        if calc:
            saldo = format_money(calc.get("saldo_atualizado"))
            situacao = calc.get("situacao_financeira") or situacao
        elif date.fromisoformat(str(titulo["data_vencimento"])[:10]) > data_base:
            saldo = format_money(titulo.get("valor_original"))
            situacao = "A vencer"

        eventos.append(
            {
                "_data": date.fromisoformat(str(titulo["data_vencimento"])[:10]),
                "_ordem": 10,
                "Data": format_date_br(titulo.get("data_vencimento")),
                "Evento": "Título",
                "Ref.": titulo.get("public_ref") or "",
                "Histórico": titulo.get("descricao") or "",
                "Grupo": titulo.get("grupo") or db.DEFAULT_GROUP_NAME,
                "Débito": format_money(titulo.get("valor_original")),
                "Crédito": "",
                "Saldo": saldo,
                "Situação": situacao,
            }
        )

    for recebimento in recebimentos:
        eventos.append(
            {
                "_data": date.fromisoformat(str(recebimento["data_pagamento"])[:10]),
                "_ordem": 20,
                "Data": format_date_br(recebimento.get("data_pagamento")),
                "Evento": "Recebimento",
                "Ref.": recebimento.get("public_ref") or "",
                "Histórico": recebimento.get("descricao") or "Recebimento",
                "Grupo": recebimento.get("grupo") or "",
                "Débito": "",
                "Crédito": format_money(recebimento.get("valor")),
                "Saldo": "",
                "Situação": "Registrado",
            }
        )

    for baixa in resultado.get("baixas", resultado.get("alocacoes", [])):
        valor = float(baixa.get("valor_alocado") or 0)

        if valor == 0:
            continue

        eventos.append(
            {
                "_data": date.fromisoformat(str(baixa["data_pagamento"])[:10]),
                "_ordem": 30,
                "Data": format_date_br(baixa.get("data_pagamento")),
                "Evento": baixa.get("tipo_alocacao") or "Baixa",
                "Ref.": baixa.get("pagamento_ref") or "",
                "Histórico": (
                    f"{baixa.get('titulo_ref') or baixa.get('divida_ref') or ''} · "
                    f"{baixa.get('titulo') or baixa.get('divida') or ''}"
                ).strip(" ·"),
                "Grupo": baixa.get("grupo") or "",
                "Débito": "",
                "Crédito": format_money(abs(valor)),
                "Saldo": "",
                "Situação": "Aplicado" if valor > 0 else "Excedente",
            }
        )

    eventos.sort(key=lambda e: (e["_data"], e["_ordem"]))

    public_rows = []

    for evento in eventos:
        public_rows.append(
            {k: v for k, v in evento.items() if not str(k).startswith("_")}
        )

    return pd.DataFrame(public_rows)


def render_novo_titulo_form(default_devedor_id: int | None = None) -> None:
    devedores = db.list_devedores()

    if not devedores:
        render_empty_state(
            "Nenhum devedor cadastrado",
            "Cadastre um devedor antes de lançar títulos.",
        )
        return

    with st.form("workspace_form_novo_titulo"):
        labels_base = [devedor_label(d) for d in devedores]
        labels = make_unique_labels(labels_base)

        default_index = 0

        if default_devedor_id is not None:
            for i, d in enumerate(devedores):
                if int(d["id"]) == int(default_devedor_id):
                    default_index = i
                    break

        escolhido = st.selectbox("Devedor", labels, index=default_index)
        devedor = devedores[labels.index(escolhido)]

        grupo_options = group_options_for_devedor(
            int(devedor["id"]),
            include_suggestions=True,
        )

        c1, c2 = st.columns(2)

        with c1:
            grupo_escolhido = st.selectbox(
                "Grupo",
                grupo_options,
                index=option_index(grupo_options, db.DEFAULT_GROUP_NAME),
            )

        with c2:
            novo_grupo = st.text_input(
                "Criar novo grupo, se necessário",
                placeholder="Ex.: Mensalidades 2026",
            )

        c3, c4 = st.columns(2)

        with c3:
            tipo = st.selectbox("Tipo", TIPOS_TITULO)

        with c4:
            vencimento = st.date_input("Data de vencimento", value=date.today())

        competencia_titulo = st.text_input(
            "Competência",
            value=competencia_from_date(vencimento),
            placeholder="Ex.: 2026-04, 2025, 2024-2025",
        )

        descricao = st.text_input("Descrição")
        valor = st.number_input(
            "Valor original",
            min_value=0.0,
            step=100.0,
            format="%.2f",
        )
        observacoes = st.text_area("Observações")

        submitted = st.form_submit_button("Cadastrar título")

        if submitted:
            if valor <= 0:
                st.error("Informe valor maior que zero.")
                return

            if not descricao.strip():
                st.error("Informe descrição.")
                return

            nome_grupo = novo_grupo.strip() or grupo_escolhido
            grupo_id = db.get_or_create_grupo(int(devedor["id"]), nome_grupo)

            db.add_divida(
                int(devedor["id"]),
                descricao,
                tipo,
                valor,
                vencimento.isoformat(),
                observacoes,
                grupo_id=grupo_id,
                competencia=competencia_titulo,
            )

            set_devedor_foco(int(devedor["id"]))
            st.success("Título cadastrado.")
            st.rerun()


def render_novo_recebimento_form(default_devedor_id: int | None = None) -> None:
    devedores = db.list_devedores()

    if not devedores:
        render_empty_state(
            "Nenhum devedor cadastrado",
            "Cadastre um devedor antes de registrar recebimentos.",
        )
        return

    with st.form("workspace_form_novo_recebimento"):
        labels_base = [devedor_label(d) for d in devedores]
        labels = make_unique_labels(labels_base)

        default_index = 0

        if default_devedor_id is not None:
            for i, d in enumerate(devedores):
                if int(d["id"]) == int(default_devedor_id):
                    default_index = i
                    break

        escolhido = st.selectbox("Devedor", labels, index=default_index)
        devedor = devedores[labels.index(escolhido)]
        devedor_id = int(devedor["id"])

        modo = st.radio(
            "Como aplicar o recebimento?",
            ["Automático", "Automático por grupo", "Título específico"],
            horizontal=True,
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
                )
                grupos_por_nome = {g["nome"]: int(g["id"]) for g in grupos}
                grupo_id = grupos_por_nome[grupo_escolhido]

            st.caption(
                "O recebimento será aplicado no título vencido mais antigo dentro do grupo."
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
                )
                divida_id = titulos_devedor[titulo_labels.index(titulo_escolhido)]["id"]

            st.caption("O recebimento será aplicado exatamente no título selecionado.")

        c1, c2 = st.columns(2)

        with c1:
            data_pagamento = st.date_input("Data do recebimento", value=date.today())

        with c2:
            valor = st.number_input(
                "Valor recebido",
                min_value=0.0,
                step=100.0,
                format="%.2f",
            )

        descricao = st.text_input("Histórico", value="PIX recebido")
        comprovante = st.text_input("Referência do comprovante/arquivo")
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

    with st.form(f"workspace_form_editar_titulo_{titulo_id}"):
        c1, c2 = st.columns(2)

        with c1:
            grupo_edit = st.selectbox(
                "Grupo",
                grupos_edit,
                index=option_index(grupos_edit, grupo_atual),
            )

        with c2:
            novo_grupo = st.text_input(
                "Criar novo grupo, se necessário",
                placeholder="Ex.: Acordo antigo",
            )

        c3, c4 = st.columns(2)

        with c3:
            tipo_edit = st.selectbox(
                "Tipo",
                tipos,
                index=option_index(tipos, tipo_atual),
            )

        with c4:
            competencia_edit = st.text_input(
                "Competência",
                value=titulo.get("competencia") or "",
            )

        descricao_edit = st.text_input(
            "Descrição",
            value=titulo.get("descricao") or "",
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
            )

        with c6:
            vencimento_edit = st.date_input(
                "Data de vencimento",
                value=date.fromisoformat(str(titulo["data_vencimento"])[:10]),
                disabled=tem_baixa,
            )

        with c7:
            status_edit = st.selectbox(
                "Status administrativo",
                status_options,
                index=option_index(status_options, status_atual),
            )

        observacoes_edit = st.text_area(
            "Observações",
            value=titulo.get("observacoes") or "",
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
                key_prefix=f"workspace_cancelar_titulo_{titulo_id}",
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

    with st.form(f"workspace_form_editar_recebimento_{recebimento_id}"):
        modo_edit = st.radio(
            "Modo de alocação",
            ["Automático", "Automático por grupo", "Título específico"],
            index=2
            if modo_atual == "Título específico"
            else 1
            if recebimento.get("grupo_id")
            else 0,
            horizontal=True,
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
                )
                divida_id_edit = titulos_devedor[titulo_labels.index(titulo_edit)]["id"]

        c1, c2 = st.columns(2)

        with c1:
            data_pagamento_edit = st.date_input(
                "Data do recebimento",
                value=date.fromisoformat(str(recebimento["data_pagamento"])[:10]),
            )

        with c2:
            valor_edit = st.number_input(
                "Valor recebido",
                min_value=0.0,
                value=float(recebimento["valor"]),
                step=100.0,
                format="%.2f",
            )

        descricao_edit = st.text_input(
            "Histórico",
            value=recebimento.get("descricao") or "",
        )
        comprovante_edit = st.text_input(
            "Referência do comprovante/arquivo",
            value=recebimento.get("comprovante_ref") or "",
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
            key_prefix=f"workspace_excluir_recebimento_{recebimento_id}",
        ):
            try:
                db.delete_pagamento(recebimento_id)
                st.success("Recebimento excluído.")
                st.rerun()
            except Exception as e:
                st.error(f"Não foi possível excluir o recebimento: {e}")


def render_demonstrativo_devedor(
    devedor: dict[str, Any],
    resultado: dict[str, Any],
    data_base: date,
) -> None:
    resumo = resultado["resumo"]

    st.write(
        f"Total atualizado em {data_base.isoformat()}: "
        f"**{format_money(resumo.get('total_atualizado'))}**"
    )

    excel_bytes = gerar_excel(resultado, db.list_taxas())

    pdf_bytes = None

    try:
        pdf_bytes = gerar_pdf(
            resultado,
            titulo=f"Demonstrativo Conta Certa — {devedor['nome']}",
        )
    except Exception as e:
        st.warning(f"Não foi possível gerar PDF: {e}")

    base_name = clean_filename(
        f"demonstrativo_{devedor['nome']}_{data_base.isoformat()}"
    )

    render_download_buttons(
        excel_bytes=excel_bytes,
        pdf_bytes=pdf_bytes,
        excel_filename=f"{base_name}.xlsx",
        pdf_filename=f"{base_name}.pdf",
    )


def render_workspace_devedor(data_base: date) -> None:
    """
    Renderiza a aba principal orientada ao devedor.

    A ideia da UX é concentrar o uso diário aqui:
    - resumo financeiro;
    - ações rápidas;
    - linha do tempo;
    - títulos;
    - recebimentos;
    - baixas;
    - demonstrativo.
    """
    st.subheader("Workspace do devedor")

    devedor_id = get_devedor_foco_id()
    devedor = get_devedor_by_id(devedor_id)

    if not devedor:
        render_empty_state(
            "Nenhum devedor selecionado",
            "Cadastre ou selecione um devedor para abrir o workspace.",
        )
        return

    devedor_id = int(devedor["id"])
    resultado = calcular_resultado_devedor(devedor_id, data_base)
    resumo = resultado["resumo"]

    render_devedor_identity(devedor)
    render_resumo_financeiro(resumo)
    render_alertas_indices(resumo)

    st.divider()

    render_section_header(
        "Ações rápidas",
        "Use estes atalhos para lançar, receber ou emitir demonstrativos para o devedor em foco.",
    )

    action = render_quick_actions(key_prefix=f"workspace_actions_{devedor_id}")

    if action == "novo_titulo":
        st.session_state["workspace_action"] = "novo_titulo"
    elif action == "novo_recebimento":
        st.session_state["workspace_action"] = "novo_recebimento"
    elif action == "demonstrativo":
        st.session_state["workspace_action"] = "demonstrativo"
    elif action == "linha_tempo":
        st.session_state["workspace_action"] = "linha_tempo"

    workspace_action = st.session_state.get("workspace_action", "linha_tempo")

    if workspace_action == "novo_titulo":
        render_section_header("Novo título")
        render_novo_titulo_form(default_devedor_id=devedor_id)

    elif workspace_action == "novo_recebimento":
        render_section_header("Novo recebimento")
        render_novo_recebimento_form(default_devedor_id=devedor_id)

    elif workspace_action == "demonstrativo":
        render_section_header("Demonstrativo")
        render_demonstrativo_devedor(devedor, resultado, data_base)

    st.divider()

    render_section_header(
        "Linha do tempo",
        "Eventos financeiros do devedor em ordem cronológica.",
    )

    timeline_df = timeline_devedor(devedor_id, data_base, resultado)

    if not timeline_df.empty:
        render_table(
            timeline_df,
            key=f"workspace_timeline_{devedor_id}",
            selectable=False,
            empty_message="Nenhum evento na linha do tempo.",
        )
    else:
        st.info("Nenhum evento registrado para este devedor.")

    st.divider()

    render_section_header("Detalhes do devedor")

    tab_titulos, tab_recebimentos, tab_baixas = st.tabs(
        ["Títulos", "Recebimentos", "Baixas"]
    )

    with tab_titulos:
        titulos = db.list_dividas(
            devedor_id=devedor_id,
            incluir_canceladas=True,
        )

        df_titulos, titulos_records = build_titulos_view(
            titulos,
            resultado,
            data_base,
        )

        event = render_table(
            df_titulos,
            key=f"workspace_titulos_{devedor_id}",
            selectable=True,
            empty_message="Nenhum título cadastrado para este devedor.",
        )

        idx = selected_row_index(event)

        if idx is not None:
            render_titulo_editor(titulos_records[idx])
        elif not df_titulos.empty:
            st.caption("Selecione um título para ver detalhes e editar.")

    with tab_recebimentos:
        recebimentos = db.list_pagamentos(devedor_id=devedor_id)

        df_recebimentos, recebimentos_records = build_recebimentos_view(recebimentos)

        event = render_table(
            df_recebimentos,
            key=f"workspace_recebimentos_{devedor_id}",
            selectable=True,
            empty_message="Nenhum recebimento registrado para este devedor.",
        )

        idx = selected_row_index(event)

        if idx is not None:
            render_recebimento_editor(recebimentos_records[idx])
        elif not df_recebimentos.empty:
            st.caption("Selecione um recebimento para ver detalhes e editar.")

    with tab_baixas:
        df_baixas = build_baixas_view(
            resultado.get("baixas", resultado.get("alocacoes", []))
        )

        render_table(
            df_baixas,
            key=f"workspace_baixas_{devedor_id}",
            selectable=False,
            empty_message="Nenhuma baixa registrada para este devedor.",
        )
