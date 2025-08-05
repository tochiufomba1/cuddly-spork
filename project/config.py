import os
import redis
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    
    # Web
    SESSION_COOKIE_HTTPONLY = os.environ.get('SESSION_COOKIE_HTTPONLY', 'True')
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'None')
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'True')
    
    # Flask-Sessions
    SESSION_TYPE = os.environ.get('SESSION_TYPE', 'redis')
    SESSION_REDIS =  redis.from_url(os.environ.get('REDIS_URL')) #/0
    SESSION_PERMANENT = os.environ.get('SESSION_PERMANENT', 'True')
    SESSION_USE_SIGNER = os.environ.get('SESSION_USE_SIGNER', 'True')

    # Celery
    
    
    # Other
    UPLOAD_FOLDER = './tmp' #os.path.join(BASE_DIR, "/api/tmp")

class CeleryConfig:
    broker_url = os.environ.get('REDIS_URL') #/1
    result_backend = os.environ.get('REDIS_URL')
    task_ignore_result=False
