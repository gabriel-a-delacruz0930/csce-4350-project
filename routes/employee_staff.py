import re
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from db import get_db_connection
from routes.employee_auth import employee_login_required, manager_login_required


employee_staff = Blueprint("employee_staff", __name__)

VALID_ROLES = ("STAFF", "MANAGER", "ADMIN")


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
    if valid_store_id is not None and not any(s[0] == valid_store_id for s in stores):
        valid_store_id = None

    if valid_store_id is None and stores:
        valid_store_id = stores[0][0]
        selected_store_id = str(valid_store_id)

    return stores, valid_store_id, selected_store_id


def redirect_to_staff(store_id=None):
    target_store = store_id or session.get("store_id", "")
    return redirect(url_for("employee_staff.browse_staff", store=target_store))


@employee_staff.route("/employee/staff")
@employee_login_required
def browse_staff():
    search_query = request.args.get("q", "").strip()
    status_message = request.args.get("status_msg", "").strip()
    error_message = request.args.get("error_msg", "").strip()

    stores = []
    valid_store_id = None
    selected_store_id = ""
    staff_members = []
    shifts = []
    departments = []

    try:
        stores, valid_store_id, selected_store_id = get_store_id()

        with get_db_connection() as conn:
            departments = conn.execute(
                """
                SELECT dept_id, dept_name
                FROM roadready.department
                ORDER BY dept_name
                """
            ).fetchall()

            staff_conditions = []
            staff_params = []

            if valid_store_id is not None:
                staff_conditions.append("e.store_id = %s")
                staff_params.append(valid_store_id)

            if search_query:
                staff_conditions.append(
                    """
                    (
                        (e.first_name || ' ' || e.last_name) ILIKE %s
                        OR e.email ILIKE %s
                        OR e.job_title ILIKE %s
                        OR e.access_role ILIKE %s
                        OR d.dept_name ILIKE %s
                    )
                    """
                )
                staff_params.extend([f"%{search_query}%"] * 5)

            staff_where = ("WHERE " + " AND ".join(staff_conditions)) if staff_conditions else ""

            staff_members = conn.execute(
                f"""
                SELECT
                    e.employee_id,
                    e.first_name || ' ' || e.last_name AS full_name,
                    e.access_role,
                    e.email,
                    e.is_active,
                    e.job_title,
                    d.dept_name,
                    e.hourly_rate
                FROM roadready.employee e
                JOIN roadready.department d
                    ON d.dept_id = e.dept_id
                {staff_where}
                ORDER BY e.is_active DESC, e.last_name, e.first_name
                """,
                tuple(staff_params),
            ).fetchall()

            shift_conditions = []
            shift_params = []

            if valid_store_id is not None:
                shift_conditions.append("sh.store_id = %s")
                shift_params.append(valid_store_id)

            if search_query:
                shift_conditions.append(
                    """
                    (
                        (e.first_name || ' ' || e.last_name) ILIKE %s
                        OR e.job_title ILIKE %s
                    )
                    """
                )
                shift_params.extend([f"%{search_query}%"] * 2)

            shift_where = ("WHERE " + " AND ".join(shift_conditions)) if shift_conditions else ""

            shifts = conn.execute(
                f"""
                SELECT
                    sh.shift_id,
                    e.first_name || ' ' || e.last_name AS employee_name,
                    sh.shift_date,
                    sh.start_time,
                    sh.end_time,
                    e.job_title
                FROM roadready.shift sh
                JOIN roadready.employee e
                    ON e.employee_id = sh.employee_id
                {shift_where}
                ORDER BY sh.shift_date DESC, sh.start_time ASC, sh.shift_id DESC
                LIMIT 50
                """,
                tuple(shift_params),
            ).fetchall()

    except Exception:
        employee_staff.logger.exception("Error loading staff and shifts")
        flash("An error occurred while loading staff and shifts.", "error")

    return render_template(
        "employee/staff.html",
        stores=stores,
        valid_store_id=valid_store_id,
        selected_store_id=selected_store_id,
        staff_members=staff_members,
        shifts=shifts,
        departments=departments,
        search_query=search_query,
        status_message=status_message,
        error_message=error_message,
    )


@employee_staff.route("/employee/staff/shifts/assign", methods=["POST"])
@employee_login_required
def assign_shift():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    employee_id = request.form.get("employee_id", type=int)
    shift_date = request.form.get("shift_date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()

    if not all([store_id, employee_id, shift_date, start_time, end_time]):
        flash("Employee, shift date, start time, and end time are required.", "error")
        return redirect_to_staff(store_id)

    if end_time <= start_time:
        flash("Shift end time must be after start time.", "error")
        return redirect_to_staff(store_id)

    try:
        with get_db_connection() as conn:
            emp_row = conn.execute(
                """
                SELECT store_id
                FROM roadready.employee
                WHERE employee_id = %s
                """,
                (employee_id,),
            ).fetchone()

            if not emp_row:
                flash("Selected employee was not found.", "error")
                return redirect_to_staff(store_id)

            target_store = emp_row[0] or store_id

            conn.execute(
                """
                INSERT INTO roadready.shift (
                    employee_id, store_id, shift_date, start_time, end_time
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (employee_id, shift_date, start_time) DO UPDATE
                    SET store_id = EXCLUDED.store_id,
                        end_time = EXCLUDED.end_time
                """,
                (employee_id, target_store, shift_date, start_time, end_time),
            )
            conn.commit()

        flash("Shift saved successfully.", "success")
        return redirect_to_staff(target_store)
    except Exception:
        employee_staff.logger.exception("Error assigning shift for employee_id=%s", employee_id)
        flash("An error occurred while saving the shift.", "error")
        return redirect_to_staff(store_id)


@employee_staff.route("/employee/staff/shifts/delete", methods=["POST"])
@manager_login_required
def delete_shift():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    shift_id = request.form.get("shift_id", type=int)

    if not shift_id:
        flash("Shift ID is required.", "error")
        return redirect_to_staff(store_id)

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                DELETE FROM roadready.shift
                WHERE shift_id = %s
                """,
                (shift_id,),
            )
            conn.commit()
        flash("Shift removed.", "success")
        return redirect_to_staff(store_id)
    except Exception:
        employee_staff.logger.exception("Error deleting shift shift_id=%s", shift_id)
        flash("An error occurred while removing the shift.", "error")
        return redirect_to_staff(store_id)


@employee_staff.route("/employee/staff/add", methods=["POST"])
@manager_login_required
def add_employee():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role_name = (request.form.get("access_role") or request.form.get("role_name") or "STAFF").strip().upper()
    job_title = request.form.get("job_title", "").strip() or role_name.title()
    dept_id = request.form.get("dept_id", type=int)
    hourly_rate_raw = request.form.get("hourly_rate", "15.00").strip()

    if role_name not in VALID_ROLES:
        role_name = "STAFF"

    try:
        hourly_rate = float(hourly_rate_raw)
        if hourly_rate < 7.25:
            hourly_rate = 15.00
    except (ValueError, TypeError):
        hourly_rate = 15.00

    if not all([store_id, first_name, last_name, email]):
        flash("First name, last name, and email are required.", "error")
        return redirect_to_staff(store_id)

    base_user = re.sub(r"[^a-z0-9_]", "", f"{first_name[:1]}{last_name}".lower()) or "staff"
    username = f"{base_user[:24]}_{store_id}"

    try:
        with get_db_connection() as conn:
            if not dept_id:
                dept_row = conn.execute(
                    """
                    SELECT dept_id
                    FROM roadready.department
                    ORDER BY dept_id
                    LIMIT 1
                    """
                ).fetchone()
                dept_id = dept_row[0] if dept_row else None

            if not dept_id:
                flash("No department found to assign employee.", "error")
                return redirect_to_staff(store_id)

            conn.execute(
                """
                INSERT INTO roadready.employee (
                    first_name, last_name, email, job_title, dept_id, store_id,
                    hourly_rate, username, password_hash, access_role, is_active
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, roadready.crypt('RoadReadyTemp123!', roadready.gen_salt('bf')), %s, TRUE
                )
                """,
                (
                    first_name,
                    last_name,
                    email,
                    job_title[:40],
                    dept_id,
                    store_id,
                    hourly_rate,
                    username[:30],
                    role_name,
                ),
            )
            conn.commit()

        flash(f"Added {first_name} {last_name} to store roster.", "success")
        return redirect_to_staff(store_id)
    except Exception:
        employee_staff.logger.exception("Error adding employee %s %s", first_name, last_name)
        flash("Could not add employee (email or username may already exist).", "error")
        return redirect_to_staff(store_id)


@employee_staff.route("/employee/staff/update", methods=["POST"])
@manager_login_required
def update_employee():
    store_id = request.form.get("store_id", type=int) or session.get("store_id")
    employee_id = request.form.get("employee_id", type=int)
    role_name = (request.form.get("access_role") or request.form.get("role_name") or "STAFF").strip().upper()
    is_active = request.form.get("is_active", "1").strip() == "1"

    if not employee_id or role_name not in VALID_ROLES:
        flash("Valid employee and role are required.", "error")
        return redirect_to_staff(store_id)

    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE roadready.employee
                SET access_role = %s,
                    is_active = %s
                WHERE employee_id = %s
                """,
                (role_name, is_active, employee_id),
            )
            conn.commit()
        flash("Employee updated successfully.", "success")
        return redirect_to_staff(store_id)
    except Exception:
        employee_staff.logger.exception("Error updating employee employee_id=%s", employee_id)
        flash("An error occurred while updating employee.", "error")
        return redirect_to_staff(store_id)