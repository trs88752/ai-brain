import os
import sqlite3

# Keep the database beside this project, regardless of the directory used to start Flask.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE = os.environ.get("DATABASE_PATH", os.path.join(DATA_DIR, "ai_brain.db"))


def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():

    conn = get_connection()
    cursor = conn.cursor()

    # =========================
    # USERS
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fullname TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        profile TEXT DEFAULT 'default.png',
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =========================
    # NOTES
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # =========================
    # PDF LIBRARY
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pdfs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        filename TEXT NOT NULL,
        original_name TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # =========================
    # IMAGES
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS images(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        filename TEXT NOT NULL,
        original_name TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # =========================
    # REMINDERS
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        reminder_date TEXT NOT NULL,
        reminder_time TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        duration_days INTEGER DEFAULT 1,
        repeat_enabled INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # Add reminder duration fields to databases created by older versions.
    reminder_columns = {row[1] for row in cursor.execute("PRAGMA table_info(reminders)").fetchall()}
    if "duration_days" not in reminder_columns:
        cursor.execute("ALTER TABLE reminders ADD COLUMN duration_days INTEGER DEFAULT 1")
    if "repeat_enabled" not in reminder_columns:
        cursor.execute("ALTER TABLE reminders ADD COLUMN repeat_enabled INTEGER DEFAULT 0")

    # One record per reminder/day prevents the Windows alert scheduler from
    # showing the same reminder repeatedly during a single scheduled minute.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminder_notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reminder_id INTEGER NOT NULL,
        alert_key TEXT NOT NULL UNIQUE,
        shown_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(reminder_id) REFERENCES reminders(id)
    )
    """)

    # =========================
    # AI CHAT HISTORY
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_message TEXT NOT NULL,
        ai_response TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # =========================
    # AI MEMORY
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_memory(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        memory TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # =========================
    # SETTINGS
    # =========================

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        theme TEXT DEFAULT 'dark',
        theme_style TEXT DEFAULT 'aurora',
        font_size TEXT DEFAULT 'medium',
        notifications INTEGER DEFAULT 1,
        voice_enabled INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # =========================
    # DATABASE MIGRATION
    # =========================

    cursor.execute("PRAGMA table_info(users)")
    user_columns = [
        column[1]
        for column in cursor.fetchall()
    ]

    if "fullname" not in user_columns:
        cursor.execute("""
        ALTER TABLE users
        ADD COLUMN fullname TEXT NOT NULL DEFAULT ''
        """)

    if "profile" not in user_columns:
        cursor.execute("""
        ALTER TABLE users
        ADD COLUMN profile TEXT DEFAULT 'default.png'
        """)

    if "created_at" not in user_columns:
        cursor.execute("""
        ALTER TABLE users
        ADD COLUMN created_at TIMESTAMP
        DEFAULT CURRENT_TIMESTAMP
        """)

    if "phone" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")

    if "address" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN address TEXT DEFAULT ''")

    # Settings used to be display-only, so migrate their placeholder light
    # value to the app's existing dark appearance the first time preferences
    # are introduced. After this migration, user-selected values are preserved.
    settings_columns = {
        column[1]
        for column in cursor.execute("PRAGMA table_info(settings)").fetchall()
    }
    if "theme" not in settings_columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN theme TEXT DEFAULT 'dark'")
    if "theme_style" not in settings_columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN theme_style TEXT DEFAULT 'aurora'")
        cursor.execute("UPDATE settings SET theme = 'dark' WHERE theme = 'light' OR theme IS NULL")
    if "font_size" not in settings_columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN font_size TEXT DEFAULT 'medium'")
    if "notifications" not in settings_columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN notifications INTEGER DEFAULT 1")
    if "voice_enabled" not in settings_columns:
        cursor.execute("ALTER TABLE settings ADD COLUMN voice_enabled INTEGER DEFAULT 1")

    conn.commit()
    conn.close()

    print("Database created successfully.")


if __name__ == "__main__":
    create_database()
