from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user

from db import get_db_connection
from routes.employee_auth import employee_login_required, manager_login_required

employee_orders = Blueprint("employee_orders", __name__)

ORDER_STATUSES = ("PLACED", "PAID", "SHIPPED", "COMPLETED", "CANCELLED")


def redirect_to_orders(store_id=None):
    target_store = store_id or session.get("store_id", "")
    return redirect(url_for("employee_orders.browse_orders", store=target_store))


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


def get_order_statuses():
    return ORDER_STATUSES


@employee_orders.route("/orders")
@employee_login_required
def browse_orders():
    search_query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip().upper()
    raw_store_id = request.args.get("store", "").strip()

    stores = []
    valid_store_id = None
    selected_store_id = ""
    statuses = get_order_statuses()
    orders = []
    suppliers = []
    skus = []
    purchase_orders = []
    returns = []

    try:
        with get_db_connection() as conn:
            stores, valid_store_id, selected_store_id = get_store_id(raw_store_id)

            conditions = []
            parameters = []

            if valid_store_id is not None:
                conditions.append("co.store_id = %s")
                parameters.append(valid_store_id)

            if search_query:
                conditions.append(
                    """
                    (
                        co.order_id::TEXT ILIKE %s
                        OR c.first_name ILIKE %s
                        OR c.last_name ILIKE %s
                    )
                    """
                )
                parameters.extend([f"%{search_query}%"] * 3)

            if status_filter in ORDER_STATUSES:
                conditions.append("co.status = %s")
                parameters.append(status_filter)
            else:
                status_filter = ""

            where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            orders = conn.execute(
                f"""
                SELECT co.order_id, co.customer_id, co.status, co.order_date,
                       c.first_name, c.last_name,
                       COALESCE(ot.order_total, 0) AS order_total
                FROM roadready.customer_order co
                JOIN roadready.customer c ON co.customer_id = c.customer_id
                LEFT JOIN roadready.v_order_totals ot ON co.order_id = ot.order_id
                {where_clause}
                ORDER BY co.order_date DESC
                """,
                tuple(parameters),
            ).fetchall()

            suppliers = conn.execute(
                """
                SELECT supplier_id, supplier_name
                FROM roadready.supplier
                ORDER BY supplier_name
                """
            ).fetchall()

            skus = conn.execute(
                """
                SELECT sku.sku_id, p.part_name, sku.condition, sku.unit_price
                FROM roadready.part_sku sku
                JOIN roadready.part p ON sku.part_id = p.part_id
                WHERE sku.is_active = TRUE
                ORDER BY p.part_name, sku.condition
                """
            ).fetchall()

            purchase_orders = conn.execute(
                """
                SELECT po.po_id, po.supplier_id, po.order_date, po.status, s.supplier_name
                FROM roadready.purchase_order po
                JOIN roadready.supplier s ON po.supplier_id = s.supplier_id
                WHERE (%s IS NULL OR po.store_id = %s)
                ORDER BY po.order_date DESC, po.po_id DESC
                """,
                (valid_store_id, valid_store_id),
            ).fetchall()

            returns = conn.execute(
                """
                SELECT r.return_id, r.order_id, r.line_no, r.quantity,
                       r.reason, r.return_date, r.refund_amount,
                       c.first_name, c.last_name
                FROM roadready.order_return r
                JOIN roadready.customer_order co ON r.order_id = co.order_id
                JOIN roadready.customer c ON co.customer_id = c.customer_id
                WHERE (%s IS NULL OR co.store_id = %s)
                ORDER BY r.return_date DESC, r.return_id DESC
                """,
                (valid_store_id, valid_store_id),
            ).fetchall()

    except Exception:
        employee_orders.logger.exception("Error fetching orders, suppliers, SKUs, purchase orders, or returns.")
        flash("An error occurred while fetching data. Please try again later.", "error")

    return render_template(
        "employee/orders.html",
        orders=orders,
        statuses=statuses,
        selected_status=status_filter,
        search_query=search_query,
        stores=stores,
        valid_store_id=valid_store_id,
        selected_store_id=selected_store_id,
        suppliers=suppliers,
        skus=skus,
        purchase_orders=purchase_orders,
        returns=returns,
    )


@employee_orders.route("/orders/update", methods=["POST"])
@employee_login_required
def update_order():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    order_id = request.form.get("order_id", type=int)
    new_status = request.form.get("status", "").strip().upper()

    if not all([order_id, new_status]) or new_status not in ORDER_STATUSES:
        flash("Order ID and a valid status are required.", "error")
        return redirect_to_orders(store_id)

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.customer_order
                SET status = %s,
                    cancelled_at = CASE WHEN %s = 'CANCELLED' THEN COALESCE(cancelled_at, NOW()) ELSE NULL END
                WHERE order_id = %s
                """,
                (new_status, new_status, order_id),
            )
            conn.commit()
            flash(f"Order #{order_id} updated to {new_status}.", "success")
    except Exception:
        employee_orders.logger.exception("Error updating order order_id=%s", order_id)
        flash("An error occurred while updating the order. Please try again later.", "error")

    return redirect_to_orders(store_id)


@employee_orders.route("/orders/po/create", methods=["POST"])
@employee_login_required
def create_order():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    supplier_id = request.form.get("supplier_id", type=int)
    sku_id = request.form.get("sku_id", type=int)
    employee_id = request.form.get("employee_id", type=int) or session.get("employee_id")
    quantity = request.form.get("quantity", type=int) or 1
    unit_cost = request.form.get("unit_cost", type=float) or 0.0

    if not all([store_id, supplier_id, sku_id, employee_id]) or quantity <= 0:
        flash("Store, supplier, SKU, employee, and positive quantity are required.", "error")
        return redirect_to_orders(store_id)

    try:
        with get_db_connection() as conn:
            po_id = conn.execute(
                """
                INSERT INTO roadready.purchase_order (supplier_id, store_id, ordered_by, status)
                VALUES (%s, %s, %s, 'PENDING')
                RETURNING po_id
                """,
                (supplier_id, store_id, employee_id),
            ).fetchone()[0]

            conn.execute(
                """
                INSERT INTO roadready.po_line (po_id, sku_id, quantity, unit_cost)
                VALUES (%s, %s, %s, %s)
                """,
                (po_id, sku_id, quantity, unit_cost),
            )
            conn.commit()
            flash(f"Purchase order #{po_id} created successfully.", "success")
    except Exception:
        employee_orders.logger.exception("Error creating purchase order for store_id=%s", store_id)
        flash("An error occurred while creating the purchase order. Please try again later.", "error")

    return redirect_to_orders(store_id)


@employee_orders.route("/orders/po/receive", methods=["POST"])
@manager_login_required
def receive_order():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    po_id = request.form.get("po_id", type=int) or request.form.get("order_id", type=int)

    if not po_id:
        flash("Purchase Order ID is required.", "error")
        return redirect_to_orders(store_id)

    try:
        with get_db_connection() as conn:
            # trg_receive_po automatically adds po_line quantities to inventory and sets received_date
            conn.execute(
                """
                UPDATE roadready.purchase_order
                SET status = 'RECEIVED'
                WHERE po_id = %s AND status <> 'STOPPED'
                """,
                (po_id,),
            )
            conn.commit()
            flash(f"Purchase order #{po_id} marked as received.", "success")
    except Exception:
        employee_orders.logger.exception("Error marking purchase order as received po_id=%s", po_id)
        flash("An error occurred while marking the purchase order as received. Please try again later.", "error")

    return redirect_to_orders(store_id)


@employee_orders.route("/orders/cancel", methods=["POST"])
@employee_login_required
def cancel_order():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    order_id = request.form.get("order_id", type=int)

    if not order_id:
        flash("Order ID is required.", "error")
        return redirect_to_orders(store_id)

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.customer_order
                SET status = 'CANCELLED',
                    cancelled_at = COALESCE(cancelled_at, NOW()),
                    cancel_reason = COALESCE(cancel_reason, 'Cancelled by employee')
                WHERE order_id = %s
                """,
                (order_id,),
            )
            conn.commit()
            flash(f"Order #{order_id} cancelled successfully.", "success")
    except Exception:
        employee_orders.logger.exception("Error cancelling order with order_id=%s", order_id)
        flash("An error occurred while cancelling the order. Please try again later.", "error")

    return redirect_to_orders(store_id)


@employee_orders.route("/orders/return", methods=["POST"])
@employee_login_required
def return_order():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    order_id = request.form.get("order_id", type=int)
    line_no = request.form.get("line_no", type=int) or 1
    quantity = request.form.get("quantity", type=int) or 1
    refund_amount = request.form.get("refund_amount", type=float) or 0.0
    reason = request.form.get("reason", "").strip() or "Customer return"
    processed_by = request.form.get("employee_id", type=int) or session.get("employee_id")

    if not all([order_id, processed_by]) or quantity <= 0:
        flash("Order ID, employee, and positive quantity are required.", "error")
        return redirect_to_orders(store_id)

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO roadready.order_return (
                    order_id, line_no, quantity, reason, refund_amount, processed_by
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (order_id, line_no, quantity, reason, refund_amount, processed_by),
            )
            conn.commit()
            flash(f"Return recorded for order #{order_id}.", "success")
    except Exception:
        employee_orders.logger.exception("Error recording return for order_id=%s", order_id)
        flash("An error occurred while recording the return. Please try again later.", "error")

    return redirect_to_orders(store_id)