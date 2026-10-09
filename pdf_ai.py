import fitz  # PyMuPDF
import os
from gemini import ask_gemini


def extract_pdf_text(pdf_path):
    text = ""

    doc = fitz.open(pdf_path)

    for page in doc:
        text += page.get_text()

    doc.close()
    return text


def summarize_pdf(pdf_path):
    pdf_text = extract_pdf_text(pdf_path)

    if not pdf_text.strip():
        return "No text found in the PDF."

    prompt = f"""
You are an AI assistant.

Read the following PDF content and create:

1. Short Summary
2. Important Points
3. Conclusion

PDF Content:

{pdf_text[:25000]}
"""

    return ask_gemini(prompt)


def ask_pdf(pdf_path, question):
    pdf_text = extract_pdf_text(pdf_path)

    prompt = f"""
Answer ONLY using the PDF.

PDF:

{pdf_text[:25000]}

Question:

{question}
"""

    return ask_gemini(prompt)