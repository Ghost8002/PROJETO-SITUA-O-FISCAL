import streamlit as st
import pandas as pd
import zipfile
import re
from io import BytesIO
from PyPDF2 import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# Extrai texto de bytes de PDF
def extract_text_from_bytes(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
        text += "\n"
    return text

# Analisa se há parcelamento nas seções Receita Federal e PGFN
def analyze_text(text: str) -> tuple[bool, bool]:
    rf_title = "Diagnóstico Fiscal na Receita Federal"
    pgfn_title = "Diagnóstico Fiscal na Procuradoria-Geral da Fazenda Nacional"
    rf_start = text.find(rf_title)
    pgfn_start = text.find(pgfn_title)
    rf_section = text[rf_start:pgfn_start] if rf_start != -1 and pgfn_start != -1 else ""
    pgfn_section = text[pgfn_start:] if pgfn_start != -1 else ""

    rf_parc = "EM PARCELAMENTO" in rf_section
    if not rf_parc and "BASE INDISPONÍVEL" in rf_section and "Parcelamento" in rf_section:
        rf_parc = False
    pgfn_parc = "Pendência - Parcelamento" in pgfn_section
    if not pgfn_parc and "Não foram detectadas pendências/exigibilidades suspensas" in pgfn_section:
        pgfn_parc = False
    return rf_parc, pgfn_parc

# Gera PDF resumo da análise
def generate_pdf(results: list[dict]) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elems = []
    elems.append(Paragraph("Relatório de Parcelamento", styles['Heading1']))
    elems.append(Spacer(1, 12))

    data = [["Empresa", "Parcelamento RF", "Parcelamento PGFN"]]
    for r in results:
        data.append([
            r["empresa"],
            "Sim" if r["rf"] else "Não",
            "Sim" if r["pgfn"] else "Não"
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkgray),
        ('TEXTCOLOR',   (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING',(0,0), (-1,0), 12),
        ('BACKGROUND',  (0,1), (-1,-1), colors.beige),
        ('GRID',        (0,0), (-1,-1), 1, colors.black),
    ]))
    elems.append(table)
    doc.build(elems)
    buffer.seek(0)
    return buffer

# Aplicação Streamlit unificada
def main():
    st.title("Processador e Analisador de Situação Fiscal")
    st.markdown(
        "Faça upload de um arquivo ZIP com relatórios fiscais em PDF e cole o mapeamento abaixo."
    )

    zip_file = st.file_uploader("ZIP de relatórios PDF (arquivo do veri)", type="zip")
    mapping_text = st.text_area(
        "Cole aqui o mapeamento (lista das empresas)", height=200
    )

    if zip_file and mapping_text:
        # Lê mapeamento do texto
        mapping: dict[str, str] = {}
        for line in mapping_text.splitlines():
            if '\t' in line:
                name, cnpj = line.split('\t')
                mapping[re.sub(r'\D', '', cnpj)] = name.strip()

        # Descompacta ZIP em memória
        zf = zipfile.ZipFile(BytesIO(zip_file.getvalue()))
        results: list[dict] = []
        matched_files: list[tuple[str, bytes]] = []
        unmatched_files: list[tuple[str, bytes]] = []

        for info in zf.infolist():
            if info.filename.lower().endswith('.pdf'):
                file_bytes = zf.read(info.filename)
                # Extrai CNPJ do nome de arquivo
                match = re.search(r"(\d{14})", info.filename)
                cnpj = match.group(1) if match else None
                empresa = mapping.get(cnpj, "Desconhecida")

                # Analisa parcelamento
                text = extract_text_from_bytes(file_bytes)
                rf_parc, pgfn_parc = analyze_text(text)

                results.append({
                    "empresa": empresa,
                    "rf": rf_parc,
                    "pgfn": pgfn_parc
                })

                # Agrupa arquivos renomeados e não encontrados
                if empresa != "Desconhecida":
                    new_name = f"{empresa}.pdf"
                    matched_files.append((new_name, file_bytes))
                else:
                    unmatched_files.append((info.filename, file_bytes))

        # Filtra apenas empresas conhecidas para exibição e relatórios
        known_results = [r for r in results if r["empresa"] != "Desconhecida"]

        # Exibe resultados na tabela
        df = pd.DataFrame([{
            "Empresa": r["empresa"],
            "Parcelamento RF": "Sim" if r["rf"] else "Não",
            "Parcelamento PGFN": "Sim" if r["pgfn"] else "Não"
        } for r in known_results])
        st.subheader("Resultados da Análise")
        st.dataframe(df)

        # Download CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Download CSV", data=csv,
            file_name="resultado_parcelamento.csv",
            mime="text/csv"
        )

        # Download PDF
        try:
            pdf_buffer = generate_pdf(known_results)
            st.download_button(
                "Download PDF", data=pdf_buffer,
                file_name="resultado_parcelamento.pdf",
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"Erro ao gerar PDF: {e}")

        # Download ZIP com pastas separadas
        out_buffer = BytesIO()
        with zipfile.ZipFile(out_buffer, 'w') as zout:
            # Pasta dos PDFs renomeados
            for fname, data in matched_files:
                zout.writestr(f"renomeados/{fname}", data)
            # Pasta dos PDFs não encontrados
            for orig, data in unmatched_files:
                zout.writestr(f"nao_encontrados/{orig}", data)
        out_buffer.seek(0)
        st.download_button(
            "Download ZIP Organizado", data=out_buffer,
            file_name="relatorios_organizados.zip",
            mime="application/zip"
        )

if __name__ == "__main__":
    main()
