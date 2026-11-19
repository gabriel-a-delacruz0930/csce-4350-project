
from flask import Blueprint, render_template
from flask_login import login_required, current_user


customer = Blueprint("customer", __name__)


@customer.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "customer/dashboard.html",
        user=current_user
    )
