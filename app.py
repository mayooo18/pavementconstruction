import os
from datetime import date
from getpass import getpass

import joblib
import pandas as pd
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

from models import (
    PAVEMENT_CONDITIONS,
    PROJECT_TYPES,
    REQUEST_STATUSES,
    STREET_TYPES,
    Property,
    ServiceRequest,
    User,
    db,
)


# Load the pavement condition model once, when the app starts.
MODEL_PATH = os.path.join(os.path.dirname(__file__), "ml", "pavement_condition_model.joblib")
condition_model = joblib.load(MODEL_PATH)

# The model was trained with a number for each street type (step 3 of the notebook).
STREET_TYPE_NUMBERS = {"AV": 0, "BL": 1, "CT": 2, "DR": 3, "LN": 4, "OTHER": 5, "PL": 6, "RD": 7, "ST": 8, "WY": 9}


def condition_rating(score):
    """Turn a 0-100 condition score into the city's rating name."""
    if score >= 85:
        return "Good"
    elif score >= 70:
        return "Satisfactory"
    elif score >= 55:
        return "Fair"
    elif score >= 40:
        return "Poor"
    elif score >= 25:
        return "Very Poor"
    elif score >= 10:
        return "Serious"
    else:
        return "Failed"


def predict_condition(service_request):
    """Predict a parking lot's condition score. Returns None if the customer didn't give both years."""
    if service_request.years_since_paved is None or service_request.years_since_sealed is None:
        return None

    lot = pd.DataFrame([{
        "years_since_repaved": service_request.years_since_paved,
        "years_since_sealed": service_request.years_since_sealed,
        "street_type_number": STREET_TYPE_NUMBERS[service_request.street_type or "OTHER"],
    }])
    score = round(condition_model.predict(lot)[0])
    return {"score": score, "rating": condition_rating(score)}


def add_missing_columns():
    """Databases made before these columns existed don't have them, so add any that are missing."""
    rows = db.session.execute(db.text("PRAGMA table_info(service_requests)")).fetchall()
    column_names = [row[1] for row in rows]

    if "years_since_paved" not in column_names:
        db.session.execute(db.text("ALTER TABLE service_requests ADD COLUMN years_since_paved INTEGER"))
    if "years_since_sealed" not in column_names:
        db.session.execute(db.text("ALTER TABLE service_requests ADD COLUMN years_since_sealed INTEGER"))
    if "street_type" not in column_names:
        db.session.execute(db.text("ALTER TABLE service_requests ADD COLUMN street_type VARCHAR(10)"))
    db.session.commit()


def years_or_none(text):
    """Turn a typed number of years into an int, or None if it was left blank."""
    text = text.strip()
    if text == "":
        return None
    return int(text)


def check_form(form, logged_in):
    """Check the request form and return a list of problems (empty if it's fine)."""
    errors = []

    # These fields must be filled in.
    required = ["address", "city", "state", "zip_code", "square_footage"]
    # People who aren't logged in also make an account with this form.
    if not logged_in:
        required = ["name", "email", "password"] + required

    for field in required:
        if form.get(field, "").strip() == "":
            errors.append(field.replace("_", " ").capitalize() + " is required.")

    if not logged_in:
        email = form.get("email", "")
        if email and ("@" not in email or "." not in email):
            errors.append("Enter a valid email address.")

        password = form.get("password", "")
        if password and len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != form.get("confirm_password", ""):
            errors.append("The two passwords don't match.")

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

    # Parking lot questions are optional, but must be whole numbers if filled in.
    if form.get("project_type") == "Parking lot":
        for field, label in [("years_since_paved", "Years since it was paved"), ("years_since_sealed", "Years since it was sealed")]:
            years = form.get(field, "").strip()
            if years and (not years.isdigit() or int(years) > 100):
                errors.append(label + " must be a whole number from 0 to 100.")
        street_type = form.get("street_type", "")
        if street_type and street_type not in STREET_TYPES:
            errors.append("Choose a street type from the list.")

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
        add_missing_columns()

    # ---------- Logging in ----------
    login_manager = LoginManager()
    login_manager.login_view = "login"  # where to send people who need to log in
    login_manager.login_message = "Please log in to see that page."
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        # Flask-Login remembers who is logged in by their id. This turns the id back into a User.
        return db.session.get(User, int(user_id))

    def block_non_staff():
        """Staff pages call this first. It sends anyone who isn't staff to the login page."""
        if current_user.is_authenticated and current_user.is_staff():
            return None
        flash("Please log in with a staff account to see that page.", "danger")
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        email = ""

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()

            if user is not None and user.check_password(password):
                login_user(user)
                flash(f"Welcome back, {user.name}.", "success")

                # Go back to the page they were trying to open, if there was one.
                # It must start with "/" so nobody can send people to another website.
                next_page = request.args.get("next", "")
                if next_page.startswith("/") and not next_page.startswith("//"):
                    return redirect(next_page)
                if user.is_staff():
                    return redirect(url_for("staff_dashboard"))
                return redirect(url_for("customer_dashboard"))

            error = "That email and password don't match an account."

        return render_template("login.html", error=error, email=email)

    @app.route("/logout", methods=["POST"])
    def logout():
        logout_user()
        flash("You're logged out.", "success")
        return redirect(url_for("home"))

    @app.cli.command("create-staff")
    def create_staff():
        """Make a staff account from the terminal: flask --app app:create_app create-staff"""
        name = input("Name: ").strip()
        email = input("Email: ").strip().lower()
        password = getpass("Password (at least 8 characters): ")

        if name == "" or "@" not in email:
            print("Enter a name and a valid email.")
            return
        if len(password) < 8:
            print("The password must be at least 8 characters.")
            return

        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(name=name, email=email)
            db.session.add(user)
        user.role = "staff"
        user.set_password(password)
        db.session.commit()
        print(f"Staff account ready for {email}. Log in at /login.")

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/services")
    def services():
        return render_template("services.html")

    @app.route("/about")
    def about():
        return render_template("about.html")

    @app.route("/contact")
    def contact():
        return render_template("contact.html")

    @app.route("/faq")
    def faq():
        return render_template("faq.html")

    # Lets every page use {{ current_year }}, for the footer.
    @app.context_processor
    def add_current_year():
        return {"current_year": date.today().year}

    @app.route("/customer/dashboard")
    @login_required
    def customer_dashboard():
        # Staff don't have requests of their own, so send them to their page.
        if current_user.is_staff():
            return redirect(url_for("staff_dashboard"))

        # Only show the logged-in customer's own requests, newest first.
        requests = (
            ServiceRequest.query.filter_by(user_id=current_user.id)
            .order_by(ServiceRequest.created_at.desc())
            .all()
        )
        return render_template("customer_dashboard.html", requests=requests)

    @app.route("/customer/request/new", methods=["GET", "POST"])
    def request_form():
        if current_user.is_authenticated and current_user.is_staff():
            flash("Staff accounts can't send service requests. Log out first.", "danger")
            return redirect(url_for("staff_dashboard"))

        logged_in = current_user.is_authenticated
        errors = []

        if request.method == "POST":
            form = request.form
            errors = check_form(form, logged_in)

            if len(errors) == 0:
                if logged_in:
                    # The request belongs to whoever is logged in.
                    user = db.session.get(User, current_user.id)
                else:
                    email = form["email"].strip().lower()
                    user = User.query.filter_by(email=email).first()

                    if user is not None and user.password_hash is not None:
                        # This email already has an account, so they need to log in.
                        # Otherwise anyone could add requests to someone else's account.
                        errors.append("An account with this email already exists. Log in first, then send your request.")
                    elif user is None:
                        # New customer: make an account.
                        user = User(name=form["name"].strip(), email=email, role="customer")
                        db.session.add(user)

                    # New customers, and customers from before accounts existed, get this password.
                    if len(errors) == 0:
                        user.set_password(form["password"])

            # Everything checks out, so save the property and the request.
            if len(errors) == 0:
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
                # Only parking lots get the condition questions.
                if new_request.project_type == "Parking lot":
                    new_request.years_since_paved = years_or_none(form.get("years_since_paved", ""))
                    new_request.years_since_sealed = years_or_none(form.get("years_since_sealed", ""))
                    new_request.street_type = form.get("street_type") or "OTHER"

                db.session.add(new_request)
                db.session.commit()

                # Log new customers in, so they can see My requests right away.
                if not logged_in:
                    login_user(user)
                return redirect(url_for("request_submitted", request_id=new_request.id))

        # Show the form (empty the first time, or with the user's answers if there were errors).
        return render_template(
            "request_form.html",
            form=request.form,
            errors=errors,
            logged_in=logged_in,
            project_types=PROJECT_TYPES,
            conditions=PAVEMENT_CONDITIONS,
            street_types=STREET_TYPES,
        )

    @app.route("/customer/request/<int:request_id>/submitted")
    @login_required
    def request_submitted(request_id):
        service_request = db.get_or_404(ServiceRequest, request_id)

        # Only the customer who sent it (or staff) can see this page.
        # Everyone else gets "not found", so they can't even tell the request exists.
        if service_request.user_id != current_user.id and not current_user.is_staff():
            abort(404)

        return render_template("request_submitted.html", req=service_request)

    @app.route("/staff/dashboard")
    def staff_dashboard():
        blocked = block_non_staff()
        if blocked:
            return blocked
        # Newest requests first.
        requests = ServiceRequest.query.order_by(ServiceRequest.created_at.desc()).all()

        # Predicted condition for each parking lot that has both years filled in.
        predictions = {}
        for service_request in requests:
            predictions[service_request.id] = predict_condition(service_request)

        return render_template(
            "staff_dashboard.html",
            requests=requests,
            statuses=REQUEST_STATUSES,
            predictions=predictions,
        )

    @app.route("/staff/request/<int:request_id>/status", methods=["POST"])
    def update_request_status(request_id):
        blocked = block_non_staff()
        if blocked:
            return blocked
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
