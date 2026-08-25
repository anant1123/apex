"""
services/auth.py — Passwordless (email OTP) login-session helpers.

No password hashing here anymore — see services/email_sender.py and
db/mongo.py's otp_codes functions for the actual OTP generate/verify flow.
This module just tracks who's logged in via Flask's signed session cookie.
"""

import random
from functools import wraps
from flask import session, redirect, url_for, request, jsonify

from db import mongo


def generate_otp_code():
    """6-digit numeric code, e.g. '042817'."""
    return f"{random.randint(0, 999999):06d}"


def log_in_user(user):
    """user: dict from mongo.get_user_by_email/get_user_by_id (has string _id)."""
    session["user_id"] = user["_id"]
    session["user_name"] = user["name"]
    session.permanent = True


def log_out_user():
    session.clear()


def current_user():
    """Returns the full user dict for the logged-in user, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return mongo.get_user_by_id(user_id)


def login_required(view_fn):
    """Redirects HTML page requests to /login; returns 401 JSON for /api/* calls."""
    @wraps(view_fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please log in first.", "auth_required": True}), 401
            return redirect(url_for("login_page", next=request.path))
        return view_fn(*args, **kwargs)
    return wrapped
