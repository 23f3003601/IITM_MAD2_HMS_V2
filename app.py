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


@app.route("/api/doctor/dashboard", methods=["GET"])
@login_required
@role_required("doctor")
def doctor_dashboard():
    today = date.today()
    week_later = today + timedelta(days=7)

    today_appointments = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.appointment_date == today,
        Appointment.status == "Booked",
    ).all()

    week_appointments = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.appointment_date >= today,
        Appointment.appointment_date <= week_later,
        Appointment.status == "Booked",
    ).all()

    patients = (
        Appointment.query.filter(Appointment.doctor_id == current_user.id)
        .distinct(Appointment.patient_id)
        .all()
    )

    return jsonify(
        {
            "today_appointments": [a.to_dict() for a in today_appointments],
            "week_appointments": [a.to_dict() for a in week_appointments],
            "total_patients": len(patients),
        }
    )


@app.route("/api/doctor/patients", methods=["GET"])
@login_required
@role_required("doctor")
def doctor_patients():
    appointments = Appointment.query.filter_by(doctor_id=current_user.id).all()
    patient_ids = set([a.patient_id for a in appointments])
    patients = Patient.query.filter(Patient.id.in_(patient_ids)).all()

    result = []
    for p in patients:
        last_apt = (
            Appointment.query.filter_by(doctor_id=current_user.id, patient_id=p.id)
            .order_by(Appointment.appointment_date.desc())
            .first()
        )
        treatment = (
            Treatment.query.filter_by(appointment_id=last_apt.id).first()
            if last_apt
            else None
        )

        result.append(
            {
                "patient": p.to_dict(),
                "last_visit": last_apt.appointment_date.isoformat()
                if last_apt
                else None,
                "last_diagnosis": treatment.diagnosis if treatment else None,
            }
        )

    return jsonify(result)


@app.route("/api/payments", methods=["POST"])
@login_required
@role_required("patient")
def create_payment():
    data = request.get_json()

    payment = {
        "appointment_id": data.get("appointment_id"),
        "amount": data.get("amount", 500),
        "card_number": data.get("card_number", ""),
        "status": "completed",
        "transaction_id": f"TXN{date.today().strftime('%Y%m%d')}{current_user.id}",
    }

    return jsonify(
        {
            "message": "Payment successful",
            "transaction_id": payment["transaction_id"],
            "amount": payment["amount"],
        }
    )


@app.route("/api/availability", methods=["GET"])
def get_availability():
    doctor_id = request.args.get("doctor_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = DoctorAvailability.query

    if doctor_id:
        query = query.filter_by(doctor_id=doctor_id)
    if start_date:
        query = query.filter(
            DoctorAvailability.date >= datetime.strptime(start_date, "%Y-%m-%d").date()
        )
    if end_date:
        query = query.filter(
            DoctorAvailability.date <= datetime.strptime(end_date, "%Y-%m-%d").date()
        )

    availability = query.all()
    return jsonify([a.to_dict() for a in availability])


@app.route("/api/availability", methods=["POST"])
@login_required
@role_required("doctor")
def create_availability():
    data = request.get_json()

    availability = DoctorAvailability(
        doctor_id=current_user.id,
        date=datetime.strptime(data["date"], "%Y-%m-%d").date(),
        start_time=datetime.strptime(data["start_time"], "%H:%M").time(),
        end_time=datetime.strptime(data["end_time"], "%H:%M").time(),
        is_available=data.get("is_available", True),
    )

    db.session.add(availability)
    db.session.commit()

    return jsonify(availability.to_dict()), 201


@app.route("/api/availability/bulk", methods=["POST"])
@login_required
@role_required("doctor")
def bulk_create_availability():
    data = request.get_json()
    start_date = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
    end_date = datetime.strptime(data["end_date"], "%Y-%m-%d").date()
    start_time = datetime.strptime(data["start_time"], "%H:%M").time()
    end_time = datetime.strptime(data["end_time"], "%H:%M").time()

    current_date = start_date
    while current_date <= end_date:
        existing = DoctorAvailability.query.filter_by(
            doctor_id=current_user.id, date=current_date
        ).first()

        if not existing:
            availability = DoctorAvailability(
                doctor_id=current_user.id,
                date=current_date,
                start_time=start_time,
                end_time=end_time,
                is_available=True,
            )
            db.session.add(availability)

        current_date += timedelta(days=1)

    db.session.commit()
    return jsonify({"message": "Availability created successfully"}), 201


@app.route("/api/dashboard/stats", methods=["GET"])
@login_required
@role_required("admin")
def dashboard_stats():
    cache_key_str = "dashboard:stats"
    cached = redis_client.get(cache_key_str)
    if cached:
        return jsonify(json.loads(cached))

    total_doctors = Doctor.query.count()
    total_patients = Patient.query.count()
    total_appointments = Appointment.query.count()
    upcoming_appointments = Appointment.query.filter(
        Appointment.appointment_date >= date.today(), Appointment.status == "Booked"
    ).count()

    result = {
        "total_doctors": total_doctors,
        "total_patients": total_patients,
        "total_appointments": total_appointments,
        "upcoming_appointments": upcoming_appointments,
    }

    redis_client.setex(cache_key_str, 60, json.dumps(result))
    return jsonify(result)


@app.route("/api/export/csv", methods=["POST"])
@login_required
@role_required("patient")
def export_treatments_csv():
    import threading, uuid

    task_id = str(uuid.uuid4())

    def run_export(patient_id, tid):
        with app.app_context():
            patient = Patient.query.get(patient_id)
            appointments = Appointment.query.filter_by(patient_id=patient_id).all()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "Patient ID",
                    "Patient Name",
                    "Doctor",
                    "Appointment Date",
                    "Diagnosis",
                    "Prescription",
                    "Notes",
                    "Next Visit",
                ]
            )
            for apt in appointments:
                treatment = Treatment.query.filter_by(appointment_id=apt.id).first()
                if treatment:
                    writer.writerow(
                        [
                            patient.id,
                            patient.username,
                            apt.doctor.username if apt.doctor else "",
                            apt.appointment_date,
                            treatment.diagnosis,
                            treatment.prescription,
                            treatment.notes,
                            treatment.next_visit or "",
                        ]
                    )
            output.seek(0)
            redis_client.setex(f"export:{tid}", 3600, output.getvalue())
            redis_client.setex(f"export_status:{tid}", 3600, "completed")

    t = threading.Thread(target=run_export, args=(current_user.id, task_id))
    t.start()
    return jsonify({"task_id": task_id, "message": "Export job started"})


@app.route("/api/export/status/<task_id>", methods=["GET"])
@login_required
@role_required("patient")
def get_export_status(task_id):
    status = redis_client.get(f"export_status:{task_id}")
    if status == "completed":
        return jsonify({"status": "completed"})
    return jsonify({"status": "pending"})


@celery.task
def send_daily_reminders():
    with app.app_context():
        tomorrow = date.today() + timedelta(days=1)
        appointments = Appointment.query.filter_by(
            appointment_date=tomorrow, status="Booked"
        ).all()

        print(f"\n{'=' * 60}")
        print(f"DAILY REMINDER JOB TRIGGERED")
        print(f"Checking appointments for: {tomorrow}")
        print(f"Found {len(appointments)} appointment(s) for tomorrow")
        print(f"{'=' * 60}")

        for appointment in appointments:
            patient = appointment.patient
            doctor = appointment.doctor

            print(f"\n  -> Sending reminder to: {patient.username} ({patient.email})")
            print(f"     Doctor: Dr. {doctor.username}")
            print(
                f"     Specialization: {doctor.specialization.name if doctor.specialization else 'General'}"
            )
            print(f"     Date: {appointment.appointment_date}")
            print(f"     Time: {appointment.appointment_time}")

            if patient.email:
                try:
                    msg = Message(
                        "Appointment Reminder - Hospital Management System",
                        recipients=[patient.email],
                    )
                    msg.body = f"""
Dear {patient.username},

This is a reminder for your appointment tomorrow.

Doctor: Dr. {doctor.username}
Specialization: {doctor.specialization.name if doctor.specialization else "General"}
Date: {appointment.appointment_date}
Time: {appointment.appointment_time}

Please arrive 15 minutes before your scheduled time.

Best regards,
Hospital Management System
"""
                    mail.send(msg)
                    print(f"     EMAIL SENT SUCCESSFULLY to {patient.email}")
                except Exception as e:
                    print(f"     Email failed (expected without SMTP config): {e}")

        print(f"\n{'=' * 60}")
        print(f"DAILY REMINDER JOB COMPLETED - Processed {len(appointments)} reminders")
        print(f"{'=' * 60}\n")

        return f"Sent {len(appointments)} reminders"


@celery.task
def send_monthly_report():
    with app.app_context():
        today = date.today()
        first_day_month = today.replace(day=1)
        last_day_month = (first_day_month + timedelta(days=32)).replace(
            day=1
        ) - timedelta(days=1)

        doctors = Doctor.query.all()

        print(f"\n{'=' * 60}")
        print(f"MONTHLY REPORT JOB TRIGGERED")
        print(f"Report period: {first_day_month} to {last_day_month}")
        print(f"Total doctors: {len(doctors)}")
        print(f"{'=' * 60}")

        for doctor in doctors:
            appointments = Appointment.query.filter(
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date >= first_day_month,
                Appointment.appointment_date <= last_day_month,
                Appointment.status == "Completed",
            ).all()

            print(f"\n  -> Dr. {doctor.username} ({doctor.email})")
            print(f"     Completed appointments this month: {len(appointments)}")

            if not doctor.email:
                print(f"     SKIPPED - no email configured")
                continue

            treatments_html = ""
            for apt in appointments:
                treatment = Treatment.query.filter_by(appointment_id=apt.id).first()
                if treatment:
                    print(
                        f"     - {apt.appointment_date} | Patient: {apt.patient.username} | Diagnosis: {treatment.diagnosis}"
                    )
                    treatments_html += f"""
                    <tr>
                        <td>{apt.appointment_date}</td>
                        <td>{apt.patient.username}</td>
                        <td>{treatment.diagnosis}</td>
                        <td>{treatment.prescription}</td>
                    </tr>
                    """

            html_content = f"""
            <html>
            <body>
                <h2>Monthly Activity Report - Dr. {doctor.username}</h2>
                <p>Period: {first_day_month} to {last_day_month}</p>
                <p>Total Completed Appointments: {len(appointments)}</p>
                <table border="1" cellpadding="5">
                    <tr>
                        <th>Date</th>
                        <th>Patient</th>
                        <th>Diagnosis</th>
                        <th>Prescription</th>
                    </tr>
                    {treatments_html}
                </table>
            </body>
            </html>
            """

            try:
                msg = Message(
                    f"Monthly Activity Report - {first_day_month.strftime('%B %Y')}",
                    recipients=[doctor.email],
                )
                msg.html = html_content
                mail.send(msg)
                print(f"     EMAIL SENT SUCCESSFULLY to {doctor.email}")
            except Exception as e:
                print(f"     Email failed (expected without SMTP config): {e}")

        print(f"\n{'=' * 60}")
        print(f"MONTHLY REPORT JOB COMPLETED - Processed {len(doctors)} doctors")
        print(f"{'=' * 60}\n")

        return f"Sent reports to {len(doctors)} doctors"

        return f"Sent reports to {len(doctors)} doctors"


@celery.task
def export_treatments_csv_task(patient_id):
    with app.app_context():
        patient = Patient.query.get(patient_id)
        appointments = Appointment.query.filter_by(patient_id=patient_id).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Patient ID",
                "Patient Name",
                "Doctor",
                "Appointment Date",
                "Diagnosis",
                "Prescription",
                "Notes",
                "Next Visit",
            ]
        )

        for apt in appointments:
            treatment = Treatment.query.filter_by(appointment_id=apt.id).first()
            if treatment:
                writer.writerow(
                    [
                        patient.id,
                        patient.username,
                        apt.doctor.username if apt.doctor else "",
                        apt.appointment_date,
                        treatment.diagnosis,
                        treatment.prescription,
                        treatment.notes,
                        treatment.next_visit if treatment.next_visit else "",
                    ]
                )

        output.seek(0)

        redis_client.setex(f"export:{patient_id}", 3600, output.getvalue())

        return {"message": "Export completed", "patient_id": patient_id}


def init_db():
    with app.app_context():
        db.create_all()

        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = Admin(username="admin", email="admin@hms.com", role="admin")
            admin.set_password("admin123")
            db.session.add(admin)

        departments = [
            {
                "name": "General Medicine",
                "description": "General health issues and common ailments",
            },
            {"name": "Cardiology", "description": "Heart and cardiovascular system"},
            {"name": "Dermatology", "description": "Skin, hair, and nails"},
            {"name": "Orthopedics", "description": "Bones, joints, and muscles"},
            {
                "name": "Pediatrics",
                "description": "Healthcare for infants and children",
            },
            {"name": "Neurology", "description": "Brain and nervous system"},
            {"name": "Gynecology", "description": "Women's health"},
            {"name": "Ophthalmology", "description": "Eye care"},
        ]

        for dept_data in departments:
            if not Department.query.filter_by(name=dept_data["name"]).first():
                dept = Department(**dept_data)
                db.session.add(dept)

        db.session.commit()

        # Seed sample doctors if not present
        seed_doctors = [
            {
                "username": "dr_smith",
                "email": "drsmith@hms.com",
                "specialization": "General Medicine",
                "phone": "9876543210",
                "bio": "Experienced general physician",
            },
            {
                "username": "dr_patel",
                "email": "drpatel@hms.com",
                "specialization": "Cardiology",
                "phone": "9876500001",
                "bio": "Cardiologist with 10 years experience",
            },
            {
                "username": "dr_ali",
                "email": "drali@hms.com",
                "specialization": "Dermatology",
                "phone": "9876500002",
                "bio": "Dermatology specialist",
            },
        ]
        for sd in seed_doctors:
            if not User.query.filter_by(username=sd["username"]).first():
                dept = Department.query.filter_by(name=sd["specialization"]).first()
                doc = Doctor(
                    username=sd["username"],
                    email=sd["email"],
                    role="doctor",
                    phone=sd["phone"],
                    bio=sd["bio"],
                    specialization_id=dept.id if dept else None,
                    is_available=True,
                )
                doc.set_password("doctor123")
                db.session.add(doc)

        db.session.commit()

        # Seed sample patients if not present
        seed_patients = [
            {
                "username": "johndoe",
                "email": "john@example.com",
                "phone": "1234567890",
                "gender": "Male",
                "blood_group": "O+",
                "dob": "1990-01-15",
                "address": "123 Main St",
            },
            {
                "username": "janesmith",
                "email": "jane@example.com",
                "phone": "9876543211",
                "gender": "Female",
                "blood_group": "A+",
                "dob": "1985-06-20",
                "address": "456 Oak Ave",
            },
        ]
        for sp in seed_patients:
            if not User.query.filter_by(username=sp["username"]).first():
                from datetime import datetime as dt

                pat = Patient(
                    username=sp["username"],
                    email=sp["email"],
                    role="patient",
                    phone=sp["phone"],
                    gender=sp["gender"],
                    blood_group=sp["blood_group"],
                    date_of_birth=dt.strptime(sp["dob"], "%Y-%m-%d").date(),
                    address=sp["address"],
                )
                pat.set_password("password123")
                db.session.add(pat)

        db.session.commit()

        # Seed availability for all doctors for the next 7 days
        all_doctors = Doctor.query.all()
        today = date.today()
        for doc in all_doctors:
            for i in range(7):
                avail_date = today + timedelta(days=i)
                existing = DoctorAvailability.query.filter_by(
                    doctor_id=doc.id, date=avail_date
                ).first()
                if not existing:
                    avail = DoctorAvailability(
                        doctor_id=doc.id,
                        date=avail_date,
                        start_time=time(9, 0),
                        end_time=time(17, 0),
                        is_available=True,
                    )
                    db.session.add(avail)

        db.session.commit()
        print("Database initialized successfully!")


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5002)
