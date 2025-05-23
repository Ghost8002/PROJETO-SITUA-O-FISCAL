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
import pdfplumber
from typing import Dict, List, Tuple, Optional
import concurrent.futures

# Extrai texto de bytes de PDF
def extract_text_from_bytes(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
        text += "\n"
    return text

# Função para extrair nome da empresa do PDF
def extract_company_name_from_bytes(file_bytes: bytes) -> str:
    """
    Extrai o nome da empresa do PDF, buscando o padrão 'CNPJ: XX.XXX.XXX - NOME DA EMPRESA'.
    """
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages[:2]:
            text = page.extract_text() or ""
            # Procura o padrão CNPJ seguido do nome da empresa
            match = re.search(r'CNPJ:\s*(\d{2}\.\d{3}\.\d{3})\s*-\s*(.+)', text)
            if match:
                return match.group(2).strip()
    return None

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

# Cache para armazenar resultados processados
@st.cache_data
def process_pdf(file_bytes: bytes) -> Tuple[Optional[str], bool, bool]:
    """
    Processa um PDF e retorna o nome da empresa e status de parcelamento.
    """
    try:
        # Extrai texto do PDF
        reader = PdfReader(BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
            text += "\n"

        # Extrai nome da empresa
        empresa = None
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for page in pdf.pages[:2]:
                text_pdf = page.extract_text() or ""
                match = re.search(r'CNPJ:\s*(\d{2}\.\d{3}\.\d{3})\s*-\s*(.+)', text_pdf)
                if match:
                    empresa = match.group(2).strip()
                    break

        # Analisa parcelamento
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

        return empresa, rf_parc, pgfn_parc
    except Exception as e:
        st.error(f"Erro ao processar PDF: {str(e)}")
        return None, False, False

# Gera PDF resumo da análise
def generate_pdf(results: List[Dict]) -> BytesIO:
    """Gera PDF com os resultados da análise."""
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
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ]))
    elems.append(table)
    doc.build(elems)
    buffer.seek(0)
    return buffer

def filter_results(results: List[Dict], search_terms: List[str]) -> List[Dict]:
    """Filtra resultados baseado em múltiplos termos de busca."""
    if not search_terms:
        return results
    
    filtered = []
    for result in results:
        empresa = result["empresa"].lower()
        if any(term.lower() in empresa for term in search_terms):
            filtered.append(result)
    return filtered

# Aplicação Streamlit unificada
def main():
    st.title("Processador e Analisador de Situação Fiscal")
    
    # Sidebar para pesquisa
    st.sidebar.title("Pesquisa por Empresas")
    st.sidebar.markdown("""
    Digite os nomes das empresas para pesquisar.
    Você pode:
    - Digitar múltiplos nomes separados por vírgula
    - Ou colar uma lista de empresas (uma por linha)
    """)
    
    search_input = st.sidebar.text_area(
        "Digite os nomes das empresas",
        height=150,
        help="Digite os nomes separados por vírgula ou quebra de linha"
    )
    
    # Processa os termos de busca
    search_terms = []
    if search_input:
        # Divide por vírgula ou quebra de linha
        terms = re.split(r'[,|\n]', search_input)
        # Remove espaços e linhas vazias
        search_terms = [term.strip() for term in terms if term.strip()]
    
    # Upload do arquivo ZIP
    zip_file = st.file_uploader("ZIP de relatórios PDF", type="zip")
    
    if zip_file:
        # Processa o ZIP em memória
        with zipfile.ZipFile(BytesIO(zip_file.getvalue())) as zf:
            # Lista para armazenar resultados
            all_results = []
            matched_files = []
            unmatched_files = []
            
            # Processa PDFs em paralelo
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future_to_file = {
                    executor.submit(process_pdf, zf.read(info.filename)): info.filename
                    for info in zf.infolist()
                    if info.filename.lower().endswith('.pdf')
                }
                
                for future in concurrent.futures.as_completed(future_to_file):
                    filename = future_to_file[future]
                    try:
                        empresa, rf_parc, pgfn_parc = future.result()
                        if empresa:
                            result = {
                                "empresa": empresa,
                                "rf": rf_parc,
                                "pgfn": pgfn_parc,
                                "filename": filename
                            }
                            all_results.append(result)
                            
                            # Organiza arquivos
                            file_bytes = zf.read(filename)
                            new_name = f"{empresa}.pdf"
                            matched_files.append((new_name, file_bytes))
                        else:
                            unmatched_files.append((filename, zf.read(filename)))
                    except Exception as e:
                        st.error(f"Erro ao processar {filename}: {str(e)}")
            
            # Filtra resultados se houver termos de pesquisa
            if search_terms:
                filtered_results = filter_results(all_results, search_terms)
                if filtered_results:
                    df = pd.DataFrame([{
                        "Empresa": r["empresa"],
                        "Parcelamento RF": "Sim" if r["rf"] else "Não",
                        "Parcelamento PGFN": "Sim" if r["pgfn"] else "Não"
                    } for r in filtered_results])
                    st.dataframe(df)
                    
                    # Botões de download
                    if search_terms and filtered_results:
                        # Download dos PDFs filtrados
                        filtered_buffer = BytesIO()
                        with zipfile.ZipFile(filtered_buffer, 'w') as zout:
                            for result in filtered_results:
                                zout.writestr(
                                    f"{result['empresa']}.pdf",
                                    zf.read(result["filename"])
                                )
                        filtered_buffer.seek(0)
                        
                        st.download_button(
                            "Download PDFs das Empresas Filtradas",
                            data=filtered_buffer,
                            file_name="empresas_filtradas.zip",
                            mime="application/zip"
                        )

                        # Download PDF do relatório
                        try:
                            pdf_buffer = generate_pdf(filtered_results)
                            st.download_button(
                                "Download PDF (verificação de parcelamento)",
                                data=pdf_buffer,
                                file_name="resultado_parcelamento.pdf",
                                mime="application/pdf"
                            )
                        except Exception as e:
                            st.error(f"Erro ao gerar PDF: {str(e)}")
                    else:
                        # Download PDF do relatório completo
                        try:
                            pdf_buffer = generate_pdf(all_results)
                            st.download_button(
                                "Download PDF (verificação de parcelamento)",
                                data=pdf_buffer,
                                file_name="resultado_parcelamento.pdf",
                                mime="application/pdf"
                            )
                        except Exception as e:
                            st.error(f"Erro ao gerar PDF: {str(e)}")
                else:
                    st.warning(f"Nenhuma empresa encontrada com os termos: {', '.join(search_terms)}")
            else:
                # Mostra todos os resultados
                st.subheader("Todos os Resultados")
                df = pd.DataFrame([{
                    "Empresa": r["empresa"],
                    "Parcelamento RF": "Sim" if r["rf"] else "Não",
                    "Parcelamento PGFN": "Sim" if r["pgfn"] else "Não"
                } for r in all_results])
                st.dataframe(df)
            
            # Download ZIP organizado
            out_buffer = BytesIO()
            with zipfile.ZipFile(out_buffer, 'w') as zout:
                for fname, data in matched_files:
                    zout.writestr(f"renomeados/{fname}", data)
                for orig, data in unmatched_files:
                    zout.writestr(f"nao_encontrados/{orig}", data)
            out_buffer.seek(0)
            
            st.download_button(
                "Download de todas as empresas",
                data=out_buffer,
                file_name="empresas_renomeadas.zip",
                mime="application/zip"
            )

if __name__ == "__main__":
    main()
