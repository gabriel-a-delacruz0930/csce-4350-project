from functools import wraps
import bcrypt

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from db import get_db_connection

employee_auth = Blueprint("employee_auth", __name__)

def employee_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("employee_logged_in"):
            flash("Please log in to access this page.", "error")
            return redirect(url_for("employee.dashboard"))
        return f(*args, **kwargs)
    return decorated_function


def manager_login_required(f):
    @wraps(f)
    @employee_login_required
    def decorated_function(*args, **kwargs):
        if not session.get("manager_logged_in"):
            flash("Please log in to access this page.", "error")
            return redirect(url_for("employee.dashboard"))
        return f(*args, **kwargs)
    return decorated_function


@employee_auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("employee_logged_in"):
        return redirect(url_for("employee.dashboard"))

    if request.method == "POST":
        emp_id_raw = request.form.get("employee_id", "").strip()
        password = request.form.get("password", "")

        if not emp_id_raw or not password:
            flash("Please enter both your Employee ID and password.", "error")
            return render_template("employee/login.html")

        try:
            emp_id = int(emp_id_raw)
        except ValueError:
            flash("Employee ID must be a valid number.", "error")
            return render_template("employee/login.html")

        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    """
                    SELECT employee_id, username, first_name, last_name, email,
                           password_hash, access_role, store_id
                    FROM roadready.employee
                    WHERE employee_id = %s
                    """,
                    (emp_id,),
                ).fetchone()

            if row:
                (
                    employee_id,
                    username,
                    first_name,
                    last_name,
                    email,
                    password_hash,
                    access_role,
                    store_id,
                ) = row

                if password_hash and bcrypt.checkpw(
                    password.encode("utf-8"), password_hash.encode("utf-8")
                ):
                    is_mgr = str(access_role).upper() in ("MANAGER", "ADMIN")
                    session["employee_logged_in"] = True
                    session["employee_id"] = employee_id
                    session["username"] = username
                    session["is_manager"] = is_mgr
                    session["manager_logged_in"] = is_mgr
                    session["access_role"] = access_role
                    session["store_id"] = store_id

                    flash("You have been logged in successfully!", "success")
                    return redirect(url_for("employee.dashboard"))

            flash("Invalid Employee ID or password.", "error")

        except Exception:
            employee_auth.logger.exception("Error during employee login.")
            flash("An error occurred during login. Please try again.", "error")

    return render_template("employee/login.html")


@employee_auth.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("employee.dashboard"))