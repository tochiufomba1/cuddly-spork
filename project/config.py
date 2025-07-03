import os
import redis

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # Database
    SQLALCHEMY_DATABASE_URI = "postgresql://postgres:Abd123baby321@localhost:5432/bookkeeper"     #os.environ.get('DATABASE_URL')
    
    # Web
    SESSION_COOKIE_HTTPONLY = os.environ.get('SESSION_COOKIE_HTTPONLY', 'True')
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'None')
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'True')
    
    # Flask-Sessions
    SESSION_TYPE =  'redis' #os.environ.get('SESSION_TYPE')
    SESSION_REDIS =  redis.from_url('redis://127.0.0.1:6379/0')
    SESSION_PERMANENT = os.environ.get('SESSION_PERMANENT')
    SESSION_USE_SIGNER = os.environ.get('SESSION_USE_SIGNER')

    # Celery
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND')
    
    # Other
    UPLOAD_FOLDER = './tmp' #os.path.join(BASE_DIR, "/api/tmp")

    # CELERY=dict(
    #     broker_url="pyamqp://guest@localhost//",
    #     result_backend="redis://localhost:6379/1",
    #     ),

class CeleryConfig:
    broker_url = "redis://localhost:6379/1"
    result_backend = "redis://localhost:6379/1"
    task_ignore_result=False