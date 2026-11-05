import os
from datetime import date

import joblib
import pandas as pd
from flask import Flask, flash, redirect, render_template, request, session, url_for

from models import (
    PAVEMENT_CONDITIONS,
    PROJECT_TYPES,
    REQUEST_STATUSES,
    Property,
    ServiceRequest,
    User,
    db,
)


# Load the work hours model once, when the app starts.
MODEL_PATH = os.path.join(os.path.dirname(__file__), "ml", "work_hours_model.joblib")
work_hours_model = joblib.load(MODEL_PATH)

# The model was trained with numbers instead of words (see the notebook).
TYPE_NUMBERS = {"New driveway": 1, "Driveway replacement": 2, "Parking lot": 3, "Resurfacing": 4}
CONDITION_NUMBERS = {"Good": 1, "Fair": 2, "Poor": 3}


# Customers don't know the thickness or crew size, so the customer ballpark
# uses a typical value for each project type (the middle of the ranges in the notebook).
TYPICAL_JOB = {
    "New driveway": {"thickness": 2.5, "crew_size": 4},
    "Driveway replacement": {"thickness": 2.5, "crew_size": 4},
    "Parking lot": {"thickness": 3.5, "crew_size": 6},
    "Resurfacing": {"thickness": 2, "crew_size": 4},
}


def predict_hours(project_type, square_footage, thickness, crew_size, condition):
    """Ask the model how many work hours a job will take."""
    project = pd.DataFrame([{
        "square_footage": square_footage,
        "thickness": thickness,
        "crew_size": crew_size,
        "type_number": TYPE_NUMBERS[project_type],
        "condition_number": CONDITION_NUMBERS[condition],
    }])
    guess = work_hours_model.predict(project)[0]
    return round(guess, 1)


def estimate_hours(service_request):
    """Staff estimate: return work hours, or None if staff haven't entered thickness and crew size."""
    if service_request.thickness is None or service_request.crew_size is None:
        return None

    return predict_hours(
        service_request.project_type,
        service_request.square_footage,
        service_request.thickness,
        service_request.crew_size,
        service_request.pavement_condition,
    )


def ballpark_hours(service_request):
    """Customer ballpark: the estimate for a typical job of this type and size, rounded to whole hours."""
    typical = TYPICAL_JOB[service_request.project_type]
    hours = predict_hours(
        service_request.project_type,
        service_request.square_footage,
        typical["thickness"],
        typical["crew_size"],
        service_request.pavement_condition,
    )
    return round(hours)


def add_missing_columns():
    """Databases made before these columns existed don't have them, so add any that are missing."""
    rows = db.session.execute(db.text("PRAGMA table_info(service_requests)")).fetchall()
    column_names = [row[1] for row in rows]

    if "thickness" not in column_names:
        db.session.execute(db.text("ALTER TABLE service_requests ADD COLUMN thickness FLOAT"))
    if "crew_size" not in column_names:
        db.session.execute(db.text("ALTER TABLE service_requests ADD COLUMN crew_size INTEGER"))
    if "actual_hours" not in column_names:
        db.session.execute(db.text("ALTER TABLE service_requests ADD COLUMN actual_hours FLOAT"))
    db.session.commit()


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
        add_missing_columns()

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
    def customer_dashboard():
        # No login yet, so look the customer up by email (from the search box,
        # or remembered from the last request they submitted).
        email = request.args.get("email", "").strip().lower()
        if email:
            session["customer_email"] = email
        else:
            email = session.get("customer_email", "")

        requests = []
        if email:
            user = User.query.filter_by(email=email).first()
            if user is not None:
                requests = (
                    ServiceRequest.query.filter_by(customer=user)
                    .order_by(ServiceRequest.created_at.desc())
                    .all()
                )

        return render_template("customer_dashboard.html", email=email, requests=requests)

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
                session["customer_email"] = email
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
        return render_template(
            "request_submitted.html",
            req=service_request,
            ballpark=ballpark_hours(service_request),
        )

    @app.route("/staff/dashboard")
    def staff_dashboard():
        # Newest requests first.
        requests = ServiceRequest.query.order_by(ServiceRequest.created_at.desc()).all()
        # Work out the estimate for each request, if staff have entered the details.
        estimates = {}
        for service_request in requests:
            estimates[service_request.id] = estimate_hours(service_request)

        # Count finished jobs that are ready to use as training data.
        training_jobs = 0
        for service_request in requests:
            if (
                service_request.status == "Completed"
                and service_request.actual_hours is not None
                and estimates[service_request.id] is not None
            ):
                training_jobs += 1

        return render_template(
            "staff_dashboard.html",
            requests=requests,
            statuses=REQUEST_STATUSES,
            estimates=estimates,
            training_jobs=training_jobs,
        )

    @app.route("/staff/request/<int:request_id>/estimate", methods=["POST"])
    def update_request_estimate(request_id):
        service_request = db.get_or_404(ServiceRequest, request_id)
        thickness = request.form.get("thickness", "").strip()
        crew_size = request.form.get("crew_size", "").strip()

        # Thickness can have a decimal, like 2.5. Crew size must be a whole number.
        try:
            thickness = float(thickness)
        except ValueError:
            thickness = 0

        if thickness < 0.5 or thickness > 12:
            flash(f"Request #{request_id}: thickness must be a number from 0.5 to 12 inches.", "danger")
        elif not crew_size.isdigit() or int(crew_size) < 1 or int(crew_size) > 20:
            flash(f"Request #{request_id}: crew size must be a whole number from 1 to 20.", "danger")
        else:
            service_request.thickness = thickness
            service_request.crew_size = int(crew_size)
            db.session.commit()
            flash(
                f"Request #{request_id}: estimated {estimate_hours(service_request)} work hours.",
                "success",
            )

        return redirect(url_for("staff_dashboard"))

    @app.route("/staff/request/<int:request_id>/status", methods=["POST"])
    def update_request_status(request_id):
        service_request = db.get_or_404(ServiceRequest, request_id)
        new_status = request.form.get("status")

        if new_status in REQUEST_STATUSES:
            service_request.status = new_status
            db.session.commit()
            flash(f"Request #{request_id} marked as {new_status}.", "success")

        return redirect(url_for("staff_dashboard"))

    @app.route("/staff/request/<int:request_id>/actual-hours", methods=["POST"])
    def update_actual_hours(request_id):
        service_request = db.get_or_404(ServiceRequest, request_id)

        try:
            hours = float(request.form.get("actual_hours", ""))
        except ValueError:
            hours = 0

        if service_request.status != "Completed":
            flash(f"Request #{request_id}: mark the job Completed before entering actual hours.", "danger")
        elif hours < 0.5 or hours > 1000:
            flash(f"Request #{request_id}: actual hours must be a number from 0.5 to 1000.", "danger")
        else:
            service_request.actual_hours = hours
            db.session.commit()
            flash(f"Request #{request_id}: saved {hours} actual work hours.", "success")

        return redirect(url_for("staff_dashboard"))

    @app.route("/staff/completed-jobs.csv")
    def download_completed_jobs():
        # Only finished jobs with every detail the model needs can be used for training.
        jobs = ServiceRequest.query.filter(
            ServiceRequest.status == "Completed",
            ServiceRequest.actual_hours.isnot(None),
            ServiceRequest.thickness.isnot(None),
            ServiceRequest.crew_size.isnot(None),
        ).all()

        # Same columns as ml/past_projects.csv, so the notebook can train on it.
        rows = []
        for job in jobs:
            rows.append({
                "project_type": job.project_type,
                "square_footage": job.square_footage,
                "thickness": job.thickness,
                "crew_size": job.crew_size,
                "condition": job.pavement_condition,
                "work_hours": job.actual_hours,
            })
        columns = ["project_type", "square_footage", "thickness", "crew_size", "condition", "work_hours"]
        csv_text = pd.DataFrame(rows, columns=columns).to_csv(index=False)

        return app.response_class(
            csv_text,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=completed_jobs.csv"},
        )

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
