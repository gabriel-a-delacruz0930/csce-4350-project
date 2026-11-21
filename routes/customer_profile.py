from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from db import get_db_connection

customer_profile = Blueprint("customer_profile", __name__)

def customer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("customer_logged_in"):
            flash("Please log in to access this page.", "error")
            return redirect(url_for("customer_profile.login"))
        return f(*args, **kwargs)
    return decorated_function

@customer_profile.route("/profile", methods=["GET", "POST"])
@customer_login_required
def profile():
    customer_id = session.get("customer_id")
    
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()

        if not first_name or not last_name or not email or not phone:
            flash("All fields are required.", "error")
            return redirect(url_for("customer_profile.profile"))
        else:
            try:
                with get_db_connection() as conn:
                    conn.execute(
                        """
                        UPDATE roadready.customer
                        SET first_name = %s,
                            last_name = %s,
                            email = %s,
                            phone = %s
                        WHERE customer_id = %s
                        """,
                        (first_name, last_name, email, phone, customer_id),
                    )
                    conn.commit()
                flash("Profile updated.", "success")
                return redirect(url_for("customer_profile.profile"))
            except Exception:
                flash("Could not update profile right now.", "error")
                
    with get_db_connection() as conn:
        customer = conn.execute(
            """
            SELECT customer_id, first_name, last_name, email, phone
            FROM roadready.customer
            WHERE customer_id = %s
            """,
            (customer_id,),
        ).fetchone()

    return render_template("customer/profile.html", customer=customer)