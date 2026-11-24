from pathlib import Path

import pymupdf
from docx import Document


root = Path(__file__).parent
docx_path = root / "SecureCloud_IEEE_Paper.docx"
pdf_path = root / "SecureCloud_IEEE_Paper.pdf"
preview_dir = root.parent / "runtime" / "ieee-revised-preview"
preview_dir.mkdir(parents=True, exist_ok=True)

document = Document(docx_path)
paragraph_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
required = [
    "Dr. S. Anthoniraj",
    "I. INTRODUCTION",
    "II. RELATED WORK",
    "III. SYSTEM ARCHITECTURE",
    "IV. TEMPORAL-GRAPH RISK ENGINE",
    "V. EXPERIMENTAL METHOD",
    "VI. RESULTS",
    "VII. DISCUSSION AND THREATS TO VALIDITY",
    "VIII. CONCLUSION",
    "[12] React Team",
]
missing = [value for value in required if value not in paragraph_text]
colors = {
    str(run.font.color.rgb)
    for paragraph in document.paragraphs
    for run in paragraph.runs
    if run.font.color.rgb is not None
}
fonts = {
    run.font.name
    for paragraph in document.paragraphs
    for run in paragraph.runs
    if run.font.name
}

pdf = pymupdf.open(pdf_path)
pdf_colors = set()
pdf_fonts = set()
for page_number, page in enumerate(pdf, start=1):
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                pdf_colors.add(span.get("color"))
                pdf_fonts.add(span.get("font"))
    page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2), alpha=False).save(
        preview_dir / f"page-{page_number}.png"
    )

print(f"paragraphs={len(document.paragraphs)} tables={len(document.tables)}")
print(f"missing_required_content={missing}")
print(f"docx_fonts={sorted(fonts)} docx_colors={sorted(colors)}")
print(f"pdf_pages={pdf.page_count} pdf_fonts={sorted(pdf_fonts)} pdf_colors={sorted(pdf_colors)}")
print(f"previews={preview_dir}")

if missing or len(document.tables) != 2:
    raise SystemExit(1)
if colors - {"000000"} or fonts - {"Times New Roman"}:
    raise SystemExit(1)
if pdf_colors - {0}:
    raise SystemExit(1)
