import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Flask, flash, redirect, render_template, request, url_for

from models import (
    CONTRACT_STATUSES,
    PAVEMENT_CONDITIONS,
    PROJECT_TYPES,
    PROPOSAL_STATUSES,
    REQUEST_STATUSES,
    Contract,
    Property,
    Proposal,
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


def check_contract_proposals(proposals):
    """Check that proposals can go on one contract and return a list of problems."""
    if len(proposals) == 0:
        return ["Select at least one accepted proposal."]

    errors = []
    for proposal in proposals:
        if proposal.status != "Accepted":
            errors.append(f"Proposal #{proposal.id} has not been accepted.")
        if proposal.contract_id is not None:
            errors.append(f"Proposal #{proposal.id} is already on contract #{proposal.contract_id}.")

    customer_ids = {p.service_request.user_id for p in proposals}
    if len(customer_ids) > 1:
        errors.append("All proposals on a contract must belong to the same customer.")

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
        proposals = Proposal.query.order_by(Proposal.created_at.desc()).all()
        contracts = Contract.query.order_by(Contract.created_at.desc()).all()
        return render_template(
            "staff_dashboard.html",
            requests=requests,
            statuses=REQUEST_STATUSES,
            proposals=proposals,
            proposal_statuses=PROPOSAL_STATUSES,
            contracts=contracts,
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

    @app.route("/staff/request/<int:request_id>/proposals", methods=["POST"])
    def create_proposal(request_id):
        service_request = db.get_or_404(ServiceRequest, request_id)

        try:
            price = Decimal(request.form.get("price", ""))
        except InvalidOperation:
            price = None
        if price is None or not price.is_finite() or price <= 0:
            flash("Enter a price greater than 0.", "danger")
            return redirect(url_for("staff_dashboard"))

        proposal = Proposal(
            service_request=service_request, price=price.quantize(Decimal("0.01"))
        )
        service_request.status = "Quoted"
        db.session.add(proposal)
        db.session.commit()
        flash(f"Proposal #{proposal.id} created for request #{request_id}.", "success")
        return redirect(url_for("staff_dashboard"))

    @app.route("/staff/proposal/<int:proposal_id>/status", methods=["POST"])
    def update_proposal_status(proposal_id):
        proposal = db.get_or_404(Proposal, proposal_id)
        new_status = request.form.get("status")

        # A proposal on a contract is locked so the contract stays accurate.
        if proposal.contract_id is not None:
            flash(f"Proposal #{proposal_id} is on contract #{proposal.contract_id} and can't be changed.", "danger")
        elif new_status in PROPOSAL_STATUSES:
            proposal.status = new_status
            proposal.accepted_at = datetime.utcnow() if new_status == "Accepted" else None
            db.session.commit()
            flash(f"Proposal #{proposal_id} marked as {new_status}.", "success")

        return redirect(url_for("staff_dashboard"))

    @app.route("/staff/contracts", methods=["POST"])
    def create_contract():
        proposal_ids = request.form.getlist("proposal_ids", type=int)
        proposals = Proposal.query.filter(Proposal.id.in_(proposal_ids)).all()

        errors = check_contract_proposals(proposals)
        if len(errors) > 0:
            for error in errors:
                flash(error, "danger")
            return redirect(url_for("staff_dashboard"))

        contract = Contract(
            customer=proposals[0].service_request.customer,
            total_price=sum(p.price for p in proposals),
            proposals=proposals,
        )
        for proposal in proposals:
            proposal.service_request.status = "Scheduled"
        db.session.add(contract)
        db.session.commit()
        flash(f"Contract #{contract.id} created with {len(proposals)} proposal(s).", "success")
        return redirect(url_for("contract_detail", contract_id=contract.id))

    @app.route("/staff/contract/<int:contract_id>")
    def contract_detail(contract_id):
        contract = db.get_or_404(Contract, contract_id)
        return render_template(
            "contract_detail.html", contract=contract, statuses=CONTRACT_STATUSES
        )

    @app.route("/staff/contract/<int:contract_id>/status", methods=["POST"])
    def update_contract_status(contract_id):
        contract = db.get_or_404(Contract, contract_id)
        new_status = request.form.get("status")

        if new_status not in CONTRACT_STATUSES or new_status == contract.status:
            return redirect(url_for("contract_detail", contract_id=contract_id))
        # Cancelled contracts have released their proposals, so they stay cancelled.
        if contract.status == "Cancelled":
            flash(f"Contract #{contract_id} is cancelled and can't be changed.", "danger")
            return redirect(url_for("contract_detail", contract_id=contract_id))
        if contract.status == "Completed" and new_status == "Cancelled":
            flash(f"Contract #{contract_id} is completed and can't be cancelled.", "danger")
            return redirect(url_for("contract_detail", contract_id=contract_id))

        contract.status = new_status
        if new_status == "Signed" and contract.signed_at is None:
            contract.signed_at = datetime.utcnow()

        if new_status == "Completed":
            for proposal in contract.proposals:
                proposal.service_request.status = "Completed"
        elif new_status == "Cancelled":
            # Release the proposals so they can go on a new contract.
            released = len(contract.proposals)
            for proposal in contract.proposals:
                proposal.service_request.status = "Quoted"
            contract.proposals = []
            flash(f"{released} proposal(s) released and can go on a new contract.", "info")

        db.session.commit()
        flash(f"Contract #{contract_id} marked as {new_status}.", "success")
        return redirect(url_for("contract_detail", contract_id=contract_id))

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
