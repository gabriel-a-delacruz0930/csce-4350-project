
from flask import Blueprint, render_template, abort
from flask_login import login_required

from db import get_db_connection


product_details = Blueprint("product_details", __name__)


@product_details.route("/parts/<int:part_id>")
@login_required
def view_product(part_id):

    with get_db_connection() as conn:

        # Retrieve the main product information and its available SKUs
        product = conn.execute(
            """
            SELECT
                p.part_id,
                p.part_number,
                p.part_name,
                p.description,
                p.brand,
                c.category_name,
                p.warranty_months,
                sku.sku_id,
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

            WHERE p.part_id = %s
              AND sku.is_active = TRUE

            GROUP BY
                p.part_id,
                p.part_number,
                p.part_name,
                p.description,
                p.brand,
                c.category_name,
                p.warranty_months,
                sku.sku_id,
                sku.condition,
                sku.unit_price,
                sku.core_charge

            ORDER BY sku.unit_price
            """,
            (part_id,)
        ).fetchall()

        if not product:
            abort(404)

        # Retrieve compatible vehicle models
        compatible_vehicles = conn.execute(
            """
            SELECT
                vm.make,
                vm.model,
                vm.model_year,
                vm.engine

            FROM roadready.part_fitment pf

            JOIN roadready.vehicle_model vm
                ON pf.model_id = vm.model_id

            WHERE pf.part_id = %s

            ORDER BY vm.make, vm.model_year DESC
            """,
            (part_id,)
        ).fetchall()

    return render_template(
        "customer/product_details.html",
        products=product,
        compatible_vehicles=compatible_vehicles
    )
