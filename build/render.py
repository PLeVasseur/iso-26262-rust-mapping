from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

def render_docx_to_pngs(docx_path: Path, out_dir: Path, max_pages: int = 2) -> List[Path]:
    """
    Renders DOCX -> PDF -> PNG pages for quick visual QA.
    Requires: soffice (LibreOffice) and pdftoppm (poppler-utils).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) DOCX -> PDF
    subprocess.check_call([
        "soffice",
        "--headless",
        "--nologo",
        "--nolockcheck",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(docx_path),
    ])

    pdf_path = out_dir / (docx_path.stem + ".pdf")
    if not pdf_path.exists():
        # LibreOffice sometimes emits uppercase extension
        alt = out_dir / (docx_path.stem + ".PDF")
        if alt.exists():
            pdf_path = alt
        else:
            raise FileNotFoundError(f"Expected PDF not found after conversion: {pdf_path}")

    # 2) PDF -> PNGs (1-indexed pages)
    prefix = out_dir / (docx_path.stem + "-page")
    subprocess.check_call([
        "pdftoppm",
        "-png",
        "-f",
        "1",
        "-l",
        str(max_pages),
        str(pdf_path),
        str(prefix),
    ])

    pngs = sorted(out_dir.glob(prefix.name + "-*.png"))
    return pngs
