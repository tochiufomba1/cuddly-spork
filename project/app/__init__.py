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

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
sess = Session()
compress = Compress()
#client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"),)

# https://flask.palletsprojects.com/en/stable/patterns/celery/
def celery_init_app(app: Flask) -> Celery:
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(CeleryConfig)
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app

def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, template_folder="../../dist", static_url_path='/static', static_folder='../../dist/static')
    app.config.from_object(Config)
    # app.config["PROFILE"] = True # Enable profiling
    # app.wsgi_app = ProfilerMiddleware(
    #     app.wsgi_app,
    #     restrictions=[50],  # Limit output to 50 most expensive calls
    #     profile_dir="profiler_dump" # Directory to save profile data
    # )

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(app, resources={r"/api/*": {"origins": ["http://localhost:5173", "http://localhost:3000"]}}, supports_credentials=True)
    sess.init_app(app)
    compress.init_app(app)
    celery_init_app(app)

    # Blueprints
    from app.api import bp
    app.register_blueprint(bp)

  
    @app.shell_context_processor
    def make_shell_context():
        return {'db': db}

    return app