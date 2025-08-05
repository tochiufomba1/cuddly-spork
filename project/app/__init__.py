from flask import Flask
from config import Config, CeleryConfig
from flask_compress import Compress
from flask_session import Session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from celery import Celery, Task
from openai import OpenAI
import os
from werkzeug.middleware.profiler import ProfilerMiddleware
from dotenv import load_dotenv
import boto3
from botocore.client import Config as BConfig

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
sess = Session()
compress = Compress()

s3_client = boto3.client(
    's3',
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"),
    config=BConfig(s3={'addressing_style': 'virtual'}),
)

#client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"),)

# https://flask.palletsprojects.com/en/stable/patterns/celery/
def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask, backend=os.environ.get("REDIS_URL"), broker=os.environ.get("REDIS_URL"))
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app

def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    # app.config["PROFILE"] = True # Enable profiling
    # app.wsgi_app = ProfilerMiddleware(
    #     app.wsgi_app,
    #     restrictions=[50],  # Limit output to 50 most expensive calls
    #     profile_dir="profiler_dump" # Directory to save profile data
    # )

    # Extensions
    db.init_app(app)

    from . import models
    migrate.init_app(app, db)
    cors.init_app(app, resources={r"/api/*": {"origins": ["*"]}}, supports_credentials=True)
    sess.init_app(app)
    compress.init_app(app)
    celery_init_app(app)

    # Blueprints
    from .api import bp
    app.register_blueprint(bp)

  
    @app.shell_context_processor
    def make_shell_context():
        return {'db': db}

    return app