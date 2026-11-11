from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()

PROJECT_TYPES = ["New driveway", "Driveway replacement", "Parking lot", "Resurfacing"]
PAVEMENT_CONDITIONS = ["Good", "Fair", "Poor"]
REQUEST_STATUSES = ["Submitted", "Inspected", "Quoted", "Scheduled", "Completed", "Cancelled"]


# UserMixin gives the User class what Flask-Login needs to log people in.
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # Customers from before login existed don't have a password yet,
    # so this can be empty. They set one the next time they send a request.
    password_hash = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="customer")

    properties = db.relationship(
        "Property", back_populates="owner", cascade="all, delete-orphan"
    )
    service_requests = db.relationship(
        "ServiceRequest", back_populates="customer", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        # Never save the real password. Save a scrambled version (a "hash") instead.
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # True if the password matches the saved hash.
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    def is_staff(self):
        return self.role == "staff"


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
    # Staff fill these in after the inspection so the model can estimate work hours.
    thickness = db.Column(db.Float, nullable=True)
    crew_size = db.Column(db.Integer, nullable=True)
    # How long the job really took. Staff enter it when the job is Completed,
    # and it becomes training data for the work hours model.
    actual_hours = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    customer = db.relationship("User", back_populates="service_requests")
    property = db.relationship("Property", back_populates="service_requests")
