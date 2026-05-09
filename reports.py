from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd

from calculos import money


def gerar_excel(resultado: dict[str, Any], taxas_rows: list[dict[str, Any]]) -> bytes:
    output = BytesIO()
    resumo = resultado["resumo"]
    df_resumo = pd.DataFrame(
        [
            {"Campo": "Data-base", "Valor": resumo["data_base"]},
            {"Campo": "Total original vencido", "Valor": resumo["total_original_vencido"]},
            {"Campo": "Pagamentos considerados", "Valor": resumo["pagamentos_considerados"]},
            {"Campo": "Principal aberto estimado", "Valor": resumo["principal_aberto_estimado"]},
            {"Campo": "Encargos IPCA + Taxa Legal", "Valor": resumo["encargos"]},
            {"Campo": "Total atualizado", "Valor": resumo["total_atualizado"]},
            {"Campo": "Competências provisórias", "Valor": resumo["competencias_provisorias"]},
            {"Campo": "Competências faltando", "Valor": resumo["competencias_faltando"]},
        ]
    )

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
        pd.DataFrame(resultado["dividas"]).to_excel(writer, sheet_name="Dividas_atualizadas", index=False)
        pd.DataFrame(resultado["alocacoes"]).to_excel(writer, sheet_name="Pagamentos_alocados", index=False)
        pd.DataFrame(taxas_rows).to_excel(writer, sheet_name="Taxas", index=False)

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                max_len = 10
                col_letter = col[0].column_letter
                for cell in col:
                    try:
                        max_len = max(max_len, len(str(cell.value)))
                    except Exception:
                        pass
                ws.column_dimensions[col_letter].width = min(max_len + 2, 60)

    return output.getvalue()


def gerar_pdf(resultado: dict[str, Any], titulo: str = "Demonstrativo de cobranca") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    styles = getSampleStyleSheet()
    story = []

    resumo = resultado["resumo"]
    story.append(Paragraph(titulo, styles["Title"]))
    story.append(Paragraph(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 0.4 * cm))

    dados = [
        ["Data-base", resumo["data_base"]],
        ["Total original vencido", money(resumo["total_original_vencido"])],
        ["Pagamentos considerados", money(resumo["pagamentos_considerados"])],
        ["Principal aberto estimado", money(resumo["principal_aberto_estimado"])],
        ["Encargos IPCA + Taxa Legal", money(resumo["encargos"])],
        ["Total atualizado", money(resumo["total_atualizado"])],
    ]
    table = Table(dados, colWidths=[7 * cm, 8 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.4 * cm))

    if resumo.get("competencias_provisorias"):
        story.append(Paragraph(f"Competencias com taxas provisorias: {resumo['competencias_provisorias']}", styles["Normal"]))
    if resumo.get("competencias_faltando"):
        story.append(Paragraph(f"Competencias faltando: {resumo['competencias_faltando']}", styles["Normal"]))

    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Dividas atualizadas", styles["Heading2"]))

    rows = [["Vencimento", "Tipo", "Descricao", "Original", "Encargos", "Saldo"]]
    for d in resultado["dividas"]:
        rows.append([
            d["vencimento"],
            d["tipo"],
            d["descricao"][:35],
            money(d["valor_original"]),
            money(d["encargos"]),
            money(d["saldo_atualizado"]),
        ])

    t2 = Table(rows, colWidths=[2.5 * cm, 2.8 * cm, 5.2 * cm, 2.4 * cm, 2.4 * cm, 2.6 * cm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t2)

    doc.build(story)
    return buffer.getvalue()
