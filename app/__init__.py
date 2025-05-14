# app/__init__.py
"""Main application package."""

import os
import logging
from flask import Flask
from dotenv import load_dotenv
from typing import Optional
from datetime import timedelta

# Import extensions instances
from .extensions import db, migrate, login_manager

# --- Basic Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def register_cli_commands(app: Flask):
    @app.cli.command("seed_dev_user")
    def seed_dev_user_command():
        """Creates a mock user 'thilo' with password 'password' for development."""
        # Imports are here to ensure app context and to avoid circular dependencies
        from .models import User
        from .extensions import db

        username_to_seed = 'thilo'
        password_to_seed = 'password'

        # Check if mock user exists
        existing_user = db.session.execute(
            db.select(User).filter_by(username=username_to_seed)
        ).scalar_one_or_none()

        if not existing_user:
            new_user = User(username=username_to_seed)
            new_user.set_password(password_to_seed)
            db.session.add(new_user)
            try:
                db.session.commit()
                print(f"Mock user '{username_to_seed}' created successfully.")
            except Exception as e:
                db.session.rollback()
                print(f"Error creating mock user '{username_to_seed}': {e}")
        else:
            print(f"Mock user '{username_to_seed}' already exists.")

def create_app(config_object=None) -> Flask:
    """Application factory function."""
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)

    # --- Load Configuration ---
    app.config.from_mapping(
        SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-please-change-in-prod'),
        PERMANENT_SESSION_LIFETIME = timedelta(days=7),
        SQLALCHEMY_DATABASE_URI = os.getenv(
            'DATABASE_URL',
            'postgresql+psycopg://user:password@localhost:5432/fit_analyzer_db'
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS = False,
        FIT_DIR = os.path.abspath(os.getenv('FIT_ANALYZER_FIT_DIR', 'fitfiles')),
        ALLOWED_EXTENSIONS = {'.fit'}
    )
    if config_object: app.config.from_object(config_object)
    try: os.makedirs(app.instance_path, exist_ok=True)
    except OSError: logger.error(f"Could not create instance folder: {app.instance_path}")

    # --- Initialize Extensions ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # --- Define User Loader ---
    @login_manager.user_loader
    def load_user(user_id: str) -> Optional['User']:
        from .models import User # Import here to avoid circular import
        try: return db.session.get(User, int(user_id))
        except Exception as e: logger.error(f"Error loading user {user_id}: {e}"); return None

    # --- Register Blueprints ---
    from .main import routes as main_routes
    app.register_blueprint(main_routes.bp)

    from .auth import routes as auth_routes
    app.register_blueprint(auth_routes.bp) # Prefix '/api' defined in blueprint

    from .files import routes as file_routes
    app.register_blueprint(file_routes.bp) # Prefix '/api' defined in blueprint

    from .analysis import routes as analysis_routes
    app.register_blueprint(analysis_routes.bp) # Prefix '/api' defined in blueprint

    # --- Ensure FIT_DIR exists (check on app creation) ---
    if not os.path.isdir(app.config['FIT_DIR']):
        logger.warning(f"Base FIT file directory '{app.config['FIT_DIR']}' not found. Attempting to create.")
        try: os.makedirs(app.config['FIT_DIR'], exist_ok=True); logger.info(f"Created base directory: {app.config['FIT_DIR']}.")
        except OSError as e: logger.error(f"Could not create base FIT file directory: {e}.")
    else: logger.info(f"Using base FIT file directory: {app.config['FIT_DIR']}")

    # --- Register CLI commands ---
    # Make sure this is called after db has been initialized with the app
    # and within the app context implicitly provided if this file is run directly or through flask run
    # For CLI commands, they operate within an app context automatically when invoked.
    with app.app_context(): # Ensures db operations have the necessary context
        register_cli_commands(app)


    logger.info("Flask app created and configured successfully.")
    return app