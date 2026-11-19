
from flask_login import UserMixin
from db import get_db_connection


class User(UserMixin):

    def __init__(self, customer_id, username, first_name, last_name, email):
        self.id = str(customer_id)
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.email = email

    @classmethod
    def get_by_id(cls, customer_id):
        try:
            customer_id = int(customer_id)
        except (ValueError, TypeError):
            return None

        with get_db_connection() as conn:
            customer = conn.execute(
                """
                SELECT customer_id, username, first_name,
                       last_name, email
                FROM roadready.customer
                WHERE customer_id = %s
                """,
                (customer_id,)
            ).fetchone()

        if customer is None:
            return None

        return cls(*customer)
