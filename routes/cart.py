
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required

from db import get_db_connection


cart = Blueprint("cart", __name__)


def get_cart():
    return session.get("roadready_cart", {})


@cart.route("/cart")
@login_required
def view_cart():

    cart_items = get_cart()
    products = []
    subtotal = 0
    total_core_charges = 0

    if cart_items:
        sku_ids = [int(sku_id) for sku_id in cart_items]

        with get_db_connection() as conn:
            products = conn.execute(
                """
                SELECT
                    sku.sku_id,
                    p.part_id,
                    p.part_name,
                    p.part_number,
                    p.brand,
                    sku.condition,
                    sku.unit_price,
                    sku.core_charge,
                    COALESCE(SUM(inv.qty_on_hand), 0) AS total_stock

                FROM roadready.part_sku sku

                JOIN roadready.part p
                    ON sku.part_id = p.part_id

                LEFT JOIN roadready.inventory inv
                    ON sku.sku_id = inv.sku_id

                WHERE sku.sku_id = ANY(%s)
                  AND sku.is_active = TRUE

                GROUP BY
                    sku.sku_id,
                    p.part_id,
                    p.part_name,
                    p.part_number,
                    p.brand,
                    sku.condition,
                    sku.unit_price,
                    sku.core_charge
                """,
                (sku_ids,)
            ).fetchall()

        # Calculate cart totals
        cart_display = []

        for product in products:
            sku_id = str(product[0])
            quantity = int(cart_items.get(sku_id, 0))

            if quantity <= 0:
                continue

            unit_price = product[6]
            core_charge = product[7]

            line_subtotal = unit_price * quantity
            line_core_charge = core_charge * quantity

            subtotal += line_subtotal
            total_core_charges += line_core_charge

            cart_display.append({
                "sku_id": product[0],
                "part_id": product[1],
                "part_name": product[2],
                "part_number": product[3],
                "brand": product[4],
                "condition": product[5],
                "unit_price": unit_price,
                "core_charge": core_charge,
                "quantity": quantity,
                "total_stock": product[8],
                "line_subtotal": line_subtotal,
                "line_core_charge": line_core_charge
            })

    else:
        cart_display = []

    return render_template(
        "customer/cart.html",
        cart_items=cart_display,
        subtotal=subtotal,
        total_core_charges=total_core_charges,
        grand_total=subtotal + total_core_charges
    )


@cart.route("/cart/add", methods=["POST"])
@login_required
def add_to_cart():

    sku_id = request.form.get("sku_id", "").strip()

    if not sku_id.isdigit():
        flash("Invalid product selection.", "error")
        return redirect(url_for("parts.browse_parts"))

    with get_db_connection() as conn:
        product = conn.execute(
            """
            SELECT
                sku.sku_id,
                COALESCE(SUM(inv.qty_on_hand), 0) AS total_stock

            FROM roadready.part_sku sku

            LEFT JOIN roadready.inventory inv
                ON sku.sku_id = inv.sku_id

            WHERE sku.sku_id = %s
              AND sku.is_active = TRUE

            GROUP BY sku.sku_id
            """,
            (int(sku_id),)
        ).fetchone()

    if product is None:
        flash("This product is no longer available.", "error")
        return redirect(url_for("parts.browse_parts"))

    if product[1] <= 0:
        flash("This product is currently out of stock.", "error")
        return redirect(url_for("parts.browse_parts"))

    cart_items = get_cart()
    current_quantity = int(cart_items.get(sku_id, 0))

    if current_quantity + 1 > product[1]:
        flash("There is not enough stock for that quantity.", "error")
        return redirect(url_for("cart.view_cart"))

    cart_items[sku_id] = current_quantity + 1
    session["roadready_cart"] = cart_items
    session.modified = True

    flash("Product added to your cart!", "success")
    return redirect(url_for("cart.view_cart"))


@cart.route("/cart/update/<int:sku_id>", methods=["POST"])
@login_required
def update_cart(sku_id):

    quantity = request.form.get("quantity", "").strip()

    if not quantity.isdigit() or int(quantity) < 1:
        flash("Please enter a valid quantity.", "error")
        return redirect(url_for("cart.view_cart"))

    quantity = int(quantity)

    cart_items = get_cart()
    sku_key = str(sku_id)

    if sku_key not in cart_items:
        flash("That item is not in your cart.", "error")
        return redirect(url_for("cart.view_cart"))

    with get_db_connection() as conn:
        product = conn.execute(
            """
            SELECT
                sku.sku_id,
                COALESCE(SUM(inv.qty_on_hand), 0) AS total_stock

            FROM roadready.part_sku sku

            LEFT JOIN roadready.inventory inv
                ON sku.sku_id = inv.sku_id

            WHERE sku.sku_id = %s
              AND sku.is_active = TRUE

            GROUP BY sku.sku_id
            """,
            (sku_id,)
        ).fetchone()

    if product is None or quantity > product[1]:
        flash("The requested quantity is not available.", "error")
        return redirect(url_for("cart.view_cart"))

    cart_items[sku_key] = quantity
    session["roadready_cart"] = cart_items
    session.modified = True

    flash("Cart quantity updated.", "success")
    return redirect(url_for("cart.view_cart"))


@cart.route("/cart/remove/<int:sku_id>", methods=["POST"])
@login_required
def remove_from_cart(sku_id):

    cart_items = get_cart()
    sku_key = str(sku_id)

    if sku_key in cart_items:
        del cart_items[sku_key]
        session["roadready_cart"] = cart_items
        session.modified = True
        flash("Item removed from your cart.", "success")

    return redirect(url_for("cart.view_cart"))
