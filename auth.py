from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
import os

auth = Blueprint("auth", __name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DATABASE = os.environ.get("DATABASE_PATH", os.path.join(DATA_DIR, "ai_brain.db"))


# -----------------------------
# Database Connection
# -----------------------------

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# -----------------------------
# Login Required
# -----------------------------

def login_required(view):

    @wraps(view)
    def wrapped_view(*args, **kwargs):

        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("auth.login"))

        return view(*args, **kwargs)

    return wrapped_view


# -----------------------------
# Register
# -----------------------------

@auth.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not fullname or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("auth.register"))

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        )

        existing_user = cursor.fetchone()

        if existing_user:
            conn.close()
            flash("Email already exists!", "danger")
            return redirect(url_for("auth.register"))

        hashed_password = generate_password_hash(password)

        cursor.execute(
            """
            INSERT INTO users(fullname, email, password)
            VALUES (?, ?, ?)
            """,
            (fullname, email, hashed_password)
        )

        conn.commit()
        conn.close()

        flash("Registration Successful! Please Login.", "success")

        return redirect(url_for("auth.login"))

    return render_template("register.html")


# -----------------------------
# Login
# -----------------------------

@auth.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter email and password.", "danger")
            return render_template("login.html")

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        )

        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session.clear()

            session["user_id"] = user["id"]
            session["fullname"] = user["fullname"]
            session["email"] = user["email"]

            flash("Login Successful!", "success")

            return redirect(url_for("dashboard"))

        flash("Invalid Email or Password!", "danger")

    return render_template("login.html")


# -----------------------------
# Logout
# -----------------------------

@auth.route("/logout")
def logout():

    session.clear()

    flash("Logged Out Successfully.", "info")

    return redirect(url_for("auth.login"))