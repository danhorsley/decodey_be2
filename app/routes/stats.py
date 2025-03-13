from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.utils.db import get_user_stats

bp = Blueprint('stats', __name__)

@bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    username = get_jwt_identity()
    stats = get_user_stats(username)
    return jsonify(stats), 200
