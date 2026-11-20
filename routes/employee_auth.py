from functools import wraps
import bcrypt

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from db import get_db_connection
from models import User

employee_auth = Blueprint("employee_auth", __name__)

def employee_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("employee_logged_in"):
            flash("Please log in to access this page.", "error")
            return redirect(url_for("employee_auth.login"))
        return f(*args, **kwargs)
    return decorated_function

def manager_login_required(f):
    @wraps(f)
    @employee_login_required
    def decorated_function(*args, **kwargs):
        if not session.get("manager_logged_in"):
            flash("Please log in to access this page.", "error")
            return redirect(url_for("employee_auth.login"))
        return f(*args, **kwargs)
    return decorated_function

@employee_auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("employee_logged_in"):
        return redirect(url_for("employee_dashboard"))

    if request.method == "POST":
        emp_user = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
    
        if not all([emp_user, password]):
            flash("Please complete all required fields.", "error")
            return render_template("auth/register.html")
    
        if len(password) < 8:
            flash("Your password must contain at least 8 characters.", "error")
            return render_template("auth/register.html")
    
        if password != confirm_password:
            flash("Your passwords do not match.", "error")
            return render_template("auth/register.html")
    
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        try:
            with get_db_connection() as conn:
                employee = conn.execute(
                    """
                    SELECT employee_id, username, first_name, last_name, email,
                    password_hash, access_role, store_id
                    FROM roadready.employee
                    WHERE username = %s
                    """,
                    (emp_user,)
                ).fetchone()

            if employee and bcrypt.checkpw(password.encode("utf-8"), employee["password_hash"].encode("utf-8")):
                session["employee_logged_in"] = True
                session["employee_id"] = employee["employee_id"]
                session["username"] = employee["username"]
                session["is_manager"] = employee["is_manager"]
                session["access_role"] = employee["access_role"]
                session["store_id"] = employee["store_id"]

                flash("You have been logged in successfully!", "success")
                return redirect(url_for("employee_dashboard"))
            else:
                flash("Invalid username or password.", "error")
                
        except Exception:
            employee_auth.logger.exception("Error during employee login.")
            flash("An error occurred during login. Please try again.", "error")