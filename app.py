from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import streamlit as st

import bcb
import database as db
from calculos import calcular_carteira, money
from reports import gerar_excel, gerar_pdf

st.set_page_config(
    page_title="Cobrança IPCA + Taxa Legal",
    page_icon="💸",
    layout="wide",
)

db.init_db()


def df_or_empty(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def select_devedor(label: str, include_all: bool = False):
    devedores = db.list_devedores()
    if include_all:
        options = [{"id": None, "nome": "Todos"}] + devedores
    else:
        options = devedores

    if not options:
        st.warning("Cadastre pelo menos um devedor primeiro.")
        return None

    labels = [f'{d["nome"]} #{d["id"]}' if d["id"] else d["nome"] for d in options]
    chosen = st.selectbox(label, labels)
    return options[labels.index(chosen)]["id"]


st.title("Cobrança IPCA + Taxa Legal")
st.caption("Controle local de dívidas, pagamentos parciais e atualização monetária por IPCA + Taxa Legal.")

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
        value=float(settings.get("ipca_provisorio_pct", "0.50").replace(",", ".")),
        step=0.01,
        format="%.4f",
    )
    tl_prov = st.number_input(
        "Taxa Legal provisória mensal (%)",
        value=float(settings.get("taxa_legal_provisoria_pct", "0.20").replace(",", ".")),
        step=0.01,
        format="%.4f",
    )

    if st.button("Salvar configurações"):
        db.set_setting("usar_provisorio", usar_prov)
        db.set_setting("ipca_provisorio_pct", str(ipca_prov))
        db.set_setting("taxa_legal_provisoria_pct", str(tl_prov))
        st.success("Configurações salvas.")
        st.rerun()

tabs = st.tabs(["Dashboard", "Devedores", "Dívidas", "Pagamentos", "Taxas", "Relatórios"])


with tabs[0]:
    st.subheader("Dashboard")
    devedor_id = select_devedor("Ver devedor", include_all=True)

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
    c1.metric("Principal aberto estimado", money(resumo["principal_aberto_estimado"]))
    c2.metric("Encargos IPCA + Taxa Legal", money(resumo["encargos"]))
    c3.metric("Total atualizado", money(resumo["total_atualizado"]))
    c4.metric("Pagamentos considerados", money(resumo["pagamentos_considerados"]))

    if resumo["competencias_faltando"]:
        st.error(f"Taxas faltando: {resumo['competencias_faltando']}")
    if resumo["competencias_provisorias"]:
        st.warning(f"Taxas provisórias usadas: {resumo['competencias_provisorias']}")

    st.markdown("### Dívidas atualizadas")
    df_dividas = df_or_empty(resultado["dividas"])
    if not df_dividas.empty:
        st.dataframe(df_dividas, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma dívida vencida até a data-base.")

    st.markdown("### Pagamentos alocados")
    df_aloc = df_or_empty(resultado["alocacoes"])
    if not df_aloc.empty:
        st.dataframe(df_aloc, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum pagamento considerado.")


with tabs[1]:
    st.subheader("Devedores")

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

    st.markdown("### Cadastrados")
    devs = db.list_devedores()
    if devs:
        st.dataframe(pd.DataFrame(devs), use_container_width=True, hide_index=True)
        with st.expander("Desativar devedor"):
            alvo = st.number_input("ID do devedor", min_value=1, step=1)
            if st.button("Desativar"):
                db.delete_devedor(int(alvo))
                st.success("Devedor desativado.")
                st.rerun()
    else:
        st.info("Nenhum devedor cadastrado.")


with tabs[2]:
    st.subheader("Dívidas")
    devedores = db.list_devedores()

    if devedores:
        with st.form("form_divida"):
            labels = [f'{d["nome"]} #{d["id"]}' for d in devedores]
            escolhido = st.selectbox("Devedor", labels)
            devedor = devedores[labels.index(escolhido)]
            tipo = st.selectbox("Tipo", ["Mensalidade", "Décimo terceiro", "Férias", "Empréstimo", "Reembolso", "Serviço", "Outros"])
            descricao = st.text_input("Descrição", value="")
            valor = st.number_input("Valor original", min_value=0.0, step=100.0, format="%.2f")
            vencimento = st.date_input("Data de vencimento", value=date.today())
            obs = st.text_area("Observações da dívida")
            submitted = st.form_submit_button("Cadastrar dívida")
            if submitted:
                if valor <= 0:
                    st.error("Informe valor maior que zero.")
                elif not descricao.strip():
                    st.error("Informe descrição.")
                else:
                    db.add_divida(devedor["id"], descricao, tipo, valor, vencimento.isoformat(), obs)
                    st.success("Dívida cadastrada.")
                    st.rerun()

    st.markdown("### Dívidas cadastradas")
    divs = db.list_dividas(incluir_canceladas=True)
    if divs:
        st.dataframe(pd.DataFrame(divs), use_container_width=True, hide_index=True)
        with st.expander("Cancelar dívida"):
            alvo = st.number_input("ID da dívida", min_value=1, step=1, key="cancelar_divida_id")
            if st.button("Cancelar dívida"):
                db.delete_divida(int(alvo))
                st.success("Dívida cancelada.")
                st.rerun()
    else:
        st.info("Nenhuma dívida cadastrada.")


with tabs[3]:
    st.subheader("Pagamentos")
    devedores = db.list_devedores()

    if devedores:
        with st.form("form_pagamento"):
            labels = [f'{d["nome"]} #{d["id"]}' for d in devedores]
            escolhido = st.selectbox("Devedor", labels, key="pag_devedor")
            devedor = devedores[labels.index(escolhido)]

            dividas_devedor = db.list_dividas(devedor_id=devedor["id"])
            divida_labels = ["Alocar automaticamente nas dívidas mais antigas"] + [
                f'{d["descricao"]} | venc. {d["data_vencimento"]} | #{d["id"]}' for d in dividas_devedor
            ]
            divida_escolhida = st.selectbox("Dívida específica ou automático", divida_labels)
            divida_id = None
            if divida_escolhida != divida_labels[0]:
                divida_id = dividas_devedor[divida_labels.index(divida_escolhida) - 1]["id"]

            data_pag = st.date_input("Data do pagamento", value=date.today())
            valor = st.number_input("Valor pago", min_value=0.0, step=100.0, format="%.2f")
            descricao = st.text_input("Descrição", value="PIX")
            comprovante = st.text_input("Referência do comprovante/arquivo (opcional)")
            submitted = st.form_submit_button("Registrar pagamento")
            if submitted:
                if valor <= 0:
                    st.error("Informe valor maior que zero.")
                else:
                    db.add_pagamento(devedor["id"], divida_id, data_pag.isoformat(), valor, descricao, comprovante)
                    st.success("Pagamento registrado.")
                    st.rerun()

    st.markdown("### Pagamentos cadastrados")
    pags = db.list_pagamentos()
    if pags:
        st.dataframe(pd.DataFrame(pags), use_container_width=True, hide_index=True)
        with st.expander("Excluir pagamento"):
            alvo = st.number_input("ID do pagamento", min_value=1, step=1)
            if st.button("Excluir pagamento"):
                db.delete_pagamento(int(alvo))
                st.success("Pagamento excluído.")
                st.rerun()
    else:
        st.info("Nenhum pagamento registrado.")


with tabs[4]:
    st.subheader("Taxas IPCA + Taxa Legal")
    st.write("Atualize as taxas oficiais pela API SGS do Banco Central ou cadastre manualmente.")

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
                        ipca_pct=None if pd.isna(row.get("ipca_pct")) else float(row["ipca_pct"]),
                        taxa_legal_pct=None if pd.isna(row.get("taxa_legal_pct")) else float(row["taxa_legal_pct"]),
                        fonte=row["fonte"],
                        status=row["status"],
                    )
                st.success(f"{len(df)} competência(s) atualizada(s).")
                st.rerun()
            except Exception as e:
                st.error(f"Falha ao buscar no BCB: {e}")

    with st.expander("Cadastrar/alterar taxa manualmente"):
        with st.form("form_taxa"):
            comp = st.text_input("Competência (YYYY-MM)", value=f"{date.today().year:04d}-{date.today().month:02d}")
            ipca = st.number_input("IPCA mensal (%)", value=0.0, step=0.01, format="%.4f")
            tl = st.number_input("Taxa Legal mensal (%)", value=0.0, step=0.01, format="%.6f")
            status = st.selectbox("Status", ["Oficial", "Provisória"])
            fonte = st.text_input("Fonte", value="Manual")
            submitted = st.form_submit_button("Salvar taxa")
            if submitted:
                db.upsert_taxa(comp.strip(), ipca, tl, fonte, status)
                st.success("Taxa salva.")
                st.rerun()

    taxas = db.list_taxas()
    if taxas:
        st.dataframe(pd.DataFrame(taxas), use_container_width=True, hide_index=True)
        with st.expander("Excluir taxa"):
            alvo = st.number_input("ID da taxa", min_value=1, step=1)
            if st.button("Excluir taxa"):
                db.delete_taxa(int(alvo))
                st.success("Taxa excluída.")
                st.rerun()
    else:
        st.info("Nenhuma taxa cadastrada ainda.")


with tabs[5]:
    st.subheader("Relatórios")
    devedor_id = select_devedor("Relatório de", include_all=True)

    resultado = calcular_carteira(
        db.list_dividas(devedor_id=None),
        db.list_pagamentos(devedor_id=None),
        db.taxas_dict(),
        db.get_settings(),
        data_base,
        devedor_id=devedor_id,
    )

    st.write(f"Total atualizado em {data_base.isoformat()}: **{money(resultado['resumo']['total_atualizado'])}**")

    excel_bytes = gerar_excel(resultado, db.list_taxas())
    st.download_button(
        "Baixar relatório Excel",
        data=excel_bytes,
        file_name=f"relatorio_cobranca_{data_base.isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    try:
        pdf_bytes = gerar_pdf(resultado)
        st.download_button(
            "Baixar relatório PDF",
            data=pdf_bytes,
            file_name=f"relatorio_cobranca_{data_base.isoformat()}.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.warning(f"Não foi possível gerar PDF: {e}")
