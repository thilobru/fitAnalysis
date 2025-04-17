# tests/conftest.py
"""Pytest configuration and fixtures."""

import pytest
import os
from app import create_app # Import factory
from app.extensions import db as _db # Import db instance initialized in extensions
from app.models import User # Import User for logged_in_client fixture
from flask import Flask
from flask.testing import FlaskClient
from flask_sqlalchemy import SQLAlchemy
from typing import Generator, Tuple

# --- Test Configuration Class ---
class TestConfig:
    TESTING = True
    # ** CHANGE: Point to the MAIN database URL consistently **
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL', # Use the same env var as the main app in docker-compose
        'postgresql+psycopg://user:password@db:5432/fit_analyzer_db' # Default matches docker-compose MAIN DB
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret-key' # Fixed key for testing
    WTF_CSRF_ENABLED = False # Often disable CSRF for testing APIs/forms
    # Set a default FIT_DIR in config for tests (can be overridden per test)
    FIT_DIR = '/tmp/pytest_global_fit_dir'
    # Disable logging noise during tests if desired
    LOGGING_LEVEL = 'WARNING' # Set to WARNING or ERROR for less noise


@pytest.fixture(scope='function') # ** CHANGE: Use function scope for better isolation **
def app() -> Generator[Flask, None, None]:
    """Function-scoped test Flask application."""
    # Create app instance using the factory and TestConfig
    _app = create_app(TestConfig)

    # Establish an application context
    ctx = _app.app_context()
    ctx.push()

    yield _app # Use the app instance for a single test function

    ctx.pop() # Clean up context

@pytest.fixture(scope='function') # Function scope ensures clean DB for each test
def db(app: Flask) -> Generator[SQLAlchemy, None, None]:
    """Function-scoped database fixture."""
    _db.app = app # Associate db with the test app instance

    # Create tables before each test
    _db.create_all()

    yield _db # Provide the db instance to tests

    # Teardown: clean up database after each test
    _db.session.remove() # Ensure session is closed cleanly
    _db.drop_all() # Drop all tables defined by models

@pytest.fixture(scope='function') # Ensure client also uses function scope
def client(app: Flask, db: SQLAlchemy) -> FlaskClient: # Depend on db fixture
    """Test client fixture using the app fixture."""
    # The db fixture handles create/drop all
    return app.test_client()

@pytest.fixture(scope='function')
def logged_in_client(client: FlaskClient, db: SQLAlchemy) -> Tuple[FlaskClient, User]:
    """Fixture to provide a test client that is already logged in."""
    # Needs db fixture to ensure tables exist and session works
    username = 'testuser'
    password = 'password123'

    # Register user using DB directly (more reliable than API call in fixture)
    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    user_id = new_user.id # Get ID after commit

    # Login via API call using the client
    login_response = client.post('/api/login', json={'username': username, 'password': password})
    assert login_response.status_code == 200, "Fixture setup failed: Login failed"

    # Retrieve user object again to ensure it's bound to session if needed
    logged_in_user = db.session.get(User, user_id)
    assert logged_in_user is not None, "Fixture setup failed: Could not retrieve user after login"

    yield client, logged_in_user # Provide client and user object

    # Teardown handled by db fixture's drop_all
