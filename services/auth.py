"""
services/auth.py — Password hashing + login-session helpers.

Uses werkzeug's password hashing (already a Flask dependency, no new
package needed) and Flask's signed session cookie to track who's
logged in — no extra library like flask-login required, keeping the
dependency footprint the same as the rest of this project.
"""

from functools import wraps
from flask import session, redirect, url_for, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from db import mongo


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


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
