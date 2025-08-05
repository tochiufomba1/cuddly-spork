import sqlalchemy as sa
from flask_httpauth import HTTPBasicAuth
from .. import db
from ..models import Users
from .errors import error_response
from flask_httpauth import HTTPTokenAuth

basic_auth = HTTPBasicAuth()
token_auth = HTTPTokenAuth()

@basic_auth.verify_password
def verify_password(email, password):
    user = db.session.scalar(sa.select(Users).where(Users.email == email))
    
    if user and user.check_password(password):
        return user

@basic_auth.error_handler
def basic_auth_error(status):
    return error_response(403, "Unauthorized attempt to access resource")

@token_auth.verify_token
def verify_token(token: str):
    return Users.check_token(token) if token else None

@token_auth.error_handler
def token_auth_error(status):
    return error_response(403, "Unauthorized attempt to access resource")