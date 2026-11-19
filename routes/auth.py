
import bcrypt

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

from flask_login import login_user, logout_user, current_user
from psycopg.errors import UniqueViolation

from db import get_db_connection
from models import User


auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please enter your username and password.", "error")
            return render_template("auth/login.html")

        try:
            with get_db_connection() as conn:
                customer = conn.execute(
                    """
                    SELECT customer_id, username, first_name,
                           last_name, email, password_hash
                    FROM roadready.customer
                    WHERE username = %s OR email = %s
                    """,
                    (username, username)
                ).fetchone()

            if customer is None:
                flash("Invalid username or password.", "error")
                return render_template("auth/login.html")

            password_valid = bcrypt.checkpw(
                password.encode("utf-8"),
                customer[5].encode("utf-8")
            )

            if not password_valid:
                flash("Invalid username or password.", "error")
                return render_template("auth/login.html")

            user = User(*customer[:5])
            login_user(user)

            flash(f"Welcome back, {user.first_name}!", "success")

            return redirect(url_for("customer.dashboard"))

        except Exception:
            auth.logger.exception("Customer login failed")
            flash("Something went wrong. Please try again.", "error")

    return render_template("auth/login.html")


@auth.route("/register", methods=["GET", "POST"])
def register():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([first_name, last_name, email, username, password]):
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
                customer = conn.execute(
                    """
                    INSERT INTO roadready.customer
                        (first_name, last_name, email, username, password_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING customer_id, username, first_name,
                              last_name, email
                    """,
                    (
                        first_name,
                        last_name,
                        email,
                        username,
                        password_hash
                    )
                ).fetchone()

            user = User(*customer)
            login_user(user)

            flash("Your account has been created successfully!", "success")
            return redirect(url_for("customer.dashboard"))

        except UniqueViolation:
            flash("That email or username is already registered.", "error")

        except Exception:
            auth.logger.exception("Customer registration failed")
            flash("Unable to create your account. Please try again.", "error")

    return render_template("auth/register.html")


@auth.route("/logout", methods=["POST"])
def logout():

    if current_user.is_authenticated:
        logout_user()
        flash("You have been logged out.", "success")

    return redirect(url_for("auth.login"))
