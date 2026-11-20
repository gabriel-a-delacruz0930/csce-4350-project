from flask import Blueprint, render_template, request, redirect, url_for, flash

from db import get_db_connection
from routes.employee_auth import employee_login_required, manager_login_required

employee_inventory = Blueprint("employee_inventory", __name__)

@employee_inventory.route("/employee/inventory")
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
        parameters = [valid_store_id]

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

        if category_id.isdigit():
            conditions.append("sku.category_id = %s")
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
                sku.sku_name,
                sku.price,
                sku.quantity_in_stock,
                c.category_name,
                v.make,
                v.model,
                v.model_year
            FROM roadready.sku
            JOIN roadready.category c
                ON sku.category_id = c.category_id
            JOIN roadready.vehicle_model v
                ON sku.vehicle_id = v.model_id
            WHERE {where_clause}
            ORDER BY sku.sku_name
        """

        products = conn.execute(query, tuple(parameters)).fetchall()

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
    
@employee_inventory.route("/employee/inventory", methods=["POST"])
@employee_login_required
def update_inventory():
    store_id = request.form.get("store_id", type=int).strip()
    sku_id = request.form.get("sku_id", type=int).strip()
    bin_location = request.form.get("bin_location") or None
    
    try:
        current_quantity = int(request.form.get("current_quantity", 0)).strip()
        reorder_level = int(request.form.get("reorder_level", 0)).strip()
    except (ValueError, TypeError):
        return render_template("employee/inventory.html", error="Invalid quantity values provided.")
        return redirect(url_for("employee_inventory.browse_inventory"), store_id=store_id)
    
    if not all([store_id, sku_id]):
        return render_template("employee/inventory.html", error="Store ID and SKU ID are required.")
        return redirect(url_for("employee_inventory.browse_inventory"), store_id=store_id)
    
    if current_quantity < 0 or reorder_level < 0:
        return render_template("employee/inventory.html", error="Quantities cannot be negative.")
        return redirect(url_for("employee_inventory.browse_inventory"), store_id=store_id)
    
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.inventory
                SET qty_on_hand = %s,
                    reorder_lvl = %s,
                    bin_location = %s
                WHERE store_id = %s AND sku_id = %s
                """,
                (current_quantity, reorder_level, bin_location, store_id, sku_id)
            )
            conn.commit()
            flash("Inventory updated successfully.", "success")
    except Exception:
        employee_inventory.logger.exception("Error updating inventory for store_id=%s, sku_id=%s", store_id, sku_id)
        flash("An error occurred while updating the inventory. Please try again.", "error")
    
    return render_template("employee/inventory.html", success="Inventory updated successfully.")       
    return redirect(url_for("employee_inventory.browse_inventory", store=store_id))

@employee_inventory.route("/employee/inventory/add", methods=["POST"])
@manager_login_required
def edit_part():
    part_name = request.form.get("part_name", "").strip()
    part_number = request.form.get("part_number", "").strip()
    category_id = request.form.get("category_id", type=int).strip()
    vehicle_id = request.form.get("vehicle_id", type=int).strip()
    brand = request.form.get("brand", "").strip()
    model_year = request.form.get("model_year", type=int).strip()
    model_id = request.form.get("model_id", type=int).strip()
    description = request.form.get("description", "").strip()
    store_id = request.form.get("store_id", type=int).strip()
    bin_location = request.form.get("bin_location", "").strip()
    
    try:
        unit_price = float(request.form.get("unit_price", 0)).strip()
        current_quantity = int(request.form.get("current_quantity", 0)).strip()
        reorder_level = int(request.form.get("reorder_level", 0)).strip()
        core_charge = float(request.form.get("core_charge", 0)).strip()
    except (ValueError, TypeError):
        flash("Invalid numeric values provided.", "error")
        return redirect(url_for("employee_inventory.browse_inventory"))
    
    if not all([part_name, part_number, category_id, vehicle_id, brand, model_year, model_id, description, store_id]):
        flash("Please complete all required fields.", "error")
        return redirect(url_for("employee_inventory.browse_inventory"))
    
    try:
        with get_db_connection() as conn:
            
            part_row = conn.execute(
                """
                INSERT INTO roadready.part (part_name, part_number, category_id, brand, description)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (part_name, part_number, category_id, brand, description)
            )
            part_id = conn.execute("SELECT LASTVAL()").fetchone()[0]
        
        if model_id:
            conn.execute(
                """
                INSERT INTO roadready.part_fitment (part_id, model_id)
                VALUES (%s, %s)
                """,
                (part_id, model_id)
            )

        sku_row = conn.execute(
            """
            INSERT INTO roadready.inventory (store_id, sku_id, qty_on_hand, reorder_lvl, bin_location)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (store_id, part_id, current_quantity, reorder_level, bin_location)
        )
        sku_row = conn.execute("SELECT LASTVAL()").fetchone()[0]
        conn.commit()

        if store_id and sku_row:
            conn.execute(
                """
                INSERT INTO roadready.store_inventory (store_id, sku_id)
                VALUES (%s, %s)
                """,
                (store_id, sku_row)
            )
            conn.commit()
            flash("Part added successfully.", "success")
    except Exception:
        employee_inventory.logger.exception("Error adding part: %s", part_name)
        flash("An error occurred while adding the part. Please try again.", "error")
        
    return redirect(url_for("employee_inventory.browse_inventory"))