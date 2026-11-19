
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from db import get_db_connection


parts = Blueprint("parts", __name__)


@parts.route("/parts")
@login_required
def browse_parts():

    search_query = request.args.get("q", "").strip()
    category_id = request.args.get("category", "").strip()
    selected_vehicle_id = request.args.get("vehicle", "").strip()

    # Load the customer's saved vehicles
    with get_db_connection() as conn:

        customer_vehicles = conn.execute(
            """
            SELECT
                cv.vehicle_id,
                cv.model_id,
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

        categories = conn.execute(
            """
            SELECT category_id, category_name
            FROM roadready.category
            ORDER BY category_name
            """
        ).fetchall()

        # Only apply a vehicle filter if it belongs to this customer
        selected_model_id = None

        if selected_vehicle_id.isdigit():
            for vehicle in customer_vehicles:
                if vehicle[0] == int(selected_vehicle_id):
                    selected_model_id = vehicle[1]
                    break

        # Build the product search
        conditions = ["sku.is_active = TRUE"]
        parameters = []

        if search_query:
            conditions.append(
                """
                (
                    p.part_name ILIKE %s
                    OR p.part_number ILIKE %s
                    OR p.brand ILIKE %s
                )
                """
            )

            search_pattern = f"%{search_query}%"

            parameters.extend([
                search_pattern,
                search_pattern,
                search_pattern
            ])

        if category_id.isdigit():
            conditions.append("p.category_id = %s")
            parameters.append(int(category_id))
        else:
            category_id = ""

        if selected_model_id is not None:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM roadready.part_fitment pf
                    WHERE pf.part_id = p.part_id
                    AND pf.model_id = %s
                )
                """
            )
            parameters.append(selected_model_id)
        else:
            selected_vehicle_id = ""

        where_clause = " AND ".join(conditions)

        products = conn.execute(
            f"""
            SELECT
                sku.sku_id,
                p.part_id,
                p.part_number,
                p.part_name,
                p.description,
                p.brand,
                c.category_name,
                p.warranty_months,
                sku.condition,
                sku.unit_price,
                sku.core_charge,
                COALESCE(SUM(inv.qty_on_hand), 0) AS total_stock

            FROM roadready.part p

            JOIN roadready.category c
                ON p.category_id = c.category_id

            JOIN roadready.part_sku sku
                ON p.part_id = sku.part_id

            LEFT JOIN roadready.inventory inv
                ON sku.sku_id = inv.sku_id

            WHERE {where_clause}

            GROUP BY
                sku.sku_id,
                p.part_id,
                p.part_number,
                p.part_name,
                p.description,
                p.brand,
                c.category_name,
                p.warranty_months,
                sku.condition,
                sku.unit_price,
                sku.core_charge

            ORDER BY p.part_name, sku.unit_price
            """,
            parameters
        ).fetchall()

    return render_template(
        "customer/parts.html",
        products=products,
        categories=categories,
        customer_vehicles=customer_vehicles,
        search_query=search_query,
        selected_category=category_id,
        selected_vehicle_id=selected_vehicle_id
    )
