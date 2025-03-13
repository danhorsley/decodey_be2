from flask import Blueprint, jsonify, redirect, url_for, render_template, request
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging

bp = Blueprint('main', __name__)


@bp.route('/', strict_slashes=True)
def index():
    """Return login page for browser requests, API status for API requests"""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({"status": "ok", "message": "Uncrypt Game API"})
    return render_template('login.html')


@bp.route('/api/health')
def health_check():
    """API health check endpoint"""
    return jsonify({"status": "ok", "message": "API is running"})


@bp.route('/register')
def register():
    """Return registration page for browser requests"""
    return render_template('register.html')


@bp.route('/game')
def game():
    """Show the game page for browser requests"""
    return render_template('game.html')


@bp.route('/stats')
def stats():
    """Show user statistics page"""
    return render_template('stats.html')


@bp.route('/leaderboard')
def leaderboard():
    """Show leaderboard page"""
    return render_template('leaderboard.html')
