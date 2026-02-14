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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5002)
