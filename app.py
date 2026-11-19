
from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from config import Config
from db import get_db_connection
from models import User

from routes.auth import auth
from routes.customer import customer
from routes.vehicles import vehicles
from routes.parts import parts
from routes.product_details import product_details
from routes.cart import cart


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CSRF protection
    CSRFProtect(app)

    # Configure customer login management
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(customer_id):
        return User.get_by_id(customer_id)

    # Register each blueprint exactly once
    app.register_blueprint(auth)
    app.register_blueprint(customer)
    app.register_blueprint(vehicles)
    app.register_blueprint(parts)
    app.register_blueprint(product_details)
    app.register_blueprint(cart)
    @app.route("/test-db")
    def test_db():
        try:
            with get_db_connection() as conn:
                result = conn.execute(
                    "SELECT current_database(), current_schema()"
                ).fetchone()

            return {
                "status": "success",
                "database": result[0],
                "schema": result[1]
            }

        except Exception:
            app.logger.exception("Database connection test failed")
            return {
                "status": "error",
                "message": "Database connection failed."
            }, 500

    @app.route("/")
    def home():
        return "Welcome to RoadReady!"

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
