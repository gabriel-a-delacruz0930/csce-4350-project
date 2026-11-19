
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from psycopg.errors import UniqueViolation

from db import get_db_connection

vehicles = Blueprint("vehicles", __name__)


@vehicles.route("/vehicles", methods=["GET", "POST"])
@login_required
def my_vehicles():

    if request.method == "POST":
        model_id = request.form.get("model_id", "").strip()
        vin = request.form.get("vin", "").strip().upper()
        nickname = request.form.get("nickname", "").strip()

        if not model_id.isdigit():
            flash("Please select a valid vehicle.", "error")
            return redirect(url_for("vehicles.my_vehicles"))

        if vin and not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
            flash("Please enter a valid 17-character VIN.", "error")
            return redirect(url_for("vehicles.my_vehicles"))

        if len(nickname) > 30:
            flash("The nickname cannot exceed 30 characters.", "error")
            return redirect(url_for("vehicles.my_vehicles"))

        try:
            with get_db_connection() as conn:
                model_exists = conn.execute(
                    """
                    SELECT model_id
                    FROM roadready.vehicle_model
                    WHERE model_id = %s
                    """,
                    (int(model_id),)
                ).fetchone()

                if model_exists is None:
                    flash("The selected vehicle could not be found.", "error")
                    return redirect(url_for("vehicles.my_vehicles"))

                conn.execute(
                    """
                    INSERT INTO roadready.customer_vehicle
                        (customer_id, model_id, vin, nickname)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        int(current_user.id),
                        int(model_id),
                        vin or None,
                        nickname or None
                    )
                )

            flash("Your vehicle was added successfully!", "success")
            return redirect(url_for("vehicles.my_vehicles"))

        except UniqueViolation:
            flash("That VIN is already registered.", "error")
        except Exception:
            vehicles.logger.exception("Adding customer vehicle failed")
            flash("Unable to add your vehicle. Please try again.", "error")

    with get_db_connection() as conn:
        vehicle_models = conn.execute(
            """
            SELECT model_id, make, model, model_year, engine
            FROM roadready.vehicle_model
            ORDER BY make, model, model_year DESC
            """
        ).fetchall()

        customer_vehicles = conn.execute(
            """
            SELECT
                cv.vehicle_id,
                cv.vin,
                cv.nickname,
                vm.make,
                vm.model,
                vm.model_year,
                vm.engine
            FROM roadready.customer_vehicle cv
            JOIN roadready.vehicle_model vm
                ON cv.model_id = vm.model_id
            WHERE cv.customer_id = %s
            ORDER BY vm.model_year DESC
            """,
            (int(current_user.id),)
        ).fetchall()

    return render_template(
        "customer/vehicles.html",
        vehicle_models=vehicle_models,
        customer_vehicles=customer_vehicles
    )
