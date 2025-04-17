import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# --- Add this section to integrate with Flask app ---
# Ensure the app directory is in the Python path
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), '..')))

# Import your Flask app's db object and models
# Adjust the import path 'app' if your Flask app factory or db instance is located differently
try:
    from app import create_app
    from app.extensions import db
    # Import models so Alembic detects them (adjust if models are elsewhere)
    from app import models # Or: from app.models import User, FitFile
except ImportError as e:
    print(f"Error importing Flask app or models in env.py: {e}")
    print("Make sure env.py is in the 'migrations' directory and your Flask app structure is correct.")
    sys.exit(1)

# Create a minimal Flask app instance for config access if needed,
# but Flask-Migrate usually handles this. We primarily need the 'db' object.
# flask_app = create_app() # Usually not needed directly here if Flask-Migrate is used

# --- End Flask integration section ---


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata

# --- Use the metadata from your Flask app's db object ---
target_metadata = db.metadata
# ---

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # --- Use URL from Flask app config ---
    # Flask-Migrate usually sets this up automatically via the CLI,
    # but defining it here ensures it works if run directly with Alembic.
    flask_app_for_config = create_app() # Need app instance to get config
    url = flask_app_for_config.config.get("SQLALCHEMY_DATABASE_URI")
    if not url:
        raise ValueError("SQLALCHEMY_DATABASE_URI not found in Flask app config.")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    # ---

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # --- Use Engine configuration from Flask app config ---
    # This section is typically managed by Flask-Migrate when run via `flask db upgrade`
    flask_app_for_config = create_app() # Need app instance to get config
    connectable = context.config.attributes.get("connection", None)

    if connectable is None:
        # --- CORRECTED LINE ---
        # Removed the attempt to call flask_app_for_config.config.get_section("sqlalchemy")
        # Directly use the dictionary with the URL from the Flask config.
        db_url = flask_app_for_config.config.get("SQLALCHEMY_DATABASE_URI")
        if not db_url:
             raise ValueError("SQLALCHEMY_DATABASE_URI not found in Flask app config for online mode.")

        connectable = engine_from_config(
            {"sqlalchemy.url": db_url}, # Use the URL directly
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    if connectable is None:
         raise Exception("Could not determine database connection for Alembic.")


    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

