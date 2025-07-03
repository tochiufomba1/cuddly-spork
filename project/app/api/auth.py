import sqlalchemy as sa
from flask_httpauth import HTTPBasicAuth
from app import db
from app.models import Users
from app.api.errors import error_response
from flask_httpauth import HTTPTokenAuth

basic_auth = HTTPBasicAuth()
token_auth = HTTPTokenAuth()

@basic_auth.verify_password
def verify_password(email, password):
    # print(f"Username: {username} Password: {password}")
    user = db.session.scalar(sa.select(Users).where(Users.email == email))
    # print(user)
    if user and user.check_password(password):
        return user

@basic_auth.error_handler
def basic_auth_error(status):
    print("HERE")
    return error_response(403, "Unauthorized attempt to access resource")

@token_auth.verify_token
def verify_token(token: str):
    print(f"Token received: {token}")
    return Users.check_token(token) if token else None

@token_auth.error_handler
def token_auth_error(status):
    return error_response(403, "Unauthorized attempt to access resource")