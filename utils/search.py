from app import Note, PDF, Image


def universal_search(query):
    query = query.strip()

    notes = Note.query.filter(
        Note.title.ilike(f"%{query}%") |
        Note.content.ilike(f"%{query}%")
    ).all()

    pdfs = PDF.query.filter(
        PDF.filename.ilike(f"%{query}%")
    ).all()

    images = Image.query.filter(
        Image.filename.ilike(f"%{query}%")
    ).all()

    return {
        "notes": notes,
        "pdfs": pdfs,
        "images": images
    }