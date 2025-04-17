import pytest
import json
import os
from datetime import date
from typing import List, Dict, Generator, Any
from flask.testing import FlaskClient
from pathlib import Path
from pytest_mock import MockerFixture # Import mocker type hint

# Import the Flask app instance and DB objects from your app file
from app import app as flask_app, db, User # Import db and User model

# --- Pytest Fixture for Flask Test Client with DB Handling ---

@pytest.fixture(scope='function') # Run setup/teardown for each test function
def client() -> Generator[FlaskClient, None, None]:
    """Create a Flask test client instance with isolated DB state."""
    # Use the regular DB URL from env vars, assuming it points to the test DB container
    DB_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://user:password@db:5432/fit_analyzer_db')
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
    flask_app.config['TESTING'] = True
    # Disable CSRF protection for simpler API testing if forms were used
    flask_app.config['WTF_CSRF_ENABLED'] = False
    # Use a different secret key for testing if desired
    # flask_app.config['SECRET_KEY'] = 'test-secret-key'

    # Establish an application context before interacting with db
    with flask_app.app_context():
        # Create all tables defined in models
        db.create_all()

    # Create a test client using the Flask application context
    with flask_app.test_client() as client:
        yield client # Provide the client to the test functions

    # Teardown: Drop all tables after the test function completes
    with flask_app.app_context():
        db.session.remove() # Ensure session is closed
        db.drop_all() # Drop all tables defined by models

# --- Test Cases for API Endpoints ---

def test_index_route(client: FlaskClient):
    """Test the main '/' route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Power Curve Analyzer" in response.data

# === Tests for Authentication API Endpoints ===

# --- /api/register ---

def test_register_success(client: FlaskClient):
    """Test successful user registration."""
    response = client.post('/api/register', json={
        'username': 'newuser',
        'password': 'password123'
    })
    assert response.status_code == 201 # Created
    assert response.content_type == 'application/json'
    assert response.json == {"message": "User registered successfully"}

    # Verify user exists in DB (within app context)
    with flask_app.app_context():
        user = db.session.execute(db.select(User).filter_by(username='newuser')).scalar_one_or_none()
        assert user is not None
        assert user.username == 'newuser'
        assert user.check_password('password123') # Verify password hash

def test_register_username_exists(client: FlaskClient):
    """Test registration with an existing username."""
    # First, register a user
    client.post('/api/register', json={'username': 'existinguser', 'password': 'password123'})
    # Then, try to register the same username again
    response = client.post('/api/register', json={
        'username': 'existinguser',
        'password': 'anotherpassword'
    })
    assert response.status_code == 409 # Conflict
    assert response.content_type == 'application/json'
    assert "error" in response.json
    assert "Username already exists" in response.json["error"]

def test_register_missing_data(client: FlaskClient):
    """Test registration with missing username or password."""
    response = client.post('/api/register', json={'username': 'newuser'}) # Missing password
    assert response.status_code == 400 # Bad Request
    assert "Username and password required" in response.json["error"]

    response = client.post('/api/register', json={'password': 'password123'}) # Missing username
    assert response.status_code == 400 # Bad Request
    assert "Username and password required" in response.json["error"]

def test_register_short_password(client: FlaskClient):
    """Test registration with too short password."""
    response = client.post('/api/register', json={'username': 'newuser', 'password': '123'})
    assert response.status_code == 400 # Bad Request
    assert "password >= 6 chars" in response.json["error"]

# --- /api/login ---

def test_login_success(client: FlaskClient):
    """Test successful user login."""
    # Register user first
    client.post('/api/register', json={'username': 'loginuser', 'password': 'password123'})
    # Attempt login
    response = client.post('/api/login', json={
        'username': 'loginuser',
        'password': 'password123'
    })
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == {"message": "Login successful", "username": "loginuser"}
    # **FIX:** Check if the Set-Cookie header exists, indicating session/remember token was set
    assert 'Set-Cookie' in response.headers

def test_login_wrong_password(client: FlaskClient):
    """Test login with incorrect password."""
    client.post('/api/register', json={'username': 'loginuser', 'password': 'password123'})
    response = client.post('/api/login', json={
        'username': 'loginuser',
        'password': 'wrongpassword'
    })
    assert response.status_code == 401 # Unauthorized
    assert "Invalid username or password" in response.json["error"]

def test_login_user_not_found(client: FlaskClient):
    """Test login with a username that doesn't exist."""
    response = client.post('/api/login', json={
        'username': 'nosuchuser',
        'password': 'password123'
    })
    assert response.status_code == 401 # Unauthorized
    assert "Invalid username or password" in response.json["error"]

def test_login_missing_data(client: FlaskClient):
    """Test login with missing username or password."""
    response = client.post('/api/login', json={'username': 'loginuser'}) # Missing password
    assert response.status_code == 400 # Bad Request
    assert "Username and password required" in response.json["error"]

# --- /api/status ---

def test_status_logged_out(client: FlaskClient):
    """Test /api/status when not logged in."""
    response = client.get('/api/status')
    assert response.status_code == 200
    assert response.json == {"logged_in": False}

def test_status_logged_in(client: FlaskClient):
    """Test /api/status when logged in."""
    # Register and login
    client.post('/api/register', json={'username': 'statususer', 'password': 'password123'})
    login_response = client.post('/api/login', json={'username': 'statususer', 'password': 'password123'})
    assert login_response.status_code == 200

    # Check status (client maintains session cookie automatically)
    status_response = client.get('/api/status')
    assert status_response.status_code == 200
    assert status_response.json["logged_in"] is True
    assert status_response.json["user"]["username"] == "statususer"
    assert "id" in status_response.json["user"]

# --- /api/logout ---

def test_logout_success(client: FlaskClient):
    """Test successful logout."""
    # Register and login
    client.post('/api/register', json={'username': 'logoutuser', 'password': 'password123'})
    client.post('/api/login', json={'username': 'logoutuser', 'password': 'password123'})

    # Logout
    logout_response = client.post('/api/logout')
    assert logout_response.status_code == 200
    assert logout_response.json == {"message": "Logout successful"}

    # Verify status after logout
    status_response = client.get('/api/status')
    assert status_response.status_code == 200
    assert status_response.json == {"logged_in": False}

def test_logout_when_not_logged_in(client: FlaskClient):
    """Test accessing /api/logout when not logged in."""
    response = client.post('/api/logout')
    # Flask-Login typically returns 401 Unauthorized for @login_required
    assert response.status_code == 401

# === Tests for Protected Routes ===

def test_protected_routes_unauthorized(client: FlaskClient):
    """Test accessing protected routes without logging in."""
    # Placeholder routes that should require login
    protected_routes = ['/api/files', '/api/powercurve'] # Add more as needed

    for route in protected_routes:
        if route == '/api/powercurve': # Power curve expects POST
             response = client.post(route, json={})
        else: # Assume GET for others for now
             response = client.get(route)

        assert response.status_code == 401, f"Route {route} did not return 401 Unauthorized"

