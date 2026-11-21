
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    request,
    current_app
)
from flask_login import login_required, current_user

from db import get_db_connection


checkout = Blueprint("checkout", __name__)


# --------------------------------------------------
# DISPLAY CHECKOUT PAGE
# --------------------------------------------------

@checkout.route("/checkout")
@login_required
def checkout_page():

    cart_items = session.get("roadready_cart", {})

    if not cart_items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart.view_cart"))

    try:
        sku_ids = [int(sku_id) for sku_id in cart_items]
    except (ValueError, TypeError):
        flash("Your cart contains invalid products.", "error")
        return redirect(url_for("cart.view_cart"))

    with get_db_connection() as conn:

        products = conn.execute(
            """
            SELECT
                sku.sku_id,
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
                p.part_name,
                p.part_number,
                p.brand,
                sku.condition,
                sku.unit_price,
                sku.core_charge
            """,
            (sku_ids,)
        ).fetchall()

        stores = conn.execute(
            """
            SELECT store_id, store_name, street, city, state, zip
            FROM roadready.store
            WHERE is_active = TRUE
            ORDER BY store_name
            """
        ).fetchall()

        customer = conn.execute(
            """
            SELECT preferred_store_id
            FROM roadready.customer
            WHERE customer_id = %s
            """,
            (int(current_user.id),)
        ).fetchone()

    checkout_products = []

    subtotal = 0
    total_core_charges = 0

    for product in products:

        sku_id = str(product[0])
        quantity = int(cart_items.get(sku_id, 0))

        if quantity <= 0:
            continue

        unit_price = product[5]
        core_charge = product[6]

        line_subtotal = unit_price * quantity
        line_core_charge = core_charge * quantity

        subtotal += line_subtotal
        total_core_charges += line_core_charge

        checkout_products.append({
            "sku_id": product[0],
            "part_name": product[1],
            "part_number": product[2],
            "brand": product[3],
            "condition": product[4],
            "unit_price": unit_price,
            "core_charge": core_charge,
            "quantity": quantity,
            "line_subtotal": line_subtotal,
            "line_core_charge": line_core_charge,
            "total_stock": product[7]
        })

    if not checkout_products:
        flash("Your cart contains no available products.", "error")
        return redirect(url_for("cart.view_cart"))

    preferred_store_id = customer[0] if customer else None

    return render_template(
        "customer/checkout.html",
        products=checkout_products,
        stores=stores,
        preferred_store_id=preferred_store_id,
        subtotal=subtotal,
        total_core_charges=total_core_charges,
        grand_total=subtotal + total_core_charges
    )


# --------------------------------------------------
# PLACE CUSTOMER ORDER
# --------------------------------------------------

@checkout.route("/checkout/place-order", methods=["POST"])
@login_required
def place_order():

    cart_items = session.get("roadready_cart", {})

    if not cart_items:
        flash("Your cart is empty.", "error")
        return redirect(url_for("cart.view_cart"))

    fulfillment_type = request.form.get("fulfillment_type", "").upper()

    if fulfillment_type not in ("PICKUP", "DELIVERY"):
        flash("Please select a valid fulfillment method.", "error")
        return redirect(url_for("checkout.checkout_page"))

    try:
        store_id = int(request.form.get("store_id", ""))
    except (ValueError, TypeError):
        flash("Please select a valid store.", "error")
        return redirect(url_for("checkout.checkout_page"))

    # Validate delivery address when delivery is selected.

    street = request.form.get("street", "").strip()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip().upper()
    zip_code = request.form.get("zip", "").strip()

    if fulfillment_type == "DELIVERY":

        if not all([street, city, state, zip_code]):
            flash("Please complete all delivery address fields.", "error")
            return redirect(url_for("checkout.checkout_page"))

        if len(street) > 100 or len(city) > 50:
            flash("Your delivery address is too long.", "error")
            return redirect(url_for("checkout.checkout_page"))

        if len(state) != 2:
            flash("Please enter a valid two-letter state code.", "error")
            return redirect(url_for("checkout.checkout_page"))

        import re

        if not re.fullmatch(r"\d{5}(-\d{4})?", zip_code):
            flash("Please enter a valid ZIP code.", "error")
            return redirect(url_for("checkout.checkout_page"))

    # Validate cart quantities.

    try:
        cart_lines = {
            int(sku_id): int(quantity)
            for sku_id, quantity in cart_items.items()
        }

        if not cart_lines or any(quantity <= 0 for quantity in cart_lines.values()):
            raise ValueError

    except (ValueError, TypeError):
        flash("Your cart contains invalid quantities.", "error")
        return redirect(url_for("cart.view_cart"))

    try:

        with get_db_connection() as conn:

            # Verify the selected store.

            store = conn.execute(
                """
                SELECT store_id
                FROM roadready.store
                WHERE store_id = %s
                    AND is_active = TRUE
                """,
                (store_id,)
            ).fetchone()

            if not store:
                raise ValueError("The selected store is unavailable.")

            # Retrieve active products and prices.

            sku_ids = list(cart_lines.keys())

            products = conn.execute(
                """
                SELECT
                    sku.sku_id,
                    sku.unit_price,
                    sku.core_charge
                FROM roadready.part_sku sku
                WHERE sku.sku_id = ANY(%s)
                    AND sku.is_active = TRUE
                """,
                (sku_ids,)
            ).fetchall()

            product_map = {
                product[0]: {
                    "unit_price": product[1],
                    "core_charge": product[2]
                }
                for product in products
            }

            if set(product_map.keys()) != set(sku_ids):
                raise ValueError(
                    "One or more products are no longer available."
                )

            # Lock and verify inventory at the selected store.

            for sku_id, quantity in cart_lines.items():

                inventory = conn.execute(
                    """
                    SELECT qty_on_hand
                    FROM roadready.inventory
                    WHERE store_id = %s
                        AND sku_id = %s
                    FOR UPDATE
                    """,
                    (store_id, sku_id)
                ).fetchone()

                if not inventory or inventory[0] < quantity:
                    raise ValueError(
                        f"Insufficient stock for product SKU {sku_id} "
                        f"at the selected store."
                    )

            # Create the customer order.

            order = conn.execute(
                """
                INSERT INTO roadready.customer_order
                    (customer_id, store_id, channel,
                     fulfillment_type, status)
                VALUES (%s, %s, 'WEB', %s, 'PLACED')
                RETURNING order_id
                """,
                (
                    int(current_user.id),
                    store_id,
                    fulfillment_type
                )
            ).fetchone()

            order_id = order[0]

            # Save order lines and deduct inventory.

            for line_no, (sku_id, quantity) in enumerate(
                cart_lines.items(), start=1
            ):

                product = product_map[sku_id]

                # The schema has no separate historical core-charge
                # column, so the recorded unit price includes it.

                recorded_unit_price = (
                    product["unit_price"] + product["core_charge"]
                )

                conn.execute(
                    """
                    INSERT INTO roadready.order_line
                        (order_id, line_no, sku_id, quantity, unit_price)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        line_no,
                        sku_id,
                        quantity,
                        recorded_unit_price
                    )
                )

                updated = conn.execute(
                    """
                    UPDATE roadready.inventory
                    SET qty_on_hand = qty_on_hand - %s
                    WHERE store_id = %s
                        AND sku_id = %s
                        AND qty_on_hand >= %s
                    """,
                    (
                        quantity,
                        store_id,
                        sku_id,
                        quantity
                    )
                )

                if updated.rowcount != 1:
                    raise ValueError(
                        "Inventory changed while placing your order. "
                        "Please try again."
                    )

            # Save delivery information if required.

            if fulfillment_type == "DELIVERY":

                conn.execute(
                    """
                    INSERT INTO roadready.delivery
                        (
                            order_id,
                            ship_street,
                            ship_city,
                            ship_state,
                            ship_zip,
                            status
                        )
                    VALUES (%s, %s, %s, %s, %s, 'PENDING')
                    """,
                    (
                        order_id,
                        street,
                        city,
                        state,
                        zip_code
                    )
                )

        # The database transaction has committed successfully.

        session.pop("roadready_cart", None)

        return redirect(
            url_for(
                "checkout.order_confirmation",
                order_id=order_id
            )
        )

    except ValueError as error:

        flash(str(error), "error")
        return redirect(url_for("checkout.checkout_page"))

    except Exception:

        current_app.logger.exception("Order placement failed.")

        flash(
            "We could not place your order. Please try again.",
            "error"
        )

        return redirect(url_for("checkout.checkout_page"))


# --------------------------------------------------
# ORDER CONFIRMATION
# --------------------------------------------------

@checkout.route("/orders/<int:order_id>/confirmation")
@login_required
def order_confirmation(order_id):

    with get_db_connection() as conn:

        order = conn.execute(
            """
            SELECT
                o.order_id,
                o.order_date,
                o.status,
                o.fulfillment_type,
                s.store_name,
                s.street,
                s.city,
                s.state,
                s.zip
            FROM roadready.customer_order o
            JOIN roadready.store s
                ON o.store_id = s.store_id
            WHERE o.order_id = %s
                AND o.customer_id = %s
            """,
            (order_id, int(current_user.id))
        ).fetchone()

        if not order:
            flash("Order not found.", "error")
            return redirect(url_for("customer.dashboard"))

        order_lines = conn.execute(
            """
            SELECT
                p.part_name,
                p.part_number,
                sku.condition,
                ol.quantity,
                ol.unit_price
            FROM roadready.order_line ol
            JOIN roadready.part_sku sku
                ON ol.sku_id = sku.sku_id
            JOIN roadready.part p
                ON sku.part_id = p.part_id
            WHERE ol.order_id = %s
            ORDER BY ol.line_no
            """,
            (order_id,)
        ).fetchall()

    order_total = sum(
        line[3] * line[4]
        for line in order_lines
    )

    return render_template(
        "customer/order_confirmation.html",
        order=order,
        order_lines=order_lines,
        order_total=order_total
    )
