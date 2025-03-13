from flask import Blueprint, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('login.html')

@bp.route('/register')
def register():
    return render_template('register.html')

@bp.route('/game')
@jwt_required()
def game():
    return render_template('game.html')