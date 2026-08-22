"""
services/document_import.py — Extract plain text from uploaded files.

Same libraries as the original desktop app (PyMuPDF for PDF, python-docx
for Word) — both are pure server-side Python packages with no Windows
dependency, so they work unchanged on Render.
"""

import pymupdf as fitz   # PyMuPDF (import name updated per their own deprecation notice)
import docx               # python-docx


def extract_text(file_storage):
    """
    file_storage: a Flask `request.files['file']` FileStorage object.
    Returns extracted plain text, or raises ValueError for unsupported types.
    """
    filename = (file_storage.filename or "").lower()

    if filename.endswith(".pdf"):
        data = file_storage.read()
        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text.strip()

    if filename.endswith(".docx"):
        document = docx.Document(file_storage.stream)
        return "\n".join(p.text for p in document.paragraphs).strip()

    if filename.endswith(".txt"):
        return file_storage.read().decode("utf-8", errors="ignore").strip()

    raise ValueError("Unsupported file type. Please upload a .pdf, .docx, or .txt file.")
