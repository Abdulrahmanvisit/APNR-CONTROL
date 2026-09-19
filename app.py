import csv
import io
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from auth_security import hash_password, verify_password
from werkzeug.utils import secure_filename

from anpr import process_license_plate
from alerts import create_alert
from access_control import decide_access, normalize_plate_number
from main import create_connection, initialize_schema
from rbac import has_permission

load_dotenv()

app = Flask(__name__)

_secret_key = os.getenv("FLASK_SECRET_KEY")
if not _secret_key:
    logging.warning(
        "FLASK_SECRET_KEY is not set. Sessions will not survive a server restart. "
        "Set FLASK_SECRET_KEY in your environment or .env file "
        "(generate with: openssl rand -hex 32)."
    )

app.config.update(
    SECRET_KEY=_secret_key or os.urandom(32),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    UPLOAD_FOLDER=os.path.join(app.root_path, "static", "uploads"),
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("FLASK_COOKIE_SECURE", "0") == "1",
    SESSION_REFRESH_EACH_REQUEST=True,
    PREFERRED_URL_SCHEME="https" if os.getenv("FLASK_COOKIE_SECURE", "0") == "1" else "http",
)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per hour", "50 per minute"],
)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
WATCHLIST_CATEGORIES = {"Allowed", "Blocked", "Visitor"}
EVENT_TYPES = {"Entry", "Exit"}


def login_required(view):
    """Require an authenticated session before entering a protected view."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Require an authenticated administrator for state-changing views."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "Admin":
            flash("Administrator privileges are required for this action.", "error")
            return redirect(url_for("watchlist"))
        return view(*args, **kwargs)

    return wrapped


def permission_required(permission):
    """Protect a route using the centralized role-permission policy."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not has_permission(session.get("role"), permission):
                flash("Your account does not have permission for this action.", "error")
                fallback = "watchlist" if permission.startswith("watchlist:") else "operator_dashboard"
                return redirect(url_for(fallback))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def has_allowed_extension(filename):
    """Return whether a filename has an allowed, case-insensitive extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def local_redirect_target(target):
    """Return a local redirect target, preventing external redirect abuse."""
    return target if target and target.startswith("/") and not target.startswith("//") else url_for("dashboard")


def role_dashboard_url(role):
    """Return the dedicated workspace URL for an authenticated role."""
    endpoint = {
        "Admin": "admin_dashboard",
        "Supervisor": "supervisor_dashboard",
        "Auditor": "auditor_dashboard",
    }.get(role, "operator_dashboard")
    return url_for(endpoint)


def close_database(connection, cursor=None):
    """Close a cursor and connection without masking the original exception."""
    if cursor is not None:
        try:
            cursor.close()
        except mysql.connector.Error:
            pass
    if connection is not None:
        try:
            if connection.is_connected():
                connection.close()
        except mysql.connector.Error:
            pass


def query_rows(query, params=()):
    """Run a read-only parameterized query and always release DB resources."""
    connection = cursor = None
    try:
        connection = create_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params)
        return cursor.fetchall()
    except mysql.connector.Error:
        return []
    finally:
        close_database(connection, cursor)


@app.before_request
def initialize_application_schema():
    """Ensure the application tables exist without creating predictable accounts."""
    if not app.config.get("USERS_SEEDED"):
        initialize_schema()
        app.config["USERS_SEEDED"] = True


@app.after_request
def disable_auth_page_caching(response):
    """Prevent browsers from retaining stale login or role-workspace markup."""
    if request.endpoint in {"login", "logout", "dashboard", "admin_dashboard", "operator_dashboard", "manage_users", "reset_password"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/")
def home():
    """Render the public landing page."""
    if session.get("user"):
        return redirect(role_dashboard_url(session.get("role")))
    return render_template("index.html")


@app.route("/dashboard")
@login_required
def dashboard():
    """Redirect the legacy dashboard URL to the role-specific workspace."""
    return redirect(role_dashboard_url(session.get("role")))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Render the administrator workspace."""
    return render_template("admin_dashboard.html")


@app.route("/operator/dashboard")
@login_required
def operator_dashboard():
    """Render the operator workspace."""
    if session.get("role") != "Operator":
        return redirect(role_dashboard_url(session.get("role")))
    return render_template("operator_dashboard.html")


@app.route("/supervisor/dashboard")
@login_required
def supervisor_dashboard():
    """Render the supervisor workspace."""
    if session.get("role") != "Supervisor":
        return redirect(role_dashboard_url(session.get("role")))
    return render_template("supervisor_dashboard.html")


@app.route("/auditor/dashboard")
@login_required
def auditor_dashboard():
    """Render the read-only auditor workspace."""
    if session.get("role") != "Auditor":
        return redirect(role_dashboard_url(session.get("role")))
    return render_template("auditor_dashboard.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    """Authenticate a user against the users table."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        rows = query_rows(
            "SELECT username, password, role, is_active, is_first_login, failed_attempts, locked_until "
            "FROM users WHERE username = %s LIMIT 1",
            (username,),
        )
        user = rows[0] if rows else None
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if user and (not user["is_active"] or (user["locked_until"] and user["locked_until"] > now)):
            flash("This account is temporarily unavailable. Contact an administrator.", "error")
            return render_template("login.html")
        valid_password, needs_rehash = verify_password(user["password"], password) if user else (False, False)
        if valid_password:
            connection = cursor = None
            try:
                connection = create_connection()
                cursor = connection.cursor()
                if needs_rehash:
                    cursor.execute(
                        "UPDATE users SET password = %s, failed_attempts = 0, locked_until = NULL, "
                        "last_login_at = CURRENT_TIMESTAMP WHERE username = %s",
                        (hash_password(password), user["username"]),
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = CURRENT_TIMESTAMP "
                        "WHERE username = %s",
                        (user["username"],),
                    )
                connection.commit()
            finally:
                close_database(connection, cursor)
            session.clear()
            session.permanent = True
            session["user"] = user["username"]
            session["role"] = user["role"]
            session["is_first_login"] = bool(user["is_first_login"])
            target = request.args.get("next")
            if session["is_first_login"]:
                return redirect(url_for("reset_password"))
            return redirect(target if target and target.startswith("/") and not target.startswith("//") else role_dashboard_url(user["role"]))
        if user:
            connection = cursor = None
            try:
                connection = create_connection()
                cursor = connection.cursor()
                attempts = int(user["failed_attempts"] or 0) + 1
                locked_until = now + timedelta(minutes=15) if attempts >= 5 else None
                cursor.execute(
                    "UPDATE users SET failed_attempts = %s, locked_until = %s WHERE username = %s",
                    (attempts, locked_until, username),
                )
                connection.commit()
            finally:
                close_database(connection, cursor)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/account/reset-password", methods=["GET", "POST"])
@login_required
def reset_password():
    """Force a newly provisioned user to replace the temporary password."""
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")
        if len(password) < 12 or password != confirmation:
            flash("Passwords must match and contain at least 12 characters.", "error")
            return render_template("reset_password.html")
        connection = cursor = None
        try:
            connection = create_connection()
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE users SET password = %s, is_first_login = FALSE WHERE username = %s",
                (hash_password(password), session["user"]),
            )
            connection.commit()
            session["is_first_login"] = False
            flash("Your password was updated successfully.", "success")
            return redirect(role_dashboard_url(session.get("role")))
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            flash("The password could not be updated.", "error")
        finally:
            close_database(connection, cursor)
    return render_template("reset_password.html")


@app.route("/logout")
def logout():
    """Clear the current authenticated session."""
    session.clear()
    return redirect(url_for("home"))


@app.route("/scan", methods=["GET", "POST"])
@login_required
def scan():
    """Validate an uploaded image, run OCR, and record the detection."""
    if request.method == "GET":
        return render_template("scan.html")

    upload = request.files.get("plate_image")
    if upload is None or not upload.filename:
        flash("Select an image to scan.", "error")
        return redirect(url_for("scan"))
    if not has_allowed_extension(upload.filename):
        flash("Only JPG, JPEG, PNG, and WEBP images are accepted.", "error")
        return redirect(url_for("scan"))

    safe_name = secure_filename(upload.filename)
    if not safe_name:
        flash("The uploaded filename is invalid.", "error")
        return redirect(url_for("scan"))
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"
    image_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_name)
    try:
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        upload.save(image_path)
    except OSError:
        app.logger.exception("Unable to save uploaded image")
        flash("The image could not be saved. Check the upload directory permissions.", "error")
        return redirect(url_for("scan"))

    result = process_license_plate(image_path)
    plate_number = normalize_plate_number(result["plate_number"])
    event_type = request.form.get("event_type", "Entry")
    if event_type not in EVENT_TYPES:
        event_type = "Entry"
    category = None
    if plate_number not in {"", "UNREADABLE", "OCRERROR"}:
        matches = query_rows(
            "SELECT category FROM watchlist WHERE plate_number = %s LIMIT 1",
            (plate_number,),
        )
        if matches:
            category = matches[0]["category"]
    decision = decide_access(
        plate_number,
        category,
        result["confidence"],
    )
    status = decision.status
    alert = create_alert(status, decision.plate_number)

    connection = cursor = None
    try:
        connection = create_connection()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO detection_logs "
            "(plate_number, confidence, status, event_type, image_path, alert_generated, operator_username) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                decision.plate_number,
                result["confidence"],
                status,
                event_type,
                os.path.relpath(image_path, app.root_path),
                alert.audible,
                session.get("user"),
            ),
        )
        connection.commit()
    except mysql.connector.Error:
        if connection is not None:
            try:
                connection.rollback()
            except mysql.connector.Error:
                app.logger.exception("Unable to roll back detection log transaction")
        flash("The scan completed, but its log could not be saved.", "error")
    finally:
        close_database(connection, cursor)

    return render_template("scan.html", result=result, status=status, alert=alert, event_type=event_type)


@app.route("/watchlist")
@login_required
def watchlist():
    """Display the watchlist for authenticated users."""
    items = query_rows(
        "SELECT plate_number, category AS status, notes, created_at FROM watchlist ORDER BY created_at DESC"
    )
    edit_plate = request.args.get("edit", "")
    edit_item = next((item for item in items if item["plate_number"] == edit_plate), None)
    return render_template("watchlist.html", watchlist_items=items, edit_item=edit_item)


@app.route("/watchlist/add", methods=["POST"])
@permission_required("watchlist:write")
def add_watchlist():
    """Add a validated watchlist entry for administrators."""
    plate_number = "".join(ch for ch in request.form.get("plate_number", "").upper() if ch.isalnum())
    category = request.form.get("status", "Visitor")
    notes = request.form.get("notes", "").strip()[:500]
    if not plate_number or category not in WATCHLIST_CATEGORIES:
        flash("Provide a valid plate number and category.", "error")
        return redirect(url_for("watchlist"))

    connection = cursor = None
    try:
        connection = create_connection()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO watchlist (plate_number, category, notes) VALUES (%s, %s, %s)",
            (plate_number, category, notes),
        )
        connection.commit()
        flash(f"Plate {plate_number} added to the watchlist.", "success")
    except mysql.connector.IntegrityError:
        if connection is not None:
            connection.rollback()
        flash(f"Plate {plate_number} is already registered.", "error")
    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        flash("The watchlist entry could not be saved.", "error")
    finally:
        close_database(connection, cursor)
    return redirect(url_for("watchlist"))


@app.route("/watchlist/<plate_number>/edit", methods=["POST"])
@permission_required("watchlist:write")
def edit_watchlist(plate_number):
    """Update the category and notes for an existing watchlist entry."""
    normalized_plate = normalize_plate_number(plate_number)
    category = request.form.get("status", "Visitor")
    notes = request.form.get("notes", "").strip()[:500]
    if not normalized_plate or category not in WATCHLIST_CATEGORIES:
        flash("Provide a valid category for this plate.", "error")
        return redirect(url_for("watchlist"))
    connection = cursor = None
    try:
        connection = create_connection()
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE watchlist SET category = %s, notes = %s WHERE plate_number = %s",
            (category, notes, normalized_plate),
        )
        if cursor.rowcount == 0:
            flash("That watchlist entry could not be found.", "error")
        else:
            connection.commit()
            flash(f"Plate {normalized_plate} was updated.", "success")
    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        flash("The watchlist entry could not be updated.", "error")
    finally:
        close_database(connection, cursor)
    return redirect(url_for("watchlist"))


@app.route("/watchlist/<plate_number>/delete", methods=["POST"])
@permission_required("watchlist:write")
def delete_watchlist(plate_number):
    """Delete an existing watchlist entry for administrators."""
    normalized_plate = normalize_plate_number(plate_number)
    connection = cursor = None
    try:
        connection = create_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM watchlist WHERE plate_number = %s", (normalized_plate,))
        if cursor.rowcount == 0:
            flash("That watchlist entry could not be found.", "error")
        else:
            connection.commit()
            flash(f"Plate {normalized_plate} was removed from the watchlist.", "success")
    except mysql.connector.Error:
        if connection is not None:
            connection.rollback()
        flash("The watchlist entry could not be removed.", "error")
    finally:
        close_database(connection, cursor)
    return redirect(url_for("watchlist"))


@app.route("/admin/users", methods=["GET", "POST"])
@permission_required("users:write")
def manage_users():
    """Allow an existing administrator to provision operator accounts."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "Operator")
        if not username or len(username) > 80 or role not in {"Admin", "Supervisor", "Operator", "Auditor"}:
            flash("Provide a valid username and role.", "error")
            return redirect(url_for("manage_users"))
        if len(password) < 12:
            flash("Use a password of at least 12 characters.", "error")
            return redirect(url_for("manage_users"))
        connection = cursor = None
        try:
            connection = create_connection()
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO users (username, password, role, is_first_login) VALUES (%s, %s, %s, TRUE)",
                (username, hash_password(password), role),
            )
            connection.commit()
            flash(f"Account {username} was created.", "success")
        except mysql.connector.IntegrityError:
            if connection is not None:
                connection.rollback()
            flash("That username is already in use.", "error")
        except mysql.connector.Error:
            if connection is not None:
                connection.rollback()
            flash("The account could not be created.", "error")
        finally:
            close_database(connection, cursor)
        return redirect(url_for("manage_users"))
    accounts = query_rows("SELECT username, role FROM users ORDER BY username")
    return render_template("admin_users.html", accounts=accounts)


@app.route("/logs")
@login_required
def logs():
    """Display persisted detection logs."""
    scan_logs = query_rows(
        "SELECT plate_number, confidence, status, event_type, scanned_at AS timestamp "
        "FROM detection_logs ORDER BY scanned_at DESC"
    )
    return render_template("logs.html", scan_logs=scan_logs, total_records=len(scan_logs))


@app.route("/logs/export")
@login_required
def export_logs():
    """Export persisted detection logs as a CSV download."""
    rows = query_rows(
        "SELECT plate_number, confidence, status, event_type, scanned_at FROM detection_logs ORDER BY scanned_at DESC"
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(("Plate Number", "Confidence", "Status", "Event Type", "Scanned At"))
    for row in rows:
        writer.writerow((row["plate_number"], row["confidence"], row["status"], row["event_type"], row["scanned_at"]))
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="detection_logs.csv",
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
