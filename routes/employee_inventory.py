from flask import Blueprint, render_template, request, redirect, url_for, flash

from db import get_db_connection
from routes.employee_auth import employee_login_required, manager_login_required

employee_inventory = Blueprint("employee_inventory", __name__)


@employee_inventory.route("/inventory")
@employee_login_required
def browse_inventory():
    search_query = request.args.get("q", "").strip()
    category_id = request.args.get("category", "").strip()
    selected_vehicle_id = request.args.get("vehicle", "").strip()
    selected_store_id = request.args.get("store", "").strip()

    with get_db_connection() as conn:
        stores = conn.execute(
            """
            SELECT store_id, store_name
            FROM roadready.store
            WHERE is_active = TRUE
            ORDER BY store_name
            """
        ).fetchall()

        categories = conn.execute(
            """
            SELECT category_id, category_name
            FROM roadready.category
            ORDER BY category_name
            """
        ).fetchall()

        valid_store_id = None

        if selected_store_id.isdigit():
            for store in stores:
                if store[0] == int(selected_store_id):
                    valid_store_id = store[0]
                    break

        if valid_store_id is None and stores:
            valid_store_id = stores[0][0]
            selected_store_id = str(valid_store_id)

        conditions = ["sku.is_active = TRUE"]
        parameters = []

        if search_query:
            conditions.append(
                """
                (
                    p.part_name ILIKE %s
                    OR p.part_number ILIKE %s
                    OR COALESCE(p.brand, '') ILIKE %s
                    OR COALESCE(inv.bin_location, '') ILIKE %s
                )
                """
            )
            parameters.extend([f"%{search_query}%"] * 4)

        if category_id.isdigit():
            conditions.append("p.category_id = %s")
            parameters.append(int(category_id))

        if selected_vehicle_id.isdigit():
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
            parameters.append(int(selected_vehicle_id))

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                sku.sku_id,
                p.part_id,
                p.part_number,
                p.part_name,
                sku.condition,
                sku.unit_price,
                sku.core_charge,
                COALESCE(inv.qty_on_hand, 0) AS qty_on_hand,
                COALESCE(inv.reorder_level, 5) AS reorder_level,
                COALESCE(inv.bin_location, '') AS bin_location,
                c.category_name
            FROM roadready.part_sku sku
            JOIN roadready.part p
                ON sku.part_id = p.part_id
            JOIN roadready.category c
                ON p.category_id = c.category_id
            LEFT JOIN roadready.inventory inv
                ON inv.sku_id = sku.sku_id
                AND inv.store_id = %s
            WHERE {where_clause}
            ORDER BY p.part_name, sku.condition
        """

        products = conn.execute(query, (valid_store_id, *parameters)).fetchall()

    return render_template(
        "employee/inventory.html",
        products=products,
        stores=stores,
        categories=categories,
        search_query=search_query,
        selected_category=category_id,
        selected_vehicle=selected_vehicle_id,
        selected_store_id=selected_store_id,
        valid_store_id=valid_store_id,
    )


@employee_inventory.route("/inventory", methods=["POST"])
@employee_login_required
def update_inventory():
    store_id = request.form.get("store_id", type=int)
    sku_id = request.form.get("sku_id", type=int)
    bin_location = request.form.get("bin_location", "").strip() or None

    try:
        current_quantity = int(str(request.form.get("current_quantity", 0)).strip())
        reorder_level = int(str(request.form.get("reorder_level", 0)).strip())
    except (ValueError, TypeError):
        flash("Invalid quantity values provided.", "error")
        return redirect(url_for("employee_inventory.browse_inventory", store=store_id))

    if not all([store_id, sku_id]):
        flash("Store ID and SKU ID are required.", "error")
        return redirect(url_for("employee_inventory.browse_inventory", store=store_id))

    if current_quantity < 0 or reorder_level < 0:
        flash("Quantities cannot be negative.", "error")
        return redirect(url_for("employee_inventory.browse_inventory", store=store_id))

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO roadready.inventory (store_id, sku_id, qty_on_hand, reorder_level, bin_location)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (store_id, sku_id) DO UPDATE
                    SET qty_on_hand = EXCLUDED.qty_on_hand,
                        reorder_level = EXCLUDED.reorder_level,
                        bin_location = EXCLUDED.bin_location
                """,
                (store_id, sku_id, current_quantity, reorder_level, bin_location),
            )
            conn.commit()
            flash("Inventory updated successfully.", "success")
    except Exception:
        employee_inventory.logger.exception("Error updating inventory for store_id=%s, sku_id=%s", store_id, sku_id)
        flash("An error occurred while updating the inventory. Please try again.", "error")

    return redirect(url_for("employee_inventory.browse_inventory", store=store_id))


@employee_inventory.route("/inventory/add", methods=["POST"])
@manager_login_required
def edit_part():
    part_name = request.form.get("part_name", "").strip()
    part_number = request.form.get("part_number", "").strip()
    category_id = request.form.get("category_id", type=int)
    model_id = request.form.get("model_id", type=int) or request.form.get("vehicle_id", type=int)
    brand = request.form.get("brand", "").strip()
    condition = request.form.get("condition", "NEW").strip().upper() or "NEW"
    description = request.form.get("description", "").strip() or None
    store_id = request.form.get("store_id", type=int)
    bin_location = request.form.get("bin_location", "").strip() or None

    try:
        unit_price = float(str(request.form.get("unit_price", 0)).strip())
        current_quantity = int(str(request.form.get("current_quantity", 0)).strip())
        reorder_level = int(str(request.form.get("reorder_level", 5)).strip())
        core_charge = float(str(request.form.get("core_charge", 0)).strip())
    except (ValueError, TypeError):
        flash("Invalid numeric values provided.", "error")
        return redirect(url_for("employee_inventory.browse_inventory", store=store_id))

    if not all([part_name, part_number, category_id, brand, store_id]) or unit_price <= 0:
        flash("Please complete all required fields with a valid price.", "error")
        return redirect(url_for("employee_inventory.browse_inventory", store=store_id))

    try:
        with get_db_connection() as conn:
            part_row = conn.execute(
                """
                INSERT INTO roadready.part (part_name, part_number, category_id, brand, description)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING part_id
                """,
                (part_name, part_number, category_id, brand, description),
            ).fetchone()
            part_id = part_row[0]

            if model_id:
                conn.execute(
                    """
                    INSERT INTO roadready.part_fitment (part_id, model_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (part_id, model_id),
                )

            sku_row = conn.execute(
                """
                INSERT INTO roadready.part_sku (part_id, condition, unit_price, core_charge, is_active)
                VALUES (%s, %s, %s, %s, TRUE)
                RETURNING sku_id
                """,
                (part_id, condition, unit_price, core_charge),
            ).fetchone()
            sku_id = sku_row[0]

            conn.execute(
                """
                INSERT INTO roadready.inventory (store_id, sku_id, qty_on_hand, reorder_level, bin_location)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (store_id, sku_id) DO UPDATE
                    SET qty_on_hand = EXCLUDED.qty_on_hand,
                        reorder_level = EXCLUDED.reorder_level,
                        bin_location = EXCLUDED.bin_location
                """,
                (store_id, sku_id, current_quantity, reorder_level, bin_location),
            )
            conn.commit()
            flash("Part added successfully.", "success")
    except Exception:
        employee_inventory.logger.exception("Error adding part: %s", part_name)
        flash("An error occurred while adding the part. Please try again.", "error")

    return redirect(url_for("employee_inventory.browse_inventory", store=store_id))