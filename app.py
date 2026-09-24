from flask import Flask, render_template

from models import db


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "change-this-before-deployment"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pavement.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/login")
    def login():
        return render_template("login.html")

    @app.route("/customer/dashboard")
    def customer_dashboard():
        return render_template("customer_dashboard.html")

    @app.route("/customer/request/new")
    def request_form():
        return render_template("request_form.html")

    @app.route("/staff/dashboard")
    def staff_dashboard():
        return render_template("staff_dashboard.html")

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
