from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from app.utils.db import get_leaderboard

bp = Blueprint('leaderboard', __name__)

@bp.route('/leaderboard', methods=['GET'])
@jwt_required()
def get_leaderboard_data():
    leaderboard = get_leaderboard()
    return jsonify(leaderboard), 200
