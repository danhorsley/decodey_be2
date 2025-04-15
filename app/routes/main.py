from flask import Blueprint, jsonify, redirect, url_for, render_template, request
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging

bp = Blueprint('main', __name__)


@bp.route('/', strict_slashes=True)
def index():
    """Return API status"""
    return jsonify({"status": "ok", "message": "Uncrypt Game API"})


@bp.route('/api/health')
def health_check():
    """API health check endpoint"""
    return jsonify({"status": "ok", "message": "API is running"})


