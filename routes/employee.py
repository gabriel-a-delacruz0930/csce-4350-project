from flask import Blueprint, render_template, session
from routes.employee_auth import employee_login_required


employee = Blueprint("employee", __name__)


@employee.route("/employee/dashboard")
@employee_login_required
def dashboard():
    return render_template(
        "employee/dashboard.html",
        employee=session
    )