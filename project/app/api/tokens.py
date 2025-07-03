from app import db
from .auth import basic_auth
from .auth import token_auth
from flask import make_response
from app.api import bp
from datetime import timedelta, datetime, timezone

@bp.route('/api/tokens', methods=['POST'])
@basic_auth.login_required
def get_token():
    token = basic_auth.current_user().get_token()
    db.session.commit()
    user = basic_auth.current_user()
    exp = int(user.token_expiration.timestamp()) #int(user.token_expiration.replace(tzinfo=timezone.utc).timestamp())
    
    return {"id":str(user.id), "name": user.username, "token":token, "exp": exp }, 200

@bp.route('/api/tokens', methods=['DELETE'])
@token_auth.login_required
def revoke_token():
    token_auth.current_user().revoke_token()
    db.session.commit()
    return '', 204