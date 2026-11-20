from flask import Blueprint, redirect, render_template, request, session, url_for, flash

from db import get_db_connection
from routes.employee_auth import employee_login_required, manager_login_required

employee_deliveries = Blueprint("employee_deliveries", __name__)


def get_store_id(store_id=None):
    with get_db_connection() as conn:
        raw_store_id = request.args.get("store", "").strip()
        selected_store_id = raw_store_id or str(store_id or "")
        if not selected_store_id.isdigit():
            selected_store_id = str(session.get("store_id", ""))
        stores = conn.execute(
            """
            SELECT store_id, store_name
            FROM roadready.store
            WHERE is_active = TRUE
            ORDER BY store_name
            """
        ).fetchall()
        valid_store_id = int(selected_store_id) if selected_store_id.isdigit() else None
        return stores, valid_store_id, selected_store_id


def redirect_to_deliveries(store_id=None):
    target_store = store_id or session.get("store_id", "")
    return redirect(url_for("employee_deliveries.browse_deliveries", store=target_store))


@employee_deliveries.route("/employee/deliveries")
@employee_login_required
def browse_deliveries():
    search_query = request.args.get("q", "").strip()
    delivery_status = request.args.get("status", "").strip().upper()
    status_message = request.args.get("status_msg", "").strip()
    error_message = request.args.get("error_msg", "").strip()

    stores = []
    valid_store_id = None
    selected_store_id = ""
    drivers = []
    eligible_orders = []
    deliveries = []

    try:
        with get_db_connection() as conn:
            stores, valid_store_id, selected_store_id = get_store_id()

            drivers = conn.execute(
                """
                SELECT e.employee_id, e.first_name || ' ' || e.last_name AS driver_name
                FROM roadready.employee e
                WHERE e.is_active = TRUE
                  AND (%s IS NULL OR e.store_id = %s)
                ORDER BY e.last_name, e.first_name
                """,
                (valid_store_id, valid_store_id),
            ).fetchall()

            eligible_orders = conn.execute(
                """
                SELECT co.order_id, co.customer_id, co.status, co.order_date,
                       c.first_name, c.last_name
                FROM roadready.customer_order co
                JOIN roadready.customer c ON co.customer_id = c.customer_id
                WHERE (%s IS NULL OR co.store_id = %s)
                  AND co.fulfillment_type = 'DELIVERY'
                  AND co.status IN ('PLACED', 'PAID')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM roadready.delivery d
                      WHERE d.order_id = co.order_id
                        AND d.status <> 'CANCELLED'
                  )
                ORDER BY co.order_date DESC
                """,
                (valid_store_id, valid_store_id),
            ).fetchall()

            conditions = []
            parameters = []

            if valid_store_id is not None:
                conditions.append("co.store_id = %s")
                parameters.append(valid_store_id)

            if search_query:
                conditions.append(
                    """
                    (
                        COALESCE(e.first_name || ' ' || e.last_name, '') ILIKE %s
                        OR co.order_id::TEXT ILIKE %s
                        OR c.first_name ILIKE %s
                        OR COALESCE(d.tracking_number, '') ILIKE %s
                        OR c.last_name ILIKE %s
                    )
                    """
                )
                parameters.extend([f"%{search_query}%"] * 5)

            if delivery_status in ("PENDING", "IN_TRANSIT", "DELIVERED", "CANCELLED"):
                conditions.append("d.status = %s")
                parameters.append(delivery_status)
            else:
                delivery_status = ""

            where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            deliveries = conn.execute(
                f"""
                SELECT d.driver_id,
                       COALESCE(e.first_name || ' ' || e.last_name, 'Unassigned') AS driver_name,
                       d.tracking_number, d.est_delivery_date, d.status, d.delivery_id, d.order_id, co.store_id,
                       co.order_id, co.customer_id, co.status AS order_status, co.order_date,
                       c.first_name, c.last_name, d.delivered_date
                FROM roadready.delivery d
                JOIN roadready.customer_order co ON d.order_id = co.order_id
                JOIN roadready.customer c ON co.customer_id = c.customer_id
                LEFT JOIN roadready.employee e ON d.driver_id = e.employee_id
                {where_clause}
                ORDER BY co.order_date DESC, d.delivery_id DESC
                """,
                tuple(parameters),
            ).fetchall()
    except Exception:
        employee_deliveries.logger.exception("Error fetching deliveries")
        flash("An error occurred while fetching deliveries.", "error")

    return render_template(
        "employee/deliveries.html",
        deliveries=deliveries,
        drivers=drivers,
        eligible_orders=eligible_orders,
        stores=stores,
        valid_store_id=valid_store_id,
        selected_store_id=selected_store_id,
        search_query=search_query,
        delivery_status=delivery_status,
        status_message=status_message,
        error_message=error_message,
    )


@employee_deliveries.route("/employee/deliveries/create", methods=["POST"])
@employee_login_required
def create_delivery():
    order_id = request.form.get("order_id", type=int).strip()
    driver_id = request.form.get("driver_id", type=int).strip()
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    tracking_number = request.form.get("tracking_number", "").strip()
    est_delivery_date = request.form.get("est_delivery_date", "").strip() or None

    if not order_id or not store_id:
        flash("Order and store are required to create a delivery.", "error")
        return redirect_to_deliveries(store_id)

    initial_status = "IN_TRANSIT" if driver_id else "PENDING"

    try:
        with get_db_connection() as conn:
            order_row = conn.execute(
                """
                SELECT co.store_id, c.street, c.city, c.state, c.zip
                FROM roadready.customer_order co
                JOIN roadready.customer c ON co.customer_id = c.customer_id
                WHERE co.order_id = %s
                """,
                (order_id,),
            ).fetchone()

            if not order_row:
                flash(f"Order #{order_id} was not found.", "error")
                return redirect_to_deliveries(store_id)

            target_store = order_row[0] or store_id
            ship_street = request.form.get("ship_street", "").strip() or order_row[1] or "TBD"
            ship_city = request.form.get("ship_city", "").strip() or order_row[2] or "TBD"
            ship_state = (request.form.get("ship_state", "").strip() or order_row[3] or "TX")[:2].upper()
            ship_zip = (request.form.get("ship_zip", "").strip() or order_row[4] or "76201")[:10]

            conn.execute(
                """
                INSERT INTO roadready.delivery (
                    order_id, ship_street, ship_city, ship_state, ship_zip,
                    tracking_number, driver_id, ship_date, est_delivery_date, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s,
                        CASE WHEN %s = 'IN_TRANSIT' THEN CURRENT_DATE ELSE NULL END,
                        %s, %s)
                """,
                (
                    order_id,
                    ship_street,
                    ship_city,
                    ship_state,
                    ship_zip,
                    tracking_number or None,
                    driver_id,
                    initial_status,
                    est_delivery_date,
                    initial_status,
                ),
            )

            if initial_status == "IN_TRANSIT":
                conn.execute(
                    """
                    UPDATE roadready.customer_order
                    SET status = 'SHIPPED'
                    WHERE order_id = %s AND status <> 'CANCELLED'
                    """,
                    (order_id,),
                )

        flash("Delivery created successfully.", "success")
        return redirect_to_deliveries(target_store)
    except Exception:
        employee_deliveries.logger.exception("Error creating delivery")
        flash("An error occurred while creating the delivery.", "error")
        return redirect_to_deliveries(store_id)

@employee_deliveries.route("/employee/deliveries/update", methods=["POST"])
@employee_login_required    
def update_delivery():
    delivery_id = request.form.get("delivery_id", type=int).strip()
    new_status = request.form.get("new_status", "").strip()

    if not all([delivery_id, new_status]):
        flash("Delivery ID and new status are required.", "error")
        return redirect_to_deliveries(session.get("store_id"))

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.delivery
                SET status = %s
                WHERE delivery_id = %s
                """,
                (new_status, delivery_id),
            )
            conn.commit()
            flash("Delivery status updated successfully.", "success")
    except Exception:
        employee_deliveries.logger.exception("Error updating delivery status")
        flash("An error occurred while updating the delivery status.", "error")

    return redirect_to_deliveries(session.get("store_id"))

@employee_deliveries.route("/employee/deliveries/cancel", methods=["POST"])
@manager_login_required
def cancel_delivery():
    store_id = request.form.get("store_id", type=int).strip()
    delivery_id = request.form.get("delivery_id", type=int).strip()

    if not delivery_id:
        flash("Delivery ID is required.", "error")
        return redirect_to_deliveries(store_id)

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.delivery
                SET status = 'CANCELLED'
                WHERE delivery_id = %s AND status <> 'DELIVERED'
                """,
                (delivery_id,),
            )
        flash(f"Delivery #{delivery_id} cancelled.", "success")
        return redirect_to_deliveries(store_id)
    except Exception:
        employee_deliveries.logger.exception("Error cancelling delivery")
        flash("An error occurred while cancelling the delivery.", "error")
        return redirect_to_deliveries(store_id)