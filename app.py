from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from functools import wraps
import redis
from celery import Celery
from datetime import datetime, timedelta, date, time
import json
import csv
import io
from flask_mail import Mail, Message
import smtplib

from config import Config
from models import (
    db,
    User,
    Admin,
    Doctor,
    Patient,
    Department,
    DoctorAvailability,
    Appointment,
    Treatment,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.from_object(Config)

CORS(app)
db.init_app(app)
mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

celery = Celery(app.name, broker=Config.CELERY_BROKER_URL)
celery.conf.update(app.config)

redis_client = redis.Redis.from_url(Config.REDIS_URL, decode_responses=True)


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    if user:
        if user.role == "admin":
            return Admin.query.get(user.id)
        elif user.role == "doctor":
            return Doctor.query.get(user.id)
        elif user.role == "patient":
            return Patient.query.get(user.id)
    return None


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({"error": "Unauthorized"}), 401
            if current_user.role not in roles:
                return jsonify({"error": "Forbidden"}), 403
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def cache_key(*args):
    return ":".join(str(arg) for arg in args)


def get_cached(key, func, timeout=300):
    cached = redis_client.get(key)
    if cached:
        return json.loads(cached)
    result = func()
    redis_client.setex(key, timeout, json.dumps(result))
    return result


def invalidate_cache(pattern):
    keys = redis_client.keys(pattern)
    if keys:
        redis_client.delete(*keys)


@app.route("/")
def index():
    import os

    path = os.path.join(app.root_path, "templates", "index.html")
    with open(path, "r") as f:
        content = f.read()
    from flask import Response

    return Response(content, mimetype="text/html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    required = ["username", "email", "password"]
    for f in required:
        if not data.get(f, "").strip():
            return jsonify({"error": f"{f} is required"}), 400

    if len(data["password"]) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already exists"}), 400

    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already exists"}), 400

    patient = Patient(
        username=data["username"],
        email=data["email"],
        role="patient",
        phone=data.get("phone", ""),
        address=data.get("address", ""),
        date_of_birth=datetime.strptime(data["date_of_birth"], "%Y-%m-%d").date()
        if data.get("date_of_birth")
        else None,
        gender=data.get("gender", ""),
        blood_group=data.get("blood_group", ""),
    )
    patient.set_password(data["password"])

    db.session.add(patient)
    db.session.commit()

    return jsonify(
        {"message": "Patient registered successfully", "user": patient.to_dict()}
    ), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"error": "Username and password are required"}), 400
    user = User.query.filter_by(username=data["username"]).first()

    if not user or not user.check_password(data["password"]):
        return jsonify({"error": "Invalid credentials"}), 401

    if user.is_blacklisted:
        return jsonify(
            {"error": "Your account has been suspended. Contact admin."}
        ), 403

    login_user(user)
    session["user_id"] = user.id
    session["role"] = user.role

    return jsonify(
        {"message": "Login successful", "user": user.to_dict(), "role": user.role}
    )


@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    return jsonify({"message": "Logged out successfully"})


@app.route("/api/current-user", methods=["GET"])
@login_required
def current_user_info():
    return jsonify({"user": current_user.to_dict(), "role": current_user.role})


@app.route("/api/departments", methods=["GET"])
def get_departments():
    def fetch():
        departments = Department.query.all()
        return [d.to_dict() for d in departments]

    cached = redis_client.get("departments:all")
    if cached:
        return jsonify(json.loads(cached))

    result = fetch()
    redis_client.setex("departments:all", 300, json.dumps(result))
    return jsonify(result)


@app.route("/api/departments", methods=["POST"])
@login_required
@role_required("admin")
def create_department():
    data = request.get_json()
    dept = Department(name=data["name"], description=data.get("description", ""))
    db.session.add(dept)
    db.session.commit()
    invalidate_cache("departments:*")
    return jsonify(dept.to_dict()), 201


@app.route("/api/doctors", methods=["GET"])
def get_doctors():
    specialization = request.args.get("specialization")
    search = request.args.get("search")

    cache_key_str = f"doctors:specialization:{specialization}:search:{search}"
    cached = redis_client.get(cache_key_str)
    if cached:
        return jsonify(json.loads(cached))

    query = Doctor.query
    if specialization:
        query = query.join(Department).filter(
            Department.name.ilike(f"%{specialization}%")
        )
    if search:
        query = query.filter(Doctor.username.ilike(f"%{search}%"))

    doctors = query.all()
    result = [d.to_dict() for d in doctors]
    redis_client.setex(cache_key_str, 300, json.dumps(result))
    return jsonify(result)


@app.route("/api/doctors", methods=["POST"])
@login_required
@role_required("admin")
def create_doctor():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    for f in ["username", "email", "password"]:
        if not data.get(f, "").strip():
            return jsonify({"error": f"{f} is required"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already exists"}), 400

    doctor = Doctor(
        username=data["username"],
        email=data["email"],
        role="doctor",
        specialization_id=data.get("specialization_id"),
        phone=data.get("phone", ""),
        address=data.get("address", ""),
        bio=data.get("bio", ""),
        is_available=data.get("is_available", True),
    )
    doctor.set_password(data["password"])

    db.session.add(doctor)
    db.session.commit()

    invalidate_cache("doctors:*")
    return jsonify(doctor.to_dict()), 201


@app.route("/api/doctors/<int:doctor_id>", methods=["PUT"])
@login_required
@role_required("admin", "doctor")
def update_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    data = request.get_json()

    if current_user.role == "doctor" and current_user.id != doctor_id:
        return jsonify({"error": "Forbidden"}), 403

    if "username" in data:
        doctor.username = data["username"]
    if "email" in data:
        doctor.email = data["email"]
    if "phone" in data:
        doctor.phone = data["phone"]
    if "address" in data:
        doctor.address = data["address"]
    if "bio" in data:
        doctor.bio = data["bio"]
    if "specialization_id" in data and current_user.role == "admin":
        doctor.specialization_id = data["specialization_id"]
    if "is_available" in data and current_user.role == "admin":
        doctor.is_available = data["is_available"]
    if "password" in data:
        doctor.set_password(data["password"])

    db.session.commit()
    invalidate_cache("doctors:*")
    return jsonify(doctor.to_dict())


@app.route("/api/doctors/<int:doctor_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    db.session.delete(doctor)
    db.session.commit()
    invalidate_cache("doctors:*")
    return jsonify({"message": "Doctor deleted successfully"})


@app.route("/api/doctors/<int:doctor_id>/blacklist", methods=["POST"])
@login_required
@role_required("admin")
def blacklist_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    data = request.get_json() or {}
    doctor.is_blacklisted = data.get("blacklist", True)
    db.session.commit()
    invalidate_cache("doctors:*")
    action = "blacklisted" if doctor.is_blacklisted else "reinstated"
    return jsonify(
        {
            "message": f"Doctor {action} successfully",
            "is_blacklisted": doctor.is_blacklisted,
        }
    )



@app.route("/api/patients", methods=["GET"])
@login_required
def get_patients():
    search = request.args.get("search", "").strip()

    query = Patient.query
    if search:
        filters = [
            Patient.username.ilike(f"%{search}%"),
            Patient.email.ilike(f"%{search}%"),
            Patient.phone.ilike(f"%{search}%"),
        ]
        if search.isdigit():
            filters.append(Patient.id == int(search))
        from sqlalchemy import or_

        query = query.filter(or_(*filters))

    patients = query.all()
    return jsonify([p.to_dict() for p in patients])


@app.route("/api/patients/<int:patient_id>", methods=["GET"])
@login_required
@role_required("admin", "doctor", "patient")
def get_patient(patient_id):
    if current_user.role == "patient" and current_user.id != patient_id:
        return jsonify({"error": "Forbidden"}), 403

    patient = Patient.query.get_or_404(patient_id)
    return jsonify(patient.to_dict())


@app.route("/api/patients/<int:patient_id>", methods=["PUT"])
@login_required
@role_required("admin", "patient")
def update_patient(patient_id):
    if current_user.role == "patient" and current_user.id != patient_id:
        return jsonify({"error": "Forbidden"}), 403

    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()

    if "username" in data:
        patient.username = data["username"]
    if "email" in data:
        patient.email = data["email"]
    if "phone" in data:
        patient.phone = data["phone"]
    if "address" in data:
        patient.address = data["address"]
    if "date_of_birth" in data:
        patient.date_of_birth = datetime.strptime(
            data["date_of_birth"], "%Y-%m-%d"
        ).date()
    if "gender" in data:
        patient.gender = data["gender"]
    if "blood_group" in data:
        patient.blood_group = data["blood_group"]
    if "password" in data:
        patient.set_password(data["password"])

    db.session.commit()
    return jsonify(patient.to_dict())


@app.route("/api/patients/<int:patient_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    db.session.delete(patient)
    db.session.commit()
    return jsonify({"message": "Patient deleted"})


@app.route("/api/patients/<int:patient_id>/blacklist", methods=["POST"])
@login_required
@role_required("admin")
def blacklist_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json() or {}
    patient.is_blacklisted = data.get("blacklist", True)
    db.session.commit()
    action = "blacklisted" if patient.is_blacklisted else "reinstated"
    return jsonify(
        {
            "message": f"Patient {action} successfully",
            "is_blacklisted": patient.is_blacklisted,
        }
    )


@app.route("/api/appointments", methods=["GET"])
@login_required
def get_appointments():
    if current_user.role == "patient":
        appointments = Appointment.query.filter_by(patient_id=current_user.id).all()
    elif current_user.role == "doctor":
        appointments = Appointment.query.filter_by(doctor_id=current_user.id).all()
    else:
        appointments = Appointment.query.all()

    return jsonify([a.to_dict() for a in appointments])


@app.route("/api/appointments/<int:appointment_id>", methods=["PUT"])
@login_required
@role_required("admin", "doctor")
def update_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    data = request.get_json()

    if "status" in data:
        appointment.status = data["status"]

    db.session.commit()
    return jsonify(appointment.to_dict())


@app.route("/api/appointments/<int:appointment_id>/reschedule", methods=["PUT"])
@login_required
@role_required("patient", "admin")
def reschedule_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    if current_user.role == "patient" and appointment.patient_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json()
    new_date = datetime.strptime(data["appointment_date"], "%Y-%m-%d").date()
    new_time = datetime.strptime(data["appointment_time"], "%H:%M").time()

    existing = Appointment.query.filter(
        Appointment.doctor_id == appointment.doctor_id,
        Appointment.appointment_date == new_date,
        Appointment.appointment_time == new_time,
        Appointment.status == "Booked",
        Appointment.id != appointment_id,
    ).first()

    if existing:
        return jsonify({"error": "Time slot not available"}), 400

    appointment.appointment_date = new_date
    appointment.appointment_time = new_time
    db.session.commit()

    return jsonify(appointment.to_dict())


@app.route("/api/appointments", methods=["POST"])
@login_required
@role_required("admin", "patient")
def create_appointment():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    if not data.get("doctor_id"):
        return jsonify({"error": "doctor_id is required"}), 400
    if not data.get("appointment_date"):
        return jsonify({"error": "appointment_date is required"}), 400
    if not data.get("appointment_time"):
        return jsonify({"error": "appointment_time is required"}), 400

    doctor_id = data.get("doctor_id")
    patient_id = (
        data.get("patient_id", current_user.id)
        if current_user.role == "patient"
        else data.get("patient_id")
    )
    appointment_date = datetime.strptime(data["appointment_date"], "%Y-%m-%d").date()
    appointment_time = datetime.strptime(data["appointment_time"], "%H:%M").time()

    existing = Appointment.query.filter_by(
        doctor_id=doctor_id,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        status="Booked",
    ).first()

    if existing:
        return jsonify({"error": "Appointment already exists at this time"}), 400

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        reason=data.get("reason", ""),
        status="Booked",
    )

    db.session.add(appointment)
    db.session.commit()

    return jsonify(appointment.to_dict()), 201


@app.route("/api/appointments/<int:appointment_id>", methods=["DELETE"])
@login_required
@role_required("admin", "patient", "doctor")
def cancel_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    if current_user.role == "patient" and appointment.patient_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    if current_user.role == "doctor" and appointment.doctor_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    appointment.status = "Cancelled"
    db.session.commit()

    return jsonify(appointment.to_dict())


@app.route("/api/treatments", methods=["GET"])
@login_required
def get_treatments():
    if current_user.role == "patient":
        appointments = Appointment.query.filter_by(patient_id=current_user.id).all()
        appointment_ids = [a.id for a in appointments]
    elif current_user.role == "doctor":
        appointments = Appointment.query.filter_by(doctor_id=current_user.id).all()
        appointment_ids = [a.id for a in appointments]
    else:
        treatments = Treatment.query.all()
        return jsonify([t.to_dict() for t in treatments])

    treatments = Treatment.query.filter(
        Treatment.appointment_id.in_(appointment_ids)
    ).all()
    return jsonify([t.to_dict() for t in treatments])


@app.route("/api/treatments", methods=["POST"])
@login_required
@role_required("doctor")
def create_treatment():
    data = request.get_json()
    appointment_id = data.get("appointment_id")

    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.doctor_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    treatment = Treatment(
        appointment_id=appointment_id,
        diagnosis=data["diagnosis"],
        prescription=data.get("prescription", ""),
        notes=data.get("notes", ""),
        next_visit=datetime.strptime(data["next_visit"], "%Y-%m-%d").date()
        if data.get("next_visit")
        else None,
    )

    appointment.status = "Completed"
    db.session.add(treatment)
    db.session.commit()

    return jsonify(treatment.to_dict()), 201


@app.route("/api/treatments/<int:treatment_id>", methods=["PUT"])
@login_required
@role_required("doctor")
def update_treatment(treatment_id):
    treatment = Treatment.query.get_or_404(treatment_id)
    data = request.get_json()

    if treatment.appointment.doctor_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    if "diagnosis" in data:
        treatment.diagnosis = data["diagnosis"]
    if "prescription" in data:
        treatment.prescription = data["prescription"]
    if "notes" in data:
        treatment.notes = data["notes"]
    if "next_visit" in data:
        treatment.next_visit = (
            datetime.strptime(data["next_visit"], "%Y-%m-%d").date()
            if data.get("next_visit")
            else None
        )

    db.session.commit()
    return jsonify(treatment.to_dict())


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5002)
