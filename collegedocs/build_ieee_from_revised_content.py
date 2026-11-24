from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.section import WD_SECTION_START
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

SOURCE = Path(__file__).with_name("SecureCloud_IEEE_Paper_Revised_Content.md")
OUTPUT = Path(__file__).with_name("SecureCloud_IEEE_Paper.docx")

REFERENCES = [
    "[1] S. Rose, O. Borchert, S. Mitchell, and S. Connelly, Zero Trust Architecture, NIST SP 800-207, Aug. 2020, doi: 10.6028/NIST.SP.800-207.",
    "[2] R. Chandramouli and Z. Butcher, A Zero Trust Architecture Model for Access Control in Cloud-Native Applications in Multi-Cloud Environments, NIST SP 800-207A, Sept. 2023, doi: 10.6028/NIST.SP.800-207A.",
    "[3] I. J. King and H. H. Huang, ‘Euler: Detecting Network Lateral Movement via Scalable Temporal Graph Link Prediction,’ in Proc. NDSS, 2022, doi: 10.14722/ndss.2022.24107.",
    "[4] Y. Seo, M. Defferrard, P. Vandergheynst, and X. Bresson, ‘Structured Sequence Modeling with Graph Convolutional Recurrent Networks,’ arXiv:1612.07659, 2016.",
    "[5] B. Rozemberczki et al., ‘PyTorch Geometric Temporal: Spatiotemporal Signal Processing with Neural Machine Learning Models,’ arXiv:2104.07788, 2021.",
    "[6] Kubernetes Authors, ‘Network Policies,’ Kubernetes Documentation, 2026. [Online]. Available: https://kubernetes.io/docs/concepts/services-networking/network-policies/.",
    "[7] Cilium Authors, ‘Deny Policies,’ Cilium Documentation, 2026. [Online]. Available: https://docs.cilium.io/en/stable/security/policy/deny/.",
    "[8] Cilium Authors, ‘Hubble Observability,’ Cilium Documentation, 2026. [Online]. Available: https://docs.cilium.io/en/stable/observability/hubble/.",
    "[9] U.S. Senate Committee on Commerce, Science, and Transportation, A ‘Kill Chain’ Analysis of the 2013 Target Data Breach, Majority Staff Report, Mar. 2014.",
    "[10] Google Cloud, ‘Online Boutique,’ GitHub repository, version 0.10.3, 2026. [Online]. Available: https://github.com/GoogleCloudPlatform/microservices-demo.",
    "[11] FastAPI, ‘FastAPI Documentation,’ 2026. [Online]. Available: https://fastapi.tiangolo.com/.",
    "[12] React Team, ‘React Documentation,’ 2026. [Online]. Available: https://react.dev/.",
]


def set_columns(section, count: int):
    columns = section._sectPr.find(qn("w:cols"))
    if columns is None:
        columns = OxmlElement("w:cols")
        section._sectPr.append(columns)
    columns.set(qn("w:num"), str(count))
    columns.set(qn("w:space"), "360")


def setup_ieee_doc():
    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.0
    return document


def ieee_heading(document, text: str, level: int = 1):
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if level == 1 else WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text.upper() if level == 1 else text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0, 0, 0)
    run.font.italic = level == 2
    return paragraph


def ieee_para(document, text: str):
    paragraph = document.add_paragraph(text)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.first_line_indent = Inches(0.15)
    paragraph.paragraph_format.line_spacing = 1.0
    paragraph.paragraph_format.space_after = Pt(2)
    for run in paragraph.runs:
        run.font.name = "Times New Roman"
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0, 0, 0)
    return paragraph


def add_ieee_table(document, headers, rows):
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for index, heading in enumerate(headers):
        table.rows[0].cells[index].text = heading
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = str(value)
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.0
                for run in paragraph.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(7.5)
                    run.font.color.rgb = RGBColor(0, 0, 0)
                    run.font.bold = row_index == 0
    return table


def markdown_sections(text: str):
    lines = text.splitlines()
    title = lines[0].removeprefix("# ").strip()
    nonempty = [line.strip() for line in lines[1:] if line.strip()]
    authors = nonempty[0]
    affiliation = nonempty[1]

    sections: dict[str, list[str]] = {}
    current = None
    block: list[str] = []

    def finish_block():
        nonlocal block
        if current and block:
            sections[current].append(" ".join(block).strip())
        block = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            finish_block()
            current = stripped[3:].strip()
            sections[current] = []
        elif current is None:
            continue
        elif not stripped:
            finish_block()
        elif stripped.startswith("### "):
            finish_block()
            sections[current].append(stripped)
        else:
            block.append(stripped)
    finish_block()
    return title, authors, affiliation, sections


def prose_blocks(blocks: list[str]) -> list[str]:
    return [
        block
        for block in blocks
        if not block.startswith("|") and not block.startswith("### ")
    ]


def add_blocks(document, blocks: list[str]):
    for block in prose_blocks(blocks):
        ieee_para(document, block)


def build() -> Path:
    title_text, authors_text, affiliation_text, sections = markdown_sections(
        SOURCE.read_text(encoding="utf-8")
    )
    abstract_blocks = sections["Abstract"]
    index_terms = abstract_blocks.pop().replace("**Index Terms—**", "").strip()

    document = setup_ieee_doc()
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(8)
    run = title.add_run(title_text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(18)
    run.font.color.rgb = RGBColor(0, 0, 0)

    authors = document.add_paragraph()
    authors.alignment = WD_ALIGN_PARAGRAPH.CENTER
    authors.paragraph_format.space_after = Pt(8)
    run = authors.add_run(f"{authors_text}\n{affiliation_text}")
    run.font.name = "Times New Roman"
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(0, 0, 0)

    abstract = document.add_paragraph()
    abstract.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    abstract.paragraph_format.space_after = Pt(3)
    run = abstract.add_run("Abstract—")
    run.bold = True
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0, 0, 0)
    run = abstract.add_run(" ".join(abstract_blocks))
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0, 0, 0)

    index = document.add_paragraph()
    index.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    index.paragraph_format.space_after = Pt(5)
    run = index.add_run("Index Terms—")
    run.bold = True
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0, 0, 0)
    run = index.add_run(index_terms)
    run.font.name = "Times New Roman"
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0, 0, 0)

    body = document.add_section(WD_SECTION_START.CONTINUOUS)
    body.top_margin = Inches(0.7)
    body.bottom_margin = Inches(0.75)
    body.left_margin = body.right_margin = Inches(0.65)
    set_columns(body, 2)

    for key in ["I. Introduction", "II. Related Work", "III. System Architecture"]:
        ieee_heading(document, key)
        add_blocks(document, sections[key])
        if key == "III. System Architecture":
            add_ieee_table(
                document,
                ["Plane", "Components", "Output"],
                [
                    ("Management", "React, FastAPI, SQLite", "Authorized desired state"),
                    ("Infrastructure", "K3s, Kubernetes API", "Observed workloads"),
                    ("Enforcement", "Cilium policy", "Allow/deny verdict"),
                    ("Detection", "Hubble, GConvGRU, risk", "Scored evidence"),
                    ("Response", "Incident adapter", "Quarantine/restore state"),
                ],
            )

    ieee_heading(document, "IV. Temporal-Graph Risk Engine")
    current_subheading = None
    for block in sections["IV. Temporal-Graph Risk Engine"]:
        if block.startswith("### "):
            current_subheading = block.removeprefix("### ")
            ieee_heading(document, current_subheading, 2)
        elif not block.startswith("|"):
            ieee_para(document, block)

    ieee_heading(document, "V. Experimental Method")
    add_blocks(document, sections["V. Experimental Method"])

    ieee_heading(document, "VI. Results")
    add_ieee_table(
        document,
        ["Method", "Prec.", "Recall", "F1", "FPR", "AP", "Latency"],
        [
            ("Frequency", "1.000", ".846", ".917", ".000", ".880", "28.0 s"),
            ("Temporal", ".923", ".923", ".923", ".091", ".771", "28.3 s"),
        ],
    )
    add_blocks(document, sections["VI. Results"])

    ieee_heading(document, "VII. Discussion and Threats to Validity")
    add_blocks(document, sections["VII. Discussion and Threats to Validity"])
    ieee_heading(document, "VIII. Conclusion")
    add_blocks(document, sections["VIII. Conclusion"])

    ieee_heading(document, "References")
    for reference in REFERENCES:
        paragraph = document.add_paragraph(reference)
        paragraph.paragraph_format.left_indent = Inches(0.15)
        paragraph.paragraph_format.first_line_indent = Inches(-0.15)
        paragraph.paragraph_format.line_spacing = 1.0
        paragraph.paragraph_format.space_after = Pt(1)
        for run in paragraph.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0, 0, 0)

    closing = document.add_section(WD_SECTION_START.CONTINUOUS)
    set_columns(closing, 1)
    document.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build())
