import os
import base64
import mimetypes
from datetime import datetime, timedelta
import sqlite3
import tempfile
import certifi
import ssl
import threading
import time

from pypdf import PdfReader 
import requests
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash,
    render_template_string,
    send_file
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from database import create_database, get_connection
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from requests.adapters import HTTPAdapter
from PIL import Image
from pypdf import PdfReader

try:
    from winotify import Notification, audio
    WINDOWS_NOTIFICATIONS_AVAILABLE = True
except ImportError:
    WINDOWS_NOTIFICATIONS_AVAILABLE = False


# =========================================================
# APP CONFIGURATION
# =========================================================
# =========================================================
# AI API CONFIGURATION
# =========================================================

load_dotenv()


def windows_server_ca_pems():
    """Return trusted Windows server roots as PEM while retaining TLS checks."""
    if os.name != "nt" or not hasattr(ssl, "enum_certificates"):
        return []
    pems = []
    try:
        for certificate, encoding, trust in ssl.enum_certificates("ROOT"):
            is_server_trusted = trust is True or (
                isinstance(trust, (tuple, list, set)) and "serverAuth" in trust
            )
            if encoding == "x509_asn" and is_server_trusted:
                pems.append(ssl.DER_cert_to_PEM_cert(certificate))
    except OSError:
        pass
    return pems


WINDOWS_SERVER_CA_PEMS = windows_server_ca_pems()


def build_ai_ssl_context():
    """Verify AI API TLS with certifi and Windows' trusted server roots."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    for certificate_pem in WINDOWS_SERVER_CA_PEMS:
        try:
            context.load_verify_locations(cadata=certificate_pem)
        except ssl.SSLError:
            # Ignore malformed store entries; keep normal TLS verification.
            continue
    return context


AI_SSL_CONTEXT = build_ai_ssl_context()


class VerifiedAIHTTPAdapter(HTTPAdapter):
    """Use the app's verified Windows-aware trust context for Requests APIs."""
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = AI_SSL_CONTEXT
        return super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = AI_SSL_CONTEXT
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def verified_ai_post(*args, **kwargs):
    """POST to an AI provider with certificate verification left enabled."""
    with requests.Session() as client:
        client.mount("https://", VerifiedAIHTTPAdapter())
        return client.post(*args, **kwargs)


def create_genai_client(api_key, timeout_ms=None):
    """Create Gemini client with certificate verification enabled."""
    return genai.Client(
        api_key=api_key,
        http_options=genai_types.HttpOptions(
            client_args={"verify": AI_SSL_CONTEXT},
            timeout=timeout_ms,
        ),
    )

GEMINI_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2")
]

GROK_KEYS = [
    os.getenv("GROK_API_KEY_1"),
    os.getenv("GROK_API_KEY_2")
]

GEMINI_KEYS = [
    key for key in GEMINI_KEYS
    if key
]

GROK_KEYS = [
    key for key in GROK_KEYS
    if key
]

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "dev-only-change-me-before-deploy"

# Session configuration
app.config["SESSION_COOKIE_NAME"] = "ai_second_brain_session"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("RENDER", "").lower() == "true" or os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true"
app.config["SESSION_REFRESH_EACH_REQUEST"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

# On hosts with a persistent disk (Render: /var/data), keep user uploads there.
# Locally, retain the original static/uploads layout for compatibility.
if os.environ.get("DATA_DIR"):
    UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
else:
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

PDF_FOLDER = os.path.join(UPLOAD_FOLDER, "pdfs")
IMAGE_FOLDER = os.path.join(UPLOAD_FOLDER, "images")
IMAGE_FALLBACK_FOLDER = os.path.join(tempfile.gettempdir(), "ai_second_brain_images")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PDF_FOLDER"] = PDF_FOLDER
app.config["IMAGE_FOLDER"] = IMAGE_FOLDER
app.config["IMAGE_FALLBACK_FOLDER"] = IMAGE_FALLBACK_FOLDER
try:
    os.makedirs(IMAGE_FALLBACK_FOLDER, exist_ok=True)
except OSError:
    IMAGE_FALLBACK_FOLDER = tempfile.gettempdir()


# =========================================================
# DATABASE
# =========================================================

create_database()


# =========================================================
# WINDOWS REMINDER NOTIFICATIONS
# =========================================================

def _show_windows_reminder(title, message):
    """Show a desktop-wide Windows popup and system tone, outside the browser."""
    safe_title = str(title or "Reminder due").replace("'", "''")
    safe_message = str(message or "Your scheduled reminder is due now.").replace("'", "''")
    shown = False

    # This is a Windows system sound, independent of the browser tab/page.
    try:
        import winsound
        winsound.PlaySound(
            "SystemExclamation",
            winsound.SND_ALIAS | winsound.SND_ASYNC,
        )
        shown = True
    except Exception:
        pass

    # Use a native top-most Windows dialog. It is outside the browser and is
    # created on a separate thread, so the Flask reminder scheduler never
    # pauses while the user is reading or dismissing the popup.
    try:
        import ctypes

        def show_topmost_dialog():
            ctypes.windll.user32.MessageBoxW(
                0,
                safe_message,
                safe_title,
                0x00000030 | 0x00010000 | 0x00040000,
            )

        threading.Thread(target=show_topmost_dialog, daemon=True).start()
        shown = True
    except Exception:
        pass

    # Also send a normal Action Center toast when Windows supports it.
    if WINDOWS_NOTIFICATIONS_AVAILABLE:
        try:
            toast = Notification(
                app_id="AI Second Brain",
                title=title or "Reminder due",
                msg=message or "Your scheduled reminder is due now.",
                duration="short",
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
            shown = True
        except Exception:
            pass
    return shown


def _reminder_notification_worker():
    """Checks saved reminders every 15 seconds while the Flask server runs."""
    while True:
        try:
            now = datetime.now().replace(second=0, microsecond=0)
            conn = get_connection()
            reminders_to_alert = conn.execute(
                """SELECT id, title, description, reminder_date, reminder_time,
                          duration_days, repeat_enabled
                   FROM reminders
                   WHERE completed = 0
                     AND COALESCE((SELECT notifications FROM settings
                                   WHERE settings.user_id = reminders.user_id), 1) = 1"""
            ).fetchall()

            for reminder in reminders_to_alert:
                try:
                    starts_at = datetime.strptime(
                        f"{reminder['reminder_date']} {reminder['reminder_time']}",
                        "%Y-%m-%d %H:%M",
                    )
                except (TypeError, ValueError):
                    continue

                day_offset = (now.date() - starts_at.date()).days
                repeats = bool(reminder["repeat_enabled"])
                allowed_days = max(1, int(reminder["duration_days"] or 1))
                valid_day = day_offset == 0 or (repeats and 0 <= day_offset < allowed_days)
                due_today = starts_at.replace(year=now.year, month=now.month, day=now.day)

                # Alert only during the scheduled minute; no old reminder popup
                # is shown after the app has been offline for a long time.
                if not valid_day or now < due_today or now - due_today >= timedelta(minutes=1):
                    continue

                alert_key = f"{reminder['id']}:{now.date().isoformat()}"
                try:
                    conn.execute(
                        "INSERT INTO reminder_notifications(reminder_id, alert_key) VALUES (?, ?)",
                        (reminder["id"], alert_key),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    continue

                _show_windows_reminder(
                    reminder["title"],
                    reminder["description"] or "Your scheduled reminder is due now.",
                )
            conn.close()
        except Exception:
            # Keep the scheduler alive even if a database is temporarily busy.
            try:
                conn.close()
            except Exception:
                pass
        time.sleep(15)


threading.Thread(
    target=_reminder_notification_worker,
    name="ai-second-brain-reminder-alerts",
    daemon=True,
).start()


# =========================================================
# HELPER
# =========================================================

def get_current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    conn = get_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    return user


def is_logged_in():

    return "user_id" in session


def answer_language_rule(selected_language, question):
    """Keeps AI text in exactly the language selected by the user."""
    if selected_language == "Tamil":
        return (
            "Reply in fluent, natural, everyday spoken Tamil, written in Tamil script. "
            "Use simple, clear sentences that sound natural when read aloud; avoid "
            "stiff literal translations, overly formal wording, and Tanglish. Keep "
            "essential technical names in English only when needed, and explain them "
            "briefly in Tamil. Do not switch the answer to English."
        )
    if selected_language == "English":
        return "Answer only in clear natural English. Do not switch to Tamil."
    if any("\u0B80" <= char <= "\u0BFF" for char in question):
        return (
            "Tamil was detected. Reply in fluent, natural, everyday spoken Tamil, "
            "written in Tamil script. Use simple sentences that sound natural when "
            "read aloud; avoid stiff literal translations, overly formal wording, "
            "and Tanglish. Keep essential technical names in English only when "
            "needed, and explain them briefly in Tamil."
        )
    return "Auto detected English: answer only in clear natural English."


def answer_heading(selected_language, question):
    """Keep the response heading in the same language as the answer."""
    is_tamil = selected_language == "Tamil" or (
        selected_language == "auto" and any("\u0B80" <= char <= "\u0BFF" for char in question)
    )
    return "## பதில்" if is_tamil else "## Answer"


def provider_unavailable_response(selected_language, question):
    """Keep even an offline provider message in the selected answer language."""
    is_tamil = selected_language == "Tamil" or (
        selected_language == "auto" and any("\u0B80" <= char <= "\u0BFF" for char in question)
    )
    if is_tamil:
        return (
            "## AI உதவியாளர்\n\n"
            "AI service தற்போது இணையத்தில் கிடைக்கவில்லை.\n\n"
            "- உங்கள் கேள்வி பாதுகாப்பாக பெறப்பட்டது.\n"
            "- இணைய இணைப்பு மற்றும் API key-ஐ சரிபார்த்து மீண்டும் முயற்சிக்கவும்."
        )
    return (
        "## AI Assistant\n\n"
        "AI service is temporarily unavailable.\n\n"
        "- Your question was received safely.\n"
        "- Check your internet connection and API key, then try again."
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if is_logged_in():
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        fullname = request.form.get(
            "fullname",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        ).strip()

        if not fullname or not email or not password:

            flash(
                "All fields are required.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        hashed_password = generate_password_hash(
            password
        )

        conn = get_connection()

        try:

            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO users(
                    fullname,
                    email,
                    password
                )
                VALUES (?, ?, ?)
                """,
                (
                    fullname,
                    email,
                    hashed_password
                )
            )

            user_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO settings(user_id)
                VALUES (?)
                """,
                (user_id,)
            )

            conn.commit()

            flash(
                "Registration successful. Please login.",
                "success"
            )

            return redirect(
                url_for("login")
            )

        except sqlite3.IntegrityError:

            flash(
                "Email already exists.",
                "error"
            )

            return redirect(
                url_for("register")
            )

        finally:

            conn.close()

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    # Do not show the login form again when a valid session already exists.
    if request.method == "GET" and is_logged_in():
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        ).strip()

        if not email or not password:

            flash(
                "Please enter email and password.",
                "error"
            )

            return redirect(
                url_for("login")
            )

        conn = get_connection()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE LOWER(email) = LOWER(?)
            """,
            (email,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            # Clear old session
            session.clear()

            # Create new session
            session["user_id"] = user["id"]
            session["fullname"] = user["fullname"]
            session["email"] = user["email"]

            # Keep the authenticated session stable across reloads and tabs.
            session.permanent = True

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid email or password.",
            "error"
        )

    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    user_id = session["user_id"]

    conn = get_connection()

    notes_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM notes
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()["count"]

    pdf_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM pdfs
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()["count"]

    recent_pdfs = conn.execute(
        "SELECT id, filename, original_name FROM pdfs WHERE user_id = ? ORDER BY id DESC LIMIT 5",
        (user_id,)
    ).fetchall()

    image_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM images
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()["count"]

    reminder_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM reminders
        WHERE user_id = ?
        AND completed = 0
        """,
        (user_id,)
    ).fetchone()["count"]

    conn.close()

    return render_template(
        "dashboard.html",
        notes_count=notes_count,
        pdf_count=pdf_count,
        image_count=image_count,
        reminder_count=reminder_count,
        notes=notes_count,
        pdfs=pdf_count,
        images=image_count,
        reminders=reminder_count,
        recent_pdfs=recent_pdfs
    )


# =========================================================
# NOTES
# =========================================================

@app.route("/notes")
def notes():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    saved_notes = conn.execute(
        """
        SELECT *
        FROM notes
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "notes.html",
        saved_notes=saved_notes
    )


@app.route("/create-note")
def create_note():

    if not is_logged_in():
        return redirect(url_for("login"))

    return render_template("create_note.html")


# =========================================================
# SAVE NOTE
# =========================================================

@app.route("/save-note", methods=["POST"])
def save_note():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    title = request.form.get(
        "title",
        ""
    ).strip()

    content = request.form.get(
        "content",
        ""
    ).strip()

    if not title or not content:

        flash(
            "Title and content are required.",
            "error"
        )

        return redirect(url_for("create_note"))

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO notes(
            user_id,
            title,
            content
        )
        VALUES (?, ?, ?)
        """,
        (
            session["user_id"],
            title,
            content
        )
    )

    conn.commit()
    conn.close()

    flash(
        "Note saved successfully.",
        "success"
    )

    return redirect(
        url_for("notes")
    )


# =========================================================
# EDIT NOTE
# =========================================================

@app.route("/view-note/<int:id>")
def view_note(id):

    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    note = conn.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?",
        (id, session["user_id"])
    ).fetchone()
    conn.close()

    if not note:
        flash("Note not found.", "error")
        return redirect(url_for("notes"))

    return render_template("view_note.html", note=note)

@app.route(
    "/edit-note/<int:id>",
    methods=["GET", "POST"]
)
def edit_note(id):

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    note = conn.execute(
        """
        SELECT *
        FROM notes
        WHERE id = ?
        AND user_id = ?
        """,
        (
            id,
            session["user_id"]
        )
    ).fetchone()

    if not note:

        conn.close()

        flash(
            "Note not found.",
            "error"
        )

        return redirect(
            url_for("notes")
        )

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        content = request.form.get(
            "content",
            ""
        ).strip()

        conn.execute(
            """
            UPDATE notes
            SET title = ?,
                content = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            AND user_id = ?
            """,
            (
                title,
                content,
                id,
                session["user_id"]
            )
        )

        conn.commit()
        conn.close()

        flash(
            "Note updated successfully.",
            "success"
        )

        return redirect(
            url_for("notes")
        )

    conn.close()

    return render_template("edit_note.html", note=note)


# =========================================================
# DELETE NOTE
# =========================================================

@app.route(
    "/delete-note/<int:id>",
    methods=["POST"]
)
def delete_note(id):

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM notes
        WHERE id = ?
        AND user_id = ?
        """,
        (
            id,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    flash(
        "Note deleted successfully.",
        "success"
    )

    return redirect(
        url_for("notes")
    )

# =========================================================
# PDF LIBRARY
# =========================================================

@app.route("/pdf-files")
def pdf_files():

    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    pdfs = conn.execute(
        """
        SELECT *
        FROM pdfs
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()
    conn.close()

    return render_template("pdf_files.html", pdfs=pdfs)

@app.route("/pdf-library")
def pdf_library():

    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()

    pdfs = conn.execute(
        """
        SELECT *
        FROM pdfs
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()

    conn.close()

    return render_template(
        "pdf_library.html",
        pdfs=pdfs
    )


# =========================================================
# PDF UPLOAD + TEXT EXTRACTION + AI SUMMARY
# =========================================================

@app.route("/pdf-summary", methods=["POST"])
def pdf_summary():

    if not is_logged_in():
        return redirect(url_for("login"))

    file = request.files.get("pdf")

    if not file or file.filename == "":
        flash("Please select a PDF file.", "error")
        return redirect(url_for("pdf_library"))

    if not file.filename.lower().endswith(".pdf"):
        flash("Only PDF files are allowed.", "error")
        return redirect(url_for("pdf_library"))

    original_name = file.filename

    safe_name = secure_filename(original_name)

    filename = f"{session['user_id']}_{safe_name}"

    pdf_path = os.path.join(
        app.config["PDF_FOLDER"],
        filename
    )

    try:
        os.makedirs(app.config["PDF_FOLDER"], exist_ok=True)
        file.save(pdf_path)
    except OSError:
        flash("PDF upload folder is not writable. Choose a writable project folder and try again.", "error")
        return redirect(url_for("pdf_library"))

    # -----------------------------------------------------
    # EXTRACT PDF TEXT
    # -----------------------------------------------------

    extracted_text = ""

    try:

        reader = PdfReader(pdf_path)

        for page in reader.pages:

            page_text = page.extract_text()

            if page_text:
                extracted_text += page_text + "\n"

    except Exception as e:

        flash(
            f"PDF text extraction failed: {str(e)}",
            "error"
        )

        return redirect(url_for("pdf_library"))

    if not extracted_text.strip():

        flash(
            "No readable text found in this PDF.",
            "error"
        )

        return redirect(url_for("pdf_library"))

    # -----------------------------------------------------
    # LIMIT TEXT FOR AI
    # -----------------------------------------------------

    pdf_text_for_ai = extracted_text[:30000]

    # -----------------------------------------------------
    # GROQ AI SUMMARY
    # -----------------------------------------------------

    summary = "AI summary could not be generated."

    groq_keys = [os.environ.get(name) for name in (
        "GROQ_API_KEY", "GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4",
        "GROK_API_KEY", "GROK_API_KEY_1", "GROK_API_KEY_2"
    )]

    groq_keys = [
        key for key in groq_keys
        if key
    ]

    for api_key in groq_keys:

        try:

            response = verified_ai_post(

                "https://api.groq.com/openai/v1/chat/completions",

                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },

                json={

                    "model": "openai/gpt-oss-120b",

                    "messages": [

                        {
                            "role": "system",
                            "content":
                            """
                            You are an AI PDF summarization assistant.

                            Read the provided PDF text and create a
                            clear and useful summary.

                            Return clean Markdown with these exact sections:
                            ## Main Topic
                            ## Important Keywords (bullet list)
                            ## Definitions (bold term: meaning)
                            ## Important Points (numbered list)
                            ## Important Lines / Facts (bullet list)
                            ## Conclusion
                            Use **bold** for important terms and leave blank lines between sections.
                            """
                        },

                        {
                            "role": "user",
                            "content":
                            f"""
                            Summarize this PDF:

                            {pdf_text_for_ai}
                            """
                        }

                    ],

                    "temperature": 0.2,

                    "max_completion_tokens": 2000

                },

                timeout=60,
            )

            if response.status_code == 200:

                data = response.json()

                summary = (
                    data["choices"][0]["message"]["content"]
                )

                break

        except Exception:
            continue

    # -----------------------------------------------------
    # SAVE PDF INFORMATION
    # -----------------------------------------------------

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO pdfs(
            user_id,
            filename,
            original_name
        )
        VALUES (?, ?, ?)
        """,
        (
            session["user_id"],
            filename,
            original_name
        )
    )

    conn.commit()

    pdf_id = cursor.lastrowid

    conn.close()

    # -----------------------------------------------------
    # SHOW SUMMARY
    # -----------------------------------------------------

    conn = get_connection()
    question_history = conn.execute("SELECT question, answer, created_at FROM pdf_chat_history WHERE pdf_id=? AND user_id=? ORDER BY id ASC", (pdf_id, session["user_id"])).fetchall()
    conn.close()
    return render_template(
        "pdf_summary.html",
        pdf_id=pdf_id,
        filename=filename,
        original_name=original_name,
        extracted_text=extracted_text,
        summary=summary,
        question_history=question_history
    )


@app.route("/api/pdf/<int:pdf_id>/ask", methods=["POST"])
def api_pdf_question(pdf_id):
    if not is_logged_in():
        return jsonify({"success": False, "message": "Login required"}), 401
    payload = request.get_json(silent=True) or {}
    question = payload.get("question", "").strip()
    language = payload.get("language", "auto").strip()
    if language not in ("auto", "Tamil", "English"):
        language = "auto"
    language_rule = answer_language_rule(language, question)
    language_heading = answer_heading(language, question)
    conn = get_connection()
    pdf = conn.execute("SELECT * FROM pdfs WHERE id = ? AND user_id = ?", (pdf_id, session["user_id"])).fetchone()
    conn.close()
    if not pdf:
        return jsonify({"success": False, "message": "PDF not found for this logged-in user"}), 404
    path = os.path.join(app.config["PDF_FOLDER"], pdf["filename"])
    if not os.path.exists(path):
        return jsonify({"success": False, "message": "PDF file is missing"}), 404
    try:
        pages = PdfReader(path).pages
        text = "\n\n".join(f"[Page {index + 1}]\n{page.extract_text() or ''}" for index, page in enumerate(pages))
        prompt = f"""Answer only from this PDF. {language_rule}
Return polished, readable Markdown: begin with the short heading {language_heading}; keep all headings in Tamil when Tamil is selected; use numbered steps for a process and bullet points for facts; make important terms **bold**; use *italic* sparingly and __underline__ only one critical term when useful. Keep each point on a separate readable line and never write one dense paragraph. Add a simple fenced text diagram only when a relationship, flow, or structure in the PDF genuinely needs one. Use an emoji only when it improves clarity. Do not invent facts not present in the PDF.
PDF:\n{text[:30000]}\nQuestion: {question}"""
        answer = ""
        for key_name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
            api_key = os.getenv(key_name)
            if not api_key:
                continue
            try:
                client = create_genai_client(api_key)
                result = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"), contents=prompt)
                answer = (result.text or "").strip()
                if answer:
                    break
            except Exception:
                continue
        if not answer:
            for key_name in ("GROQ_API_KEY", "GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4", "GROK_API_KEY", "GROK_API_KEY_1", "GROK_API_KEY_2"):
                key = os.getenv(key_name)
                if not key:
                    continue
                try:
                    result = verified_ai_post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json={"model":"openai/gpt-oss-120b","messages":[{"role":"system","content":f"Answer only from the supplied PDF. {language_rule} Use clean Markdown with headings, bold terms, numbered steps, bullets, and readable line breaks."},{"role":"user","content":prompt}],"temperature":0.2,"max_completion_tokens":2000}, timeout=30)
                    if result.ok:
                        answer = (result.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                        if answer:
                            break
                except Exception:
                    continue
        if not answer:
            return jsonify({"success": False, "message": provider_unavailable_response(language, question)}), 503
        conn = get_connection()
        conn.execute("INSERT INTO pdf_chat_history(pdf_id,user_id,question,answer) VALUES (?,?,?,?)", (pdf_id, session["user_id"], question, answer))
        conn.commit(); conn.close()
        return jsonify({"success": True, "answer": answer})
    except Exception as error:
        return jsonify({"success": False, "message": f"PDF AI error: {error}"}), 503


# =========================================================
# VIEW / OPEN PDF
# =========================================================

@app.route("/pdf-ai/<int:pdf_id>")
def pdf_ai_page(pdf_id):
    if not is_logged_in():
        return redirect(url_for("login"))
    conn = get_connection()
    pdf = conn.execute("SELECT * FROM pdfs WHERE id=? AND user_id=?", (pdf_id, session["user_id"])).fetchone()
    history = conn.execute("SELECT question, answer, created_at FROM pdf_chat_history WHERE pdf_id=? AND user_id=? ORDER BY id ASC", (pdf_id, session["user_id"])).fetchall()
    conn.close()
    if not pdf:
        flash("PDF not found.", "error")
        return redirect(url_for("pdf_library"))
    path = os.path.join(app.config["PDF_FOLDER"], pdf["filename"])
    if not os.path.exists(path):
        flash("PDF file is missing.", "error")
        return redirect(url_for("pdf_library"))
    try:
        text = "\n\n".join(f"[Page {i+1}]\n{p.extract_text() or ''}" for i, p in enumerate(PdfReader(path).pages))
    except Exception:
        text = ""
    return render_template("pdf_summary.html", pdf_id=pdf_id, filename=pdf["filename"], original_name=pdf["original_name"], extracted_text=text, summary="", question_history=history)

@app.route("/view-pdf/<filename>")
def view_pdf(filename):

    if not is_logged_in():
        return redirect(url_for("login"))

    safe_filename = secure_filename(filename)
    conn = get_connection()
    pdf = conn.execute("SELECT * FROM pdfs WHERE filename = ? AND user_id = ?", (safe_filename, session["user_id"])).fetchone()
    conn.close()
    if not pdf or not os.path.exists(os.path.join(app.config["PDF_FOLDER"], safe_filename)):
        flash("PDF not found or it was already deleted.", "error")
        return redirect(url_for("pdf_library"))
    from flask import send_from_directory
    return send_from_directory(app.config["PDF_FOLDER"], safe_filename, as_attachment=False, download_name=pdf["original_name"] or safe_filename)


# =========================================================
# DOWNLOAD PDF
# =========================================================

@app.route("/download-pdf/<filename>")
def download_pdf(filename):

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    pdf = conn.execute(
        """
        SELECT *
        FROM pdfs
        WHERE filename = ?
        AND user_id = ?
        """,
        (
            filename,
            session["user_id"]
        )
    ).fetchone()

    conn.close()

    if not pdf:

        flash(
            "PDF not found.",
            "error"
        )

        return redirect(
            url_for("pdf_library")
        )

    from flask import send_from_directory

    return send_from_directory(
        app.config["PDF_FOLDER"],
        filename,
        as_attachment=True,
        download_name=pdf["original_name"]
    )


# =========================================================
# DELETE PDF
# =========================================================

@app.route(
    "/delete-pdf/<int:id>",
    methods=["POST"]
)
def delete_pdf(id):

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    pdf = conn.execute(
        """
        SELECT *
        FROM pdfs
        WHERE id = ?
        AND user_id = ?
        """,
        (
            id,
            session["user_id"]
        )
    ).fetchone()

    if not pdf:

        conn.close()

        flash(
            "PDF not found.",
            "error"
        )

        return redirect(
            url_for("pdf_library")
        )

    file_path = os.path.join(
        app.config["PDF_FOLDER"],
        pdf["filename"]
    )

    if os.path.exists(file_path):

        os.remove(file_path)

    conn.execute(
        """
        DELETE FROM pdfs
        WHERE id = ?
        AND user_id = ?
        """,
        (
            id,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    flash(
        "PDF deleted successfully.",
        "success"
    )

    return redirect(
        url_for("pdf_library")
    )


# =========================================================
# RENAME PDF
# =========================================================

@app.route("/rename-pdf/<int:id>", methods=["POST"])
def rename_pdf(id):
    if not is_logged_in():
        return redirect(url_for("login"))
    new_name = (request.form.get("name") or "").strip()
    if new_name:
        conn = get_connection()
        conn.execute("UPDATE pdfs SET original_name = ? WHERE id = ? AND user_id = ?", (new_name, id, session["user_id"]))
        conn.commit()
        conn.close()
    return redirect(url_for("pdf_library"))


# =========================================================
# IMAGE LIBRARY
# =========================================================

@app.route("/image-files")
def image_files():

    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_connection()
    images = conn.execute(
        "SELECT * FROM images WHERE user_id = ? ORDER BY id DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()
    return render_template("image_files.html", images=images)

@app.route("/image-library")
def image_library():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    query = request.args.get("q", "").strip()
    selected_date = request.args.get("date", "").strip()
    period = request.args.get("period", "").strip().lower()
    images = conn.execute(
        """
        SELECT *
        FROM images
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],)
    ).fetchall()
    if query:
        normalized_query = query.lower().replace("_", " ").replace("-", " ")
        images = [
            image for image in images
            if normalized_query in (image["original_name"] or "").lower().replace("_", " ").replace("-", " ")
            or normalized_query in (image["filename"] or "").lower().replace("_", " ").replace("-", " ")
        ]
    if selected_date:
        images = [image for image in images if (image["uploaded_at"] or "").startswith(selected_date)]
    if period:
        ranges = {"morning": (6, 12), "afternoon": (12, 17), "evening": (17, 21), "night": (21, 30)}
        if period in ranges:
            start, end = ranges[period]
            images = [image for image in images if (lambda hour: (start <= hour < end) if period != "night" else (hour >= 21 or hour < 6))(int((image["uploaded_at"] or "0000-00-00 00:00") [11:13] or 0))]

    conn.close()

    return render_template(
        "image_library.html",
        images=images, search_query=query, selected_date=selected_date, selected_period=period
    )


# =========================================================
# UPLOAD IMAGE
# =========================================================

@app.route(
    "/upload-image",
    methods=["POST"]
)
def upload_image():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    file = request.files.get(
        "image"
    )

    if not file or file.filename == "":

        flash(
            "Please select an image.",
            "error"
        )

        return redirect(
            url_for("image_library")
        )

    allowed = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp"
    }

    extension = os.path.splitext(
        file.filename
    )[1].lower()

    if extension not in allowed:

        flash(
            "Invalid image format.",
            "error"
        )

        return redirect(
            url_for("image_library")
        )

    original_name = file.filename

    safe_name = secure_filename(
        original_name
    )

    filename = (
        f"{session['user_id']}_"
        f"{safe_name}"
    )

    try:
        os.makedirs(app.config["IMAGE_FOLDER"], exist_ok=True)
        file.save(os.path.join(app.config["IMAGE_FOLDER"], filename))
    except OSError:
        saved = False
        for folder in (app.config["IMAGE_FALLBACK_FOLDER"], app.config["PDF_FOLDER"], app.config["UPLOAD_FOLDER"]):
            try:
                file.stream.seek(0)
                os.makedirs(folder, exist_ok=True)
                file.save(os.path.join(folder, filename))
                saved = True
                break
            except OSError:
                continue
        if not saved:
            flash("Image upload failed. Check folder permissions and try again.", "error")
            return redirect(url_for("image_library"))

    try:
        conn = get_connection()
        conn.execute("INSERT INTO images(user_id, filename, original_name) VALUES (?, ?, ?)", (session["user_id"], filename, original_name))
        conn.commit()
        conn.close()
    except sqlite3.Error:
        try:
            conn.close()
        except Exception:
            pass
        for folder in (app.config["IMAGE_FOLDER"], app.config["IMAGE_FALLBACK_FOLDER"]):
            try: os.remove(os.path.join(folder, filename))
            except OSError: pass
        flash("Image could not be saved because the database is read-only. Grant Modify permission to ai_brain.db and restart Flask.", "error")
        return redirect(url_for("image_library"))

    flash(
        "Image uploaded successfully.",
        "success"
    )

    return redirect(
        url_for("image_library")
    )

@app.route("/view-image/<filename>")
def view_image(filename):
    if not is_logged_in():
        return redirect(url_for("login"))
    safe = secure_filename(filename)
    primary = os.path.join(app.config["IMAGE_FOLDER"], safe)
    locations = (primary, os.path.join(app.config["IMAGE_FALLBACK_FOLDER"], safe), os.path.join(app.config["PDF_FOLDER"], safe), os.path.join(app.config["UPLOAD_FOLDER"], safe))
    for location in locations:
        if os.path.exists(location):
            return send_file(location)
    flash("Image file is missing.", "error")
    return redirect(url_for("image_library"))

@app.route("/delete-image/<int:id>", methods=["POST", "GET"])
def delete_image(id):
    if not is_logged_in():
        return redirect(url_for("login"))
    conn = get_connection(); image = conn.execute("SELECT * FROM images WHERE id=? AND user_id=?", (id, session["user_id"])).fetchone()
    if image:
        conn.execute("DELETE FROM images WHERE id=? AND user_id=?", (id, session["user_id"])); conn.commit()
        for folder in (app.config["IMAGE_FOLDER"], app.config["IMAGE_FALLBACK_FOLDER"], app.config["PDF_FOLDER"], app.config["UPLOAD_FOLDER"]):
            try: os.remove(os.path.join(folder, image["filename"]))
            except OSError: pass
    conn.close(); return redirect(url_for("image_library"))

@app.route("/rename-image/<int:id>", methods=["POST"])
def rename_image(id):
    if not is_logged_in():
        return redirect(url_for("login"))
    new_name = (request.form.get("name") or "").strip()
    if new_name:
        conn = get_connection()
        conn.execute(
            "UPDATE images SET original_name = ? WHERE id = ? AND user_id = ?",
            (new_name, id, session["user_id"])
        )
        conn.commit()
        conn.close()
    return redirect(url_for("image_library"))

@app.route("/api/image/<int:image_id>/ask", methods=["POST"])
def api_image_question(image_id):
    if not is_logged_in(): return jsonify({"success":False,"message":"Login required"}), 401
    image_payload = request.get_json(silent=True) or {}
    question = image_payload.get("question", "").strip()
    language = image_payload.get("language", "auto").strip()
    if language not in ("auto", "Tamil", "English"):
        language = "auto"
    language_rule = answer_language_rule(language, question)
    language_heading = answer_heading(language, question)
    if not question: return jsonify({"success":False,"message":"Question is required"}), 400
    conn=get_connection(); image=conn.execute("SELECT * FROM images WHERE id=? AND user_id=?",(image_id,session["user_id"])).fetchone(); conn.close()
    if not image: return jsonify({"success":False,"message":"Image not found"}),404
    path=os.path.join(app.config["IMAGE_FOLDER"],image["filename"])
    if not os.path.exists(path): return jsonify({"success":False,"message":"Image file is missing"}),404
    prompt = f"""Answer the image question. {language_rule} Return polished, concise Markdown: begin with {language_heading}; keep all headings in Tamil when Tamil is selected; use 2-5 short bullets when they help; make important visible details **bold**; use *italic* sparingly and __underline__ only one key detail if useful. Include a simple fenced text diagram only when the image has a layout, flow, or relationship that benefits from it. Use emojis only when helpful. Do not invent image details.
Question: {question}"""
    gemini_keys = [os.getenv(name) for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")]
    for key in filter(None, gemini_keys):
        try:
            client = create_genai_client(key)
            result = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"), contents=[Image.open(path), prompt])
            answer = (result.text or "").strip()
            if answer:
                return jsonify({"success": True, "answer": answer})
        except Exception:
            continue

    # Vision fallback for Gemini SSL/provider failures.
    image_type = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode("ascii")
    groq_keys = [os.getenv(name) for name in ("GROQ_API_KEY", "GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROK_API_KEY", "GROK_API_KEY_1")]
    for key in filter(None, groq_keys):
        try:
            response = verified_ai_post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b"), "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{image_type};base64,{image_data}"}}]}], "temperature": 0.1, "max_tokens": 120},
                timeout=30,
            )
            if response.ok:
                answer = (response.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if answer:
                    return jsonify({"success": True, "answer": answer})
        except Exception:
            continue
    return jsonify({"success": False, "message": provider_unavailable_response(language, question)}), 503


# =========================================================
# REMINDERS
# =========================================================

@app.route("/reminders")
def reminders():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    reminders_list = conn.execute(
        """
        SELECT *
        FROM reminders
        WHERE user_id = ?
        ORDER BY reminder_date,
                 reminder_time
        """,
        (session["user_id"],)
    ).fetchall()

    settings_row = conn.execute(
        "SELECT notifications FROM settings WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return render_template(
        "remainders.html",
        reminders=reminders_list,
        reminders_enabled=(settings_row["notifications"] if settings_row else 1),
    )


@app.route("/api/reminders/test-notification", methods=["POST"])
def test_reminder_notification():
    """Lets the user verify the Windows popup and tone immediately."""
    if not is_logged_in():
        return jsonify({"success": False, "message": "Login required"}), 401
    conn = get_connection()
    settings_row = conn.execute(
        "SELECT notifications FROM settings WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()
    conn.close()
    if settings_row and not settings_row["notifications"]:
        return jsonify({"success": False, "message": "Reminder notifications are turned off in Settings."}), 409
    sent = _show_windows_reminder(
        "AI Second Brain test reminder",
        "If you can see this popup and hear a tone, reminder alerts are ready.",
    )
    if not sent:
        return jsonify({
            "success": False,
            "message": "Windows notification could not be sent. Check Windows notification settings."
        }), 503
    return jsonify({"success": True, "message": "Test popup sent with the Windows notification tone."})


# =========================================================
# SAVE REMINDER
# =========================================================

@app.route(
    "/save-reminder",
    methods=["POST"]
)
def save_reminder():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    title = request.form.get(
        "title",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    reminder_date = request.form.get(
        "reminder_date",
        ""
    ).strip()

    reminder_time = request.form.get(
        "reminder_time",
        ""
    ).strip()
    # Support both the current form names and the older date/time names.
    reminder_date = reminder_date or request.form.get("date", "").strip()
    reminder_time = reminder_time or request.form.get("time", "").strip()
    try:
        duration_days = max(1, min(365, int(request.form.get("duration_days", "1"))))
    except (TypeError, ValueError):
        duration_days = 1
    try:
        custom_duration = int(request.form.get("custom_duration_days", "0") or 0)
        if custom_duration > 0:
            duration_days = min(3650, custom_duration)
    except (TypeError, ValueError):
        pass
    repeat_enabled = 1 if request.form.get("repeat_enabled") == "1" else 0

    if not title or not reminder_date or not reminder_time:

        flash(
            "Please fill required fields.",
            "error"
        )

        return redirect(
            url_for("reminders")
        )

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO reminders(
            user_id,
            title,
            description,
            reminder_date,
            reminder_time,
            duration_days,
            repeat_enabled
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            title,
            description,
            reminder_date,
            reminder_time,
            duration_days,
            repeat_enabled
        )
    )

    conn.commit()
    conn.close()

    flash(
        "Reminder created successfully.",
        "success"
    )

    return redirect(
        url_for("reminders")
    )


# =========================================================
# DELETE REMINDER
# =========================================================

@app.route("/delete-reminder/<int:id>", methods=["GET", "POST"])
def delete_reminder(id):
    if not is_logged_in():
        return redirect(url_for("login"))
    conn = get_connection()
    conn.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (id, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Reminder deleted.", "success")
    return redirect(url_for("reminders"))


# =========================================================
# AI CHAT
# =========================================================

@app.route("/ai-chat")
def ai_chat():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()
    saved_history = conn.execute(
        """
        SELECT *
        FROM chat_history
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (session["user_id"],)
    ).fetchall()

    history_id = request.args.get("history_id", type=int)
    selected_chat = None
    if history_id:
        selected_chat = conn.execute(
            "SELECT * FROM chat_history WHERE id = ? AND user_id = ?",
            (history_id, session["user_id"]),
        ).fetchone()
    conn.close()

    # Each saved entry is one question-and-answer chat in the current schema.
    displayed_chat = [selected_chat] if selected_chat else []
    return render_template(
        "ai_chat.html",
        history=displayed_chat,
        saved_history=saved_history,
        current_chat_id=selected_chat["id"] if selected_chat else None,
    )


# =========================================================
# AI CHAT API
# =========================================================

@app.route(
    "/api/chat",
    methods=["POST"]
)
def api_chat():

    if not is_logged_in():

        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    message = data.get(
        "message",
        ""
    ).strip()
    language = data.get("language", "auto").strip()
    if language not in ("auto", "Tamil", "English"):
        language = "auto"
    language_rule = answer_language_rule(language, message)
    language_heading = answer_heading(language, message)

    if not message:

        return jsonify({
            "success": False,
            "message": "Message is required"
        }), 400

    gemini_keys = [os.getenv(name) for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3")]

    response = ""
    errors = []
    for api_key in filter(None, gemini_keys):
        try:
            client = create_genai_client(api_key, timeout_ms=20000)
            ai_result = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"), contents=(f"""Answer naturally and clearly. {language_rule}
Return a concise but complete answer by default; add detail only when the question asks for it. Begin with the short heading {language_heading}; keep all headings in Tamil when Tamil is selected; use numbered steps for procedures and bullets for facts; make key terms **bold**; use *italic* sparingly; use __underline__ for only one critical item when it helps; put each idea on its own readable line. Add a simple fenced text diagram only when a flow, comparison, hierarchy, or relationship needs one. Use emojis only when they improve clarity. Never return raw hashtags, a dense paragraph, or unsafe HTML.\n\nQuestion: {message}"""), config=genai_types.GenerateContentConfig(temperature=0.2, max_output_tokens=900))
            response = (ai_result.text or "").strip()
            if response:
                break
        except Exception as error:
            errors.append(f"Gemini unavailable: {type(error).__name__}")

    if not response:
        # Accept both common spellings: Groq (official) and legacy GROK names.
        groq_keys = [os.getenv(name) for name in (
            "GROQ_API_KEY", "GROQ_API_KEY_1", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4",
            "GROK_API_KEY", "GROK_API_KEY_1", "GROK_API_KEY_2", "GROK_API_KEY_3", "GROK_API_KEY_4"
        )]
        for groq_key in filter(None, groq_keys):
            try:
                result = verified_ai_post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}, json={"model":"openai/gpt-oss-120b","messages":[{"role":"system","content":f"Answer concisely but completely by default. {language_rule} Return polished Markdown: begin with ## Answer; use numbered steps for procedures and bullets for facts; make key terms **bold**; use *italic* sparingly; use __underline__ for only one critical item when useful; keep each idea on a separate readable line. Include a simple fenced text diagram only when a flow, comparison, hierarchy, or relationship benefits from it. Use emojis only when helpful. Never return raw hashtags, a dense paragraph, or unsafe HTML."},{"role":"user","content":message}],"temperature":0.2,"max_completion_tokens":900}, timeout=20)
                if result.ok:
                    response = (result.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                    if response: break
                errors.append(f"Groq HTTP {result.status_code}")
            except Exception as error:
                errors.append(f"Groq unavailable: {type(error).__name__}")
    if not response:
        response = provider_unavailable_response(language, message)

    # A response should still reach the user if history storage is temporarily locked.
    history_id = None
    try:
        conn = get_connection()
        cursor = conn.execute("INSERT INTO chat_history(user_id, user_message, ai_response) VALUES (?, ?, ?)", (session["user_id"], message, response))
        history_id = cursor.lastrowid
        conn.commit()
        conn.close()
    except sqlite3.Error:
        try:
            conn.close()
        except Exception:
            pass

    return jsonify({
        "success": True,
        "response": response,
        "history_id": history_id,
    })


# =========================================================
# VOICE ASSISTANT
# =========================================================

@app.route("/voice-assistant")
def voice_assistant():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    return render_template(
        "voice_assistant.html"
    )


# =========================================================
# PROFILE
# =========================================================

@app.route("/profile", methods=["GET", "POST"])
def profile():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    profile_error = None

    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()

        if not fullname or not email or "@" not in email:
            profile_error = "Enter your name and a valid email address."
        elif len(fullname) > 120 or len(email) > 254 or len(phone) > 40 or len(address) > 200:
            profile_error = "One or more profile fields are too long."
        else:
            conn = get_connection()
            try:
                conn.execute(
                    """UPDATE users
                       SET fullname = ?, email = ?, phone = ?, address = ?
                       WHERE id = ?""",
                    (fullname, email, phone, address, session["user_id"]),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                profile_error = "That email address is already used by another account."
            finally:
                conn.close()

            if profile_error is None:
                return redirect(url_for("profile", updated="1"))

    user = get_current_user()

    return render_template(
        "profile.html",
        user=user,
        profile_error=profile_error,
        profile_saved=(request.args.get("updated") == "1"),
        edit_open=(request.method == "POST"),
    )


# =========================================================
# SETTINGS
# =========================================================

@app.route("/settings")
def settings():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    conn = get_connection()

    conn.execute(
        "INSERT OR IGNORE INTO settings(user_id) VALUES (?)",
        (session["user_id"],)
    )
    conn.commit()

    settings_data = conn.execute(
        """
        SELECT *
        FROM settings
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return render_template(
        "settings.html",
        settings=settings_data
    )


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Read or save this user's appearance and reminder alert preferences."""
    if not is_logged_in():
        return jsonify({"success": False, "message": "Login required"}), 401

    user_id = session["user_id"]
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO settings(user_id) VALUES (?)", (user_id,))

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        current = conn.execute(
            "SELECT theme, theme_style, font_size, notifications FROM settings WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        theme = data.get("theme", current["theme"] or "dark")
        theme_style = data.get("theme_style", current["theme_style"] or "aurora")
        font_size = data.get("font_size", current["font_size"] or "medium")
        notifications = data.get("notifications", current["notifications"])

        if theme not in ("dark", "light"):
            conn.close()
            return jsonify({"success": False, "message": "Choose Dark or Light mode."}), 400
        if theme_style not in ("aurora", "midnight", "ocean"):
            conn.close()
            return jsonify({"success": False, "message": "Choose a supported theme style."}), 400
        if font_size not in ("small", "medium", "large"):
            conn.close()
            return jsonify({"success": False, "message": "Choose a supported font size."}), 400
        if isinstance(notifications, str):
            notifications = notifications.strip().lower() in ("1", "true", "on", "yes")
        notifications = 1 if notifications else 0

        conn.execute(
            """UPDATE settings SET theme = ?, theme_style = ?, font_size = ?, notifications = ?
               WHERE user_id = ?""",
            (theme, theme_style, font_size, notifications, user_id)
        )
        conn.commit()

    settings_data = conn.execute(
        "SELECT theme, theme_style, font_size, notifications FROM settings WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    return jsonify({
        "success": True,
        "theme": settings_data["theme"] or "dark",
        "theme_style": settings_data["theme_style"] or "aurora",
        "font_size": settings_data["font_size"] or "medium",
        "notifications": bool(settings_data["notifications"]),
    })


# =========================================================
# UNIVERSAL SEARCH
# =========================================================

@app.route(
    "/search",
    methods=["GET", "POST"]
)
def search():

    if not is_logged_in():

        return redirect(
            url_for("login")
        )

    query = ""

    if request.method == "POST":

        query = request.form.get(
            "query",
            ""
        ).strip()

    else:

        query = request.args.get(
            "query",
            ""
        ).strip()

    results = {
        "notes": [],
        "pdfs": [],
        "images": [],
        "reminders": []
    }

    if query:

        conn = get_connection()

        search_text = f"%{query}%"

        results["notes"] = conn.execute(
            """
            SELECT *
            FROM notes
            WHERE user_id = ?
            AND (
                title LIKE ?
                OR content LIKE ?
            )
            """,
            (
                session["user_id"],
                search_text,
                search_text
            )
        ).fetchall()

        results["pdfs"] = conn.execute(
            """
            SELECT *
            FROM pdfs
            WHERE user_id = ?
            AND (
                filename LIKE ?
                OR original_name LIKE ?
            )
            """,
            (
                session["user_id"],
                search_text,
                search_text
            )
        ).fetchall()

        results["images"] = conn.execute(
            """
            SELECT *
            FROM images
            WHERE user_id = ?
            AND (
                filename LIKE ?
                OR original_name LIKE ?
            )
            """,
            (
                session["user_id"],
                search_text,
                search_text
            )
        ).fetchall()

        conn.close()

    return render_template(
        "search.html",
        query=query,
        results=results
    )


# =========================================================
# USER API
# =========================================================

@app.route("/api/user")
def api_user():

    if not is_logged_in():

        return jsonify({
            "success": False
        }), 401

    user = get_current_user()

    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "fullname": user["fullname"],
            "email": user["email"],
            "profile": user["profile"]
        }
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    print()
    print("=" * 55)
    print("        AI SECOND BRAIN")
    print("        Flask Server")
    print("=" * 55)
    print("Server: http://127.0.0.1:5000")
    print("=" * 55)
    print()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=False
    )
