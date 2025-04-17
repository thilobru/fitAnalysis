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
    # --- Explicitly import the models module HERE ---
    # This ensures SQLAlchemy registers the models before metadata is accessed below
    from app import models
    # ---
except ImportError as e:
    print(f"Error importing Flask app or models in env.py: {e}")
    print("Make sure env.py is in the 'migrations' directory and your Flask app structure is correct.")
    sys.exit(1)

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
# --- Use the metadata from your Flask app's db object ---
# Ensure models are imported above before this line!
target_metadata = db.metadata
# ---

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    """
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

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.
    """
    flask_app_for_config = create_app() # Need app instance to get config
    connectable = context.config.attributes.get("connection", None)

    if connectable is None:
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
