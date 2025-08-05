from .errors import bad_request
from .. import db, models
from .auth import basic_auth
from .auth import token_auth
from flask import make_response
from . import bp
from datetime import timedelta, datetime, timezone

@bp.route('/api/tokens', methods=['POST'])
@basic_auth.login_required
def get_token():
    user: models.Users | None= basic_auth.current_user()

    if user is None:
        return bad_request("User does not exist")
    
    token = user.get_token() if user is not None else -1
    db.session.commit()
        
    token_exp = user.token_expiration
    if token_exp is not None:
        unix_expiration_timestamp = int(token_exp.timestamp())
        return {"id":str(user.id), "name": user.username, "token":token, "exp": unix_expiration_timestamp }, 200

@bp.route('/api/tokens', methods=['DELETE'])
@token_auth.login_required
def revoke_token():
    user = token_auth.current_user()
    if user is not None:
        user.revoke_token()
        db.session.commit()
        return '', 204
    else:
        return bad_request("User does not exist")