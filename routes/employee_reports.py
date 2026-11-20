from flask import Blueprint, flash, render_template, request, session

from db import get_db_connection
from routes.employee_auth import employee_login_required, manager_login_required


employee_reports = Blueprint("employee_reports", __name__)


def get_store_id(store_id=None):
    raw_store_id = request.args.get("store", "").strip()
    selected_store_id = raw_store_id or str(store_id or "")
    if not selected_store_id.isdigit():
        selected_store_id = str(session.get("store_id", ""))

    with get_db_connection() as conn:
        stores = conn.execute(
            """
            SELECT store_id, store_name
            FROM roadready.store
            WHERE is_active = TRUE
            ORDER BY store_name
            """
        ).fetchall()

    valid_store_id = int(selected_store_id) if selected_store_id.isdigit() else None
    selected_store_name = None
    if valid_store_id is not None:
        for s_id, s_name in stores:
            if s_id == valid_store_id:
                selected_store_name = s_name
                break
        if selected_store_name is None:
            valid_store_id = None

    if valid_store_id is None and stores:
        valid_store_id, selected_store_name = stores[0]
        selected_store_id = str(valid_store_id)

    return stores, valid_store_id, selected_store_id, selected_store_name


@employee_reports.route("/employee/reports")
@employee_login_required
@manager_login_required
def browse_reports():
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    status_message = request.args.get("status_msg", "").strip()
    error_message = request.args.get("error_msg", "").strip()

    stores = []
    valid_store_id = None
    selected_store_id = ""
    selected_store_name = None
    daily_sales = []
    low_stock = []
    roster = []
    summary = {
        "total_orders": 0,
        "total_revenue": 0.0,
        "active_staff": 0,
    }

    try:
        stores, valid_store_id, selected_store_id, selected_store_name = get_store_id()

        with get_db_connection() as conn:
            sales_conditions = []
            sales_params = []

            if selected_store_name:
                sales_conditions.append("store_name = %s")
                sales_params.append(selected_store_name)

            if start_date:
                sales_conditions.append("sale_date >= %s")
                sales_params.append(start_date)

            if end_date:
                sales_conditions.append("sale_date <= %s")
                sales_params.append(end_date)

            sales_where = ("WHERE " + " AND ".join(sales_conditions)) if sales_conditions else ""

            daily_sales = conn.execute(
                f"""
                SELECT store_name, sale_date, orders, revenue
                FROM roadready.v_daily_sales
                {sales_where}
                ORDER BY sale_date DESC, store_name
                """,
                tuple(sales_params),
            ).fetchall()

            for row in daily_sales:
                summary["total_orders"] += int(row[2] or 0)
                summary["total_revenue"] += float(row[3] or 0.0)

            if selected_store_name:
                low_stock = conn.execute(
                    """
                    SELECT store_name, part_number, part_name, condition,
                           unit_price, qty_on_hand, reorder_level, needs_reorder
                    FROM roadready.v_low_stock
                    WHERE store_name = %s
                    ORDER BY part_name, condition
                    """,
                    (selected_store_name,),
                ).fetchall()
            else:
                low_stock = conn.execute(
                    """
                    SELECT store_name, part_number, part_name, condition,
                           unit_price, qty_on_hand, reorder_level, needs_reorder
                    FROM roadready.v_low_stock
                    ORDER BY store_name, part_name, condition
                    """
                ).fetchall()

            if selected_store_name:
                roster = conn.execute(
                    """
                    SELECT employee_id, employee, job_title, dept_name,
                           store_name, manager, access_role, is_active
                    FROM roadready.v_employee_roster
                    WHERE store_name = %s
                    ORDER BY is_active DESC, employee
                    """,
                    (selected_store_name,),
                ).fetchall()
            else:
                roster = conn.execute(
                    """
                    SELECT employee_id, employee, job_title, dept_name,
                           store_name, manager, access_role, is_active
                    FROM roadready.v_employee_roster
                    ORDER BY store_name, is_active DESC, employee
                    """
                ).fetchall()

            summary["active_staff"] = sum(1 for emp in roster if emp[7])

    except Exception:
        employee_reports.logger.exception("Error loading reports")
        flash("An error occurred while loading reports.", "error")

    return render_template(
        "employee/reports.html",
        stores=stores,
        valid_store_id=valid_store_id,
        selected_store_id=selected_store_id,
        daily_sales=daily_sales,
        low_stock=low_stock,
        roster=roster,
        summary=summary,
        start_date=start_date,
        end_date=end_date,
        status_message=status_message,
        error_message=error_message,
    )