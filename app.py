import os
from datetime import date

from flask import Flask, flash, redirect, render_template, request, url_for

from models import (
    PAVEMENT_CONDITIONS,
    PROJECT_TYPES,
    REQUEST_STATUSES,
    Property,
    ServiceRequest,
    User,
    db,
)


def check_form(form):
    """Check the request form and return a list of problems (empty if it's fine)."""
    errors = []

    # These fields must be filled in.
    required = ["name", "email", "address", "city", "state", "zip_code", "square_footage"]
    for field in required:
        if form.get(field, "").strip() == "":
            errors.append(field.replace("_", " ").capitalize() + " is required.")

    email = form.get("email", "")
    if email and ("@" not in email or "." not in email):
        errors.append("Enter a valid email address.")

    state = form.get("state", "")
    if state and (len(state) != 2 or not state.isalpha()):
        errors.append("State must be a two-letter code, like IL.")

    zip_code = form.get("zip_code", "")
    if zip_code and (len(zip_code) != 5 or not zip_code.isdigit()):
        errors.append("ZIP code must be 5 digits.")

    square_footage = form.get("square_footage", "")
    if square_footage and (not square_footage.isdigit() or int(square_footage) == 0):
        errors.append("Square footage must be a whole number greater than 0.")

    if form.get("project_type") not in PROJECT_TYPES:
        errors.append("Choose a project type.")

    if form.get("pavement_condition") not in PAVEMENT_CONDITIONS:
        errors.append("Choose a pavement condition.")

    inspection_date = form.get("preferred_inspection_date", "")
    if inspection_date and inspection_date < date.today().isoformat():
        errors.append("The inspection date can't be in the past.")

    return errors


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
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

    @app.route("/customer/request/new", methods=["GET", "POST"])
    def request_form():
        errors = []

        if request.method == "POST":
            form = request.form
            errors = check_form(form)

            if len(errors) == 0:
                # Find the customer by email, or create a new one.
                email = form["email"].lower()
                user = User.query.filter_by(email=email).first()
                if user is None:
                    user = User(name=form["name"], email=email, role="customer")
                    db.session.add(user)

                new_property = Property(
                    owner=user,
                    address=form["address"],
                    city=form["city"],
                    state=form["state"].upper(),
                    zip_code=form["zip_code"],
                )

                inspection_date = None
                if form.get("preferred_inspection_date"):
                    inspection_date = date.fromisoformat(form["preferred_inspection_date"])

                new_request = ServiceRequest(
                    customer=user,
                    property=new_property,
                    project_type=form["project_type"],
                    square_footage=int(form["square_footage"]),
                    pavement_condition=form["pavement_condition"],
                    preferred_inspection_date=inspection_date,
                    additional_details=form.get("additional_details"),
                )
                db.session.add(new_request)
                db.session.commit()
                return redirect(url_for("request_submitted", request_id=new_request.id))

        # Show the form (empty the first time, or with the user's answers if there were errors).
        return render_template(
            "request_form.html",
            form=request.form,
            errors=errors,
            project_types=PROJECT_TYPES,
            conditions=PAVEMENT_CONDITIONS,
        )

    @app.route("/customer/request/<int:request_id>/submitted")
    def request_submitted(request_id):
        service_request = db.get_or_404(ServiceRequest, request_id)
        return render_template("request_submitted.html", req=service_request)

    @app.route("/staff/dashboard")
    def staff_dashboard():
        # Newest requests first.
        requests = ServiceRequest.query.order_by(ServiceRequest.created_at.desc()).all()
        return render_template(
            "staff_dashboard.html", requests=requests, statuses=REQUEST_STATUSES
        )

    @app.route("/staff/request/<int:request_id>/status", methods=["POST"])
    def update_request_status(request_id):
        service_request = db.get_or_404(ServiceRequest, request_id)
        new_status = request.form.get("status")

        if new_status in REQUEST_STATUSES:
            service_request.status = new_status
            db.session.commit()
            flash(f"Request #{request_id} marked as {new_status}.", "success")

        return redirect(url_for("staff_dashboard"))

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
