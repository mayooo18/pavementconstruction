from datetime import datetime

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")

    properties = db.relationship(
        "Property", back_populates="owner", cascade="all, delete-orphan"
    )
    service_requests = db.relationship(
        "ServiceRequest", back_populates="customer", cascade="all, delete-orphan"
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
