from datetime import datetime

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()

PROJECT_TYPES = ["New driveway", "Driveway replacement", "Parking lot", "Resurfacing"]
PAVEMENT_CONDITIONS = ["Good", "Fair", "Poor"]
REQUEST_STATUSES = ["Submitted", "Inspected", "Quoted", "Scheduled", "Completed", "Cancelled"]
PROPOSAL_STATUSES = ["Sent", "Accepted", "Declined", "Expired"]
CONTRACT_STATUSES = ["Draft", "Sent", "Signed", "Completed", "Cancelled"]


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # Optional until login is added; customers are created from the request form.
    password_hash = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="customer")

    properties = db.relationship(
        "Property", back_populates="owner", cascade="all, delete-orphan"
    )
    service_requests = db.relationship(
        "ServiceRequest", back_populates="customer", cascade="all, delete-orphan"
    )
    contracts = db.relationship(
        "Contract", back_populates="customer", cascade="all, delete-orphan"
    )


class Property(db.Model):
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    state = db.Column(db.String(2), nullable=False, default="IL")
    zip_code = db.Column(db.String(10), nullable=False)

    owner = db.relationship("User", back_populates="properties")
    service_requests = db.relationship(
        "ServiceRequest", back_populates="property", cascade="all, delete-orphan"
    )


class ServiceRequest(db.Model):
    __tablename__ = "service_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=False
    )
    project_type = db.Column(db.String(50), nullable=False)
    square_footage = db.Column(db.Integer, nullable=False)
    pavement_condition = db.Column(db.String(30), nullable=False)
    preferred_inspection_date = db.Column(db.Date, nullable=True)
    additional_details = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="Submitted")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    customer = db.relationship("User", back_populates="service_requests")
    property = db.relationship("Property", back_populates="service_requests")
    proposals = db.relationship(
        "Proposal", back_populates="service_request", cascade="all, delete-orphan"
    )


class Proposal(db.Model):
    __tablename__ = "proposals"

    id = db.Column(db.Integer, primary_key=True)
    service_request_id = db.Column(
        db.Integer, db.ForeignKey("service_requests.id"), nullable=False
    )
    # Empty until the proposal is added to a contract. A proposal can only be
    # on one contract, but a contract can hold many proposals.
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    estimated_hours = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="Sent")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True)

    service_request = db.relationship("ServiceRequest", back_populates="proposals")
    contract = db.relationship("Contract", back_populates="proposals")


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Draft")
    # Saved when the contract is created so later proposal changes can't alter it.
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    signed_at = db.Column(db.DateTime, nullable=True)

    customer = db.relationship("User", back_populates="contracts")
    proposals = db.relationship("Proposal", back_populates="contract")
