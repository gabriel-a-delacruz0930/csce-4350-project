from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user

from db import get_db_connection
from routes.employee_auth import employee_login_required, manager_login_required

employee_orders = Blueprint("employee_orders", __name__)

def redirect_to_orders():
    return redirect(url_for("employee_orders.browse_orders"))

def get_status_id(status_name):
    with get_db_connection() as conn:
        status = conn.execute(
            """
            SELECT status_id
            FROM roadready.order_status
            WHERE status_name = %s
            """,
            (status_name,)
        ).fetchone()
    return status[0] if status else None

def get_store_id(store_id):
    with get_db_connection() as conn:
        selected_store_id = (raw_store_id := request.args.get("store", "").strip()) or store_id
        if not selected_store_id.isdigit():
            selected_store_id = str(session.get("store_id", ""))
        stores = conn.execute(
            """
            SELECT store_id, store_name
            FROM roadready.store
            """
        ).fetchall()

def get_order_statuses():
    with get_db_connection() as conn:
        statuses = conn.execute(
            """
            SELECT status_id, status_name
            FROM roadready.order_status
            ORDER BY status_id
            """
        ).fetchall()
    return statuses

@employee_orders.route("/employee/orders")
@employee_login_required
def browse_orders():
    search_query = request.args.get("q", "").strip()
    status_id = request.args.get("status", "").strip()
    raw_store_id = request.args.get("store", "").strip()
    
    store_id = get_store_id(raw_store_id)

    try:    
        with get_db_connection() as conn:
            statuses = get_order_statuses()

            conditions = []
            parameters = []

            if search_query:
                conditions.append(
                    """
                    (
                        o.order_id::TEXT ILIKE %s
                        OR c.first_name ILIKE %s
                        OR c.last_name ILIKE %s
                    )
                    """
                )
                parameters.extend([f"%{search_query}%"] * 3)

            if status_id.isdigit():
                conditions.append("o.status_id = %s")
                parameters.append(int(status_id))

            where_clause = " AND ".join(conditions)
            if where_clause:
                where_clause = "WHERE " + where_clause

            orders = conn.execute(
                f"""
                SELECT o.order_id, o.customer_id, o.status_id, o.order_date,
                    c.first_name, c.last_name, s.status_name
                FROM roadready.orders o
                JOIN roadready.customer c ON o.customer_id = c.customer_id
                JOIN roadready.order_status s ON o.status_id = s.status_id
                {where_clause}
                ORDER BY o.order_date DESC
                """,
                tuple(parameters)
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
                SELECT sku_id, part_name
                FROM roadready.sku
                ORDER BY part_name
                """
            ).fetchall()
            
            purchase_orders = conn.execute(
                """
                SELECT po.purchase_order_id, po.supplier_id, po.order_date, s.supplier_name
                FROM roadready.purchase_order po
                JOIN roadready.supplier s ON po.supplier_id = s.supplier_id
                ORDER BY po.order_date DESC
                """
            ).fetchall()

            returns = conn.execute(
                """
                SELECT r.return_id, r.order_id, r.customer_id, r.return_date, c.first_name, c.last_name
                FROM roadready.return r
                JOIN roadready.customer c ON r.customer_id = c.customer_id
                ORDER BY r.return_date DESC
                """
            ).fetchall()

    except Exception:
        employee_orders.logger.exception("Error fetching orders, suppliers, SKUs, purchase orders, or returns.")
        flash("An error occurred while fetching data. Please try again later.", "error")
            
    return render_template(
        "employee/orders.html",
        orders=orders,
        statuses=statuses,
        selected_status=status_id,
        search_query=search_query,
        suppliers=suppliers,
        skus=skus,
        purchase_orders=purchase_orders,
        returns=returns
    )
    
@employee_orders.route("/employee/orders/<int:order_id>")
@employee_login_required
def update_order(order_id):
    store_id = get_store_id(request.form.get("store", "").strip())
    order_id = request.form.get("order_id", type=int).strip()
    status_id = request.form.get("status_id", type=int).strip()
    
    if not all([store_id, order_id, status_id]):
        flash("Store ID, Order ID, and Status ID are required.", "error")
        return redirect_to_orders()
    
    try:
        with get_db_connection() as conn:
            order = conn.execute(
                """
                SELECT o.order_id, o.customer_id, o.status_id, o.order_date,
                    c.first_name, c.last_name, s.status_name
                FROM roadready.orders o
                JOIN roadready.customer c ON o.customer_id = c.customer_id
                JOIN roadready.order_status s ON o.status_id = s.status_id
                WHERE o.order_id = %s
                """,
                (order_id,)
            ).fetchone()

            if not order:
                flash("Order not found.", "error")
                return redirect_to_orders()

            statuses = get_order_statuses()

        return render_template(
            "employee/order_detail.html",
            order=order,
            statuses=statuses
        )
        return redirect_to_orders(store_id, status=f"Status ID {status_id} updated successfully.")
    except Exception:
        employee_orders.logger.exception("Error fetching order details for order_id=%s", order_id)
        flash("An error occurred while fetching the order details. Please try again later.", "error")
        return redirect_to_orders()
    
@employee_orders.route("/employee/orders/update", methods=["POST"])
@employee_login_required
def create_order():
    store_id = get_store_id(request.form.get("store", "").strip())
    employee_id = request.form.get("employee_id", type=int).strip()
    status_id = request.form.get("status_id", type=int).strip()
    sku_id = request.form.get("sku_id", type=int).strip()
    
    if not all([store_id, employee_id, status_id]):
        flash("Store ID, Employee ID, and Status ID are required.", "error")
        return redirect_to_orders()
    
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO roadready.orders (employee_id, status_id)
                VALUES (%s, %s)
                """,
                (employee_id, status_id)
            )
            conn.commit()
            flash("Order created successfully.", "success")
    except Exception:
        employee_orders.logger.exception("Error creating order for employee_id=%s", employee_id)
        flash("An error occurred while creating the order. Please try again later.", "error")
    
    return redirect_to_orders()

@employee_orders.route("/employee/orders/delete", methods=["POST"])
@employee_login_required
def delete_order():
    store_id = get_store_id(request.form.get("store", "").strip())
    order_id = request.form.get("order_id", type=int).strip()
    
    if not all([store_id, order_id]):
        flash("Store ID and Order ID are required.", "error")
        return redirect_to_orders()
    
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                DELETE FROM roadready.orders
                WHERE order_id = %s
                """,
                (order_id,)
            )
            conn.commit()
            flash("Order deleted successfully.", "success")
    except Exception:
        employee_orders.logger.exception("Error deleting order with order_id=%s", order_id)
        flash("An error occurred while deleting the order. Please try again later.", "error")
    
    return redirect_to_orders()

@employee_orders.route("/employee/orders/receive", methods=["POST"])
@employee_login_required
def receive_order():
    store_id = get_store_id(request.form.get("store", "").strip())
    order_id = request.form.get("order_id", type=int).strip()
    status_id = get_status_id("Received")
    
    if not all([store_id, order_id]):
        flash("Store ID and Order ID are required.", "error")
        return redirect_to_orders()

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.orders
                SET status_id = %s
                WHERE order_id = %s
                """,
                (status_id, order_id)
            )
            conn.commit()
            flash("Order marked as received successfully.", "success")
    except Exception:
        employee_orders.logger.exception("Error marking order as received with order_id=%s", order_id)
        flash("An error occurred while marking the order as received. Please try again later.", "error")

    return redirect_to_orders()

@employee_orders.route("/employee/orders/cancel", methods=["POST"])
@employee_login_required
def cancel_order():
    store_id = get_store_id(request.form.get("store", "").strip())
    order_id = request.form.get("order_id", type=int).strip()

    if not all([store_id, order_id]):
        flash("Store ID and Order ID are required.", "error")
        return redirect_to_orders()

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.orders
                SET status_id = %s
                WHERE order_id = %s
                """,
                (get_status_id("Cancelled"), order_id)
            )
            conn.commit()
            flash("Order cancelled successfully.", "success")
    except Exception:
        employee_orders.logger.exception("Error cancelling order with order_id=%s", order_id)
        flash("An error occurred while cancelling the order. Please try again later.", "error")

    return redirect_to_orders()

@employee_orders.route("/employee/orders/return", methods=["POST"])
@employee_login_required
def return_order():
    store_id = get_store_id(request.form.get("store", "").strip())
    order_id = request.form.get("order_id", type=int).strip()

    if not all([store_id, order_id]):
        flash("Store ID and Order ID are required.", "error")
        return redirect_to_orders()

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.orders
                SET status_id = %s
                WHERE order_id = %s
                """,
                (get_status_id("Returned"), order_id)
            )
            conn.commit()
            flash("Order marked as returned successfully.", "success")
    except Exception:
        employee_orders.logger.exception("Error marking order as returned with order_id=%s", order_id)
        flash("An error occurred while marking the order as returned. Please try again later.", "error")

    return redirect_to_orders()