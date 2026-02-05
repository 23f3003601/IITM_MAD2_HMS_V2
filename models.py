from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __mapper_args__ = {"polymorphic_identity": "user", "polymorphic_on": role}

    # Flask-Login: blacklisted users cannot log in
    @property
    def is_active(self):
        return not self.is_blacklisted

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
        }


class Admin(User):
    __tablename__ = "admins"

    id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)

    __mapper_args__ = {"polymorphic_identity": "admin"}


class Doctor(User):
    __tablename__ = "doctors"

    id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    specialization_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    bio = db.Column(db.Text)
    is_available = db.Column(db.Boolean, default=True)

    specialization = db.relationship("Department", backref="doctors")
    appointments = db.relationship("Appointment", backref="doctor", lazy="dynamic")

    __mapper_args__ = {"polymorphic_identity": "doctor"}

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "bio": self.bio,
            "specialization": self.specialization.name if self.specialization else None,
            "specialization_id": self.specialization_id,
            "is_available": self.is_available,
            "is_blacklisted": self.is_blacklisted,
        }


class Patient(User):
    __tablename__ = "patients"

    id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))
    blood_group = db.Column(db.String(10))

    appointments = db.relationship("Appointment", backref="patient", lazy="dynamic")

    __mapper_args__ = {"polymorphic_identity": "patient"}

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "date_of_birth": self.date_of_birth.isoformat()
            if self.date_of_birth
            else None,
            "gender": self.gender,
            "blood_group": self.blood_group,
            "is_blacklisted": self.is_blacklisted,
        }


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "doctor_count": len(self.doctors) if self.doctors else 0,
        }


class DoctorAvailability(db.Model):
    __tablename__ = "doctor_availability"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_available = db.Column(db.Boolean, default=True)

    doctor = db.relationship("Doctor", backref="availabilities")

    def to_dict(self):
        return {
            "id": self.id,
            "doctor_id": self.doctor_id,
            "date": self.date.isoformat(),
            "start_time": self.start_time.strftime("%H:%M"),
            "end_time": self.end_time.strftime("%H:%M"),
            "is_available": self.is_available,
        }


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), default="Booked")
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "doctor_id": self.doctor_id,
            "doctor_name": self.doctor.username if self.doctor else None,
            "patient_name": self.patient.username if self.patient else None,
            "specialization": self.doctor.specialization.name
            if self.doctor and self.doctor.specialization
            else None,
            "appointment_date": self.appointment_date.isoformat(),
            "appointment_time": self.appointment_time.strftime("%H:%M"),
            "status": self.status,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
        }


class Treatment(db.Model):
    __tablename__ = "treatments"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id"), nullable=False
    )
    diagnosis = db.Column(db.Text, nullable=False)
    prescription = db.Column(db.Text)
    notes = db.Column(db.Text)
    next_visit = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    appointment = db.relationship("Appointment", backref="treatment")

    def to_dict(self):
        return {
            "id": self.id,
            "appointment_id": self.appointment_id,
            "diagnosis": self.diagnosis,
            "prescription": self.prescription,
            "notes": self.notes,
            "next_visit": self.next_visit.isoformat() if self.next_visit else None,
            "created_at": self.created_at.isoformat(),
        }
