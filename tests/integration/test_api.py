import pytest
import json
import os
import io # For simulating file uploads
import uuid
from datetime import date, datetime, timezone
from typing import List, Dict, Generator, Any, Tuple
from flask.testing import FlaskClient
from pathlib import Path
from pytest_mock import MockerFixture # Import mocker type hint

# Import the Flask app instance and DB objects/models from your app file
# Ensure FIT_DIR is imported if needed, or rely on app.config
from app import app as flask_app, db, User, FitFile, PowerCurveData

# --- Pytest Fixtures ---

@pytest.fixture(scope='function') # Run setup/teardown for each test function
def client() -> Generator[FlaskClient, None, None]:
    """Create a Flask test client instance with isolated DB state for each test."""
    # Configure app for testing
    # Use a distinct test database URI if possible, or ensure clean state
    TEST_DB_URL = os.getenv('TEST_DATABASE_URL', 'postgresql+psycopg://user:password@db:5432/fit_analyzer_test_db') # Use a test DB if possible
    # Fallback to default if TEST_DATABASE_URL not set - ensure DB container uses same creds/db name
    DB_URL = os.getenv('DATABASE_URL', 'postgresql+psycopg://user:password@db:5432/fit_analyzer_db')
    # Prefer TEST_DB_URL if set, otherwise use regular DB_URL
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = TEST_DB_URL if 'TEST_DATABASE_URL' in os.environ else DB_URL
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False # Disable CSRF for simpler API testing
    flask_app.config['SECRET_KEY'] = 'test-secret-key' # Use a fixed secret key for tests
    # Set a default FIT_DIR in config for tests (can be overridden per test)
    flask_app.config['FIT_DIR'] = '/tmp/pytest_fit_dir_default'


    # Establish application context and manage database schema
    with flask_app.app_context():
        db.create_all() # Create tables based on models

    # Create a test client using the Flask application context
    with flask_app.test_client() as client:
        yield client # Provide the client to the test functions

    # Teardown: Drop all tables after the test function completes
    with flask_app.app_context():
        db.session.remove() # Ensure session is closed
        db.drop_all() # Drop all tables defined by models

@pytest.fixture(scope='function')
def logged_in_client(client: FlaskClient) -> Tuple[FlaskClient, User]:
    """Fixture to provide a test client that is already logged in."""
    username = 'testuser'
    password = 'password123'
    # Register user via API (uses the client fixture's clean DB)
    reg_response = client.post('/api/register', json={'username': username, 'password': password})
    assert reg_response.status_code == 201, "Fixture setup failed: Registration failed"
    # Login via API
    login_response = client.post('/api/login', json={'username': username, 'password': password})
    assert login_response.status_code == 200, "Fixture setup failed: Login failed"
    # Retrieve user object for reference in tests
    with flask_app.app_context():
        user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one()
    yield client, user # Provide client and user object
    # Logout is not strictly necessary as DB is dropped by client fixture teardown

# --- Test Cases ---

def test_index_route(client: FlaskClient):
    """Test the main '/' route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Power Curve Analyzer" in response.data

# === Tests for Authentication API Endpoints ===
# (These tests remain the same as before)
def test_register_success(client: FlaskClient): # ...
    response = client.post('/api/register', json={'username': 'newuser','password': 'password123'})
    assert response.status_code == 201
    with flask_app.app_context(): user = db.session.execute(db.select(User).filter_by(username='newuser')).scalar_one_or_none(); assert user is not None; assert user.check_password('password123')

def test_register_username_exists(client: FlaskClient): # ...
    client.post('/api/register', json={'username': 'existinguser', 'password': 'password123'}); response = client.post('/api/register', json={'username': 'existinguser', 'password': 'anotherpassword'}); assert response.status_code == 409

def test_register_missing_data(client: FlaskClient): # ...
    response = client.post('/api/register', json={'username': 'newuser'}); assert response.status_code == 400; response = client.post('/api/register', json={'password': 'password123'}); assert response.status_code == 400

def test_register_short_password(client: FlaskClient): # ...
    response = client.post('/api/register', json={'username': 'newuser', 'password': '123'}); assert response.status_code == 400

def test_login_success(logged_in_client: Tuple[FlaskClient, User]): # Use logged_in_client fixture implicitly
    """Test successful user login (implicitly tested by fixture setup)."""
    client, user = logged_in_client
    # Check status to confirm login
    response = client.get('/api/status')
    assert response.status_code == 200
    assert response.json['logged_in'] is True
    assert response.json['user']['username'] == user.username
    # Check that a cookie header was involved during login (done by fixture)
    # This check is now implicitly covered by the fixture success and status check

def test_login_wrong_password(client: FlaskClient): # ...
    client.post('/api/register', json={'username': 'loginuser', 'password': 'password123'}); response = client.post('/api/login', json={'username': 'loginuser', 'password': 'wrongpassword'}); assert response.status_code == 401

def test_login_user_not_found(client: FlaskClient): # ...
    response = client.post('/api/login', json={'username': 'nosuchuser', 'password': 'password123'}); assert response.status_code == 401

def test_login_missing_data(client: FlaskClient): # ...
    response = client.post('/api/login', json={'username': 'loginuser'}); assert response.status_code == 400

def test_status_logged_out(client: FlaskClient): # ...
    response = client.get('/api/status'); assert response.status_code == 200; assert response.json == {"logged_in": False}

def test_status_logged_in(logged_in_client: Tuple[FlaskClient, User]): # Use fixture
    client, user = logged_in_client
    status_response = client.get('/api/status'); assert status_response.status_code == 200; assert status_response.json["logged_in"] is True; assert status_response.json["user"]["username"] == user.username

def test_logout_success(logged_in_client: Tuple[FlaskClient, User]): # Use fixture
    client, user = logged_in_client; logout_response = client.post('/api/logout'); assert logout_response.status_code == 200; status_response = client.get('/api/status'); assert status_response.json == {"logged_in": False}

def test_logout_when_not_logged_in(client: FlaskClient): # ...
    response = client.post('/api/logout'); assert response.status_code == 401

# === Tests for File Management API Endpoints ===

# --- POST /api/files (Upload) ---

def test_upload_success(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture, tmp_path: Path):
    """Test successful file upload."""
    client, user = logged_in_client
    # Set FIT_DIR config specifically for this test using tmp_path
    test_fit_dir = str(tmp_path / "test_uploads")
    # Use mocker.patch.dict to temporarily modify app.config for this test
    mocker.patch.dict(flask_app.config, {"FIT_DIR": test_fit_dir})
    # Mock filesystem and helper functions
    mock_makedirs = mocker.patch('os.makedirs')
    mock_save = mocker.patch('werkzeug.datastructures.FileStorage.save')
    mock_getsize = mocker.patch('os.path.getsize', return_value=12345)
    mock_extract_date = mocker.patch('app._extract_activity_date', return_value=date(2024, 1, 15))
    mock_uuid_val = uuid.UUID('12345678-1234-5678-1234-567812345678') # Predictable UUID
    mocker.patch('uuid.uuid4', return_value=mock_uuid_val)

    # Simulate file upload data
    file_data = {'file': (io.BytesIO(b"dummy fit data"), 'test_activity.fit')}
    response = client.post('/api/files', data=file_data, content_type='multipart/form-data')

    # Assert response
    assert response.status_code == 201
    assert response.json['message'] == "File uploaded successfully"
    assert response.json['file']['filename'] == 'test_activity.fit'
    assert response.json['file']['date'] == '2024-01-15'
    assert response.json['file']['status'] == 'uploaded'
    file_id = response.json['file']['id']

    # Assert mocks were called correctly
    expected_user_dir = os.path.join(test_fit_dir, str(user.id))
    expected_filename = f"{mock_uuid_val}.fit"
    expected_save_path = os.path.join(expected_user_dir, expected_filename)
    mock_makedirs.assert_called_once_with(expected_user_dir, exist_ok=True)
    mock_save.assert_called_once_with(expected_save_path)
    mock_extract_date.assert_called_once_with(expected_save_path)
    mock_getsize.assert_called_once_with(expected_save_path)

    # Assert database record created
    with flask_app.app_context():
        fit_file = db.session.get(FitFile, file_id)
        assert fit_file is not None
        assert fit_file.user_id == user.id
        assert fit_file.original_filename == 'test_activity.fit'
        assert fit_file.storage_path == os.path.join(str(user.id), expected_filename) # Check relative path
        assert fit_file.filesize == 12345
        assert fit_file.activity_date == date(2024, 1, 15)

def test_upload_no_file(logged_in_client: Tuple[FlaskClient, User]):
    """Test upload request with no file part."""
    client, _ = logged_in_client
    response = client.post('/api/files', data={}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert "No file part" in response.json['error']

def test_upload_disallowed_extension(logged_in_client: Tuple[FlaskClient, User]):
    """Test upload with a non-FIT file."""
    client, _ = logged_in_client
    file_data = {'file': (io.BytesIO(b"dummy data"), 'test_activity.txt')}
    response = client.post('/api/files', data=file_data, content_type='multipart/form-data')
    assert response.status_code == 400
    assert "File type not allowed" in response.json['error']

# --- GET /api/files (List) ---

def test_list_files_empty(logged_in_client: Tuple[FlaskClient, User]):
    """Test listing files when user has none."""
    client, _ = logged_in_client
    response = client.get('/api/files')
    assert response.status_code == 200
    assert response.json == []

def test_list_files_success(logged_in_client: Tuple[FlaskClient, User]):
    """Test listing files successfully."""
    client, user = logged_in_client
    # Create some file records directly in DB for this user
    with flask_app.app_context():
        # Create timestamps for ordering check
        ts1 = datetime(2023,10,10,10,0,0, tzinfo=timezone.utc)
        ts2 = datetime(2023,10,11,11,0,0, tzinfo=timezone.utc)
        f1 = FitFile(user_id=user.id, original_filename="ride1.fit", storage_path=f"{user.id}/uuid1.fit", activity_date=date(2023, 10, 10), upload_timestamp=ts1)
        f2 = FitFile(user_id=user.id, original_filename="ride2.fit", storage_path=f"{user.id}/uuid2.fit", activity_date=date(2023, 10, 11), upload_timestamp=ts2)
        db.session.add_all([f1, f2])
        db.session.commit()
        # Keep IDs for assertion
        f1_id, f2_id = f1.id, f2.id

    response = client.get('/api/files')
    assert response.status_code == 200
    assert len(response.json) == 2
    # Response is ordered by upload desc
    assert response.json[0]['id'] == f2_id
    assert response.json[0]['filename'] == 'ride2.fit' # Use correct key 'filename'
    assert response.json[1]['id'] == f1_id
    assert response.json[1]['filename'] == 'ride1.fit' # Use correct key 'filename'

def test_list_files_isolation(client: FlaskClient):
    """Test that listing files only returns files for the logged-in user."""
    # Register user A, login, create file, logout
    client.post('/api/register', json={'username': 'user_a', 'password': 'password_a'})
    client.post('/api/login', json={'username': 'user_a', 'password': 'password_a'})
    f_a_id = None
    with flask_app.app_context():
         user_a = db.session.execute(db.select(User).filter_by(username='user_a')).scalar_one()
         f_a = FitFile(user_id=user_a.id, original_filename="ride_a.fit", storage_path=f"{user_a.id}/uuid_a.fit")
         db.session.add(f_a); db.session.commit(); f_a_id = f_a.id
    client.post('/api/logout')

    # Register user B, login, create file
    client.post('/api/register', json={'username': 'user_b', 'password': 'password_b'})
    client.post('/api/login', json={'username': 'user_b', 'password': 'password_b'})
    f_b_id = None
    with flask_app.app_context():
         user_b = db.session.execute(db.select(User).filter_by(username='user_b')).scalar_one()
         f_b = FitFile(user_id=user_b.id, original_filename="ride_b.fit", storage_path=f"{user_b.id}/uuid_b.fit")
         db.session.add(f_b); db.session.commit(); f_b_id = f_b.id

    # Get files as user B
    response = client.get('/api/files')
    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]['id'] == f_b_id
    assert response.json[0]['filename'] == 'ride_b.fit' # Use correct key 'filename'

# --- DELETE /api/files/<id> ---

def test_delete_file_success(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture, tmp_path: Path):
    """Test successful file deletion."""
    client, user = logged_in_client
    # Set FIT_DIR config for this test
    test_fit_dir = str(tmp_path / "test_delete")
    mocker.patch.dict(flask_app.config, {"FIT_DIR": test_fit_dir})
    storage_path = os.path.join(str(user.id), "delete_uuid.fit")
    full_path = os.path.join(test_fit_dir, storage_path) # Expected path

    # Create DB record
    file_id = None
    with flask_app.app_context():
        fit_file = FitFile(user_id=user.id, original_filename="delete_me.fit", storage_path=storage_path)
        db.session.add(fit_file); db.session.commit(); file_id = fit_file.id

    # Mock filesystem checks/actions
    mock_exists = mocker.patch('os.path.exists', return_value=True)
    mock_remove = mocker.patch('os.remove')

    # Send DELETE request
    response = client.delete(f'/api/files/{file_id}')

    # Assert response and actions
    assert response.status_code == 200 # API returns 200 OK on success
    assert response.json == {"message": "File deleted successfully"}
    mock_exists.assert_called_once_with(full_path)
    mock_remove.assert_called_once_with(full_path)

    # Assert DB record is gone
    with flask_app.app_context():
        deleted_file = db.session.get(FitFile, file_id)
        assert deleted_file is None

def test_delete_file_not_found(logged_in_client: Tuple[FlaskClient, User]):
    """Test deleting a non-existent file ID."""
    client, _ = logged_in_client
    response = client.delete('/api/files/99999') # ID likely doesn't exist
    assert response.status_code == 404

def test_delete_file_wrong_user(client: FlaskClient): # Needs base client
    """Test deleting a file belonging to another user."""
    # Register user A, login, create file, logout
    client.post('/api/register', json={'username': 'user_a', 'password': 'password_a'})
    client.post('/api/login', json={'username': 'user_a', 'password': 'password_a'})
    file_id_a = None
    with flask_app.app_context():
         user_a = db.session.execute(db.select(User).filter_by(username='user_a')).scalar_one()
         f_a = FitFile(user_id=user_a.id, original_filename="ride_a.fit", storage_path=f"{user_a.id}/uuid_a.fit")
         db.session.add(f_a); db.session.commit(); file_id_a = f_a.id
    client.post('/api/logout')
    # Register user B, login
    client.post('/api/register', json={'username': 'user_b', 'password': 'password_b'})
    client.post('/api/login', json={'username': 'user_b', 'password': 'password_b'})

    # Try delete user A's file as user B
    response = client.delete(f'/api/files/{file_id_a}')
    assert response.status_code == 404 # Should not find file for this user

# --- POST /api/powercurve (User Specific) ---

def test_powercurve_user_specific_success(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture, tmp_path: Path):
    """Test successful power curve calculation for logged-in user's files."""
    client, user = logged_in_client
    user_id_str = str(user.id)
    # Set FIT_DIR config for this test
    test_fit_dir = str(tmp_path / "test_pc")
    mocker.patch.dict(flask_app.config, {"FIT_DIR": test_fit_dir})

    # Create mock DB entries and expected paths *within app context*
    expected_paths_to_check = []
    with flask_app.app_context():
        f1 = FitFile(user_id=user.id, original_filename="pc_ride1.fit", storage_path=f"{user_id_str}/pc_uuid1.fit", activity_date=date(2024, 2, 10))
        f2 = FitFile(user_id=user.id, original_filename="pc_ride2.fit", storage_path=f"{user_id_str}/pc_uuid2.fit", activity_date=date(2024, 2, 11))
        f3 = FitFile(user_id=user.id, original_filename="pc_ride3.fit", storage_path=f"{user_id_str}/pc_uuid3.fit", activity_date=date(2024, 2, 15)) # Outside range
        db.session.add_all([f1, f2, f3])
        db.session.commit()
        # ** FIX: Get paths inside context **
        db_files_in_range = [f1, f2] # Files within range
        expected_paths_to_check = [f.get_full_path() for f in db_files_in_range]

    mock_isfile = mocker.patch('os.path.isfile', return_value=True)
    mock_power_curve_result: PowerCurveData = { 1: 250.0, 5: 240.0, 60: 200.0 }
    mock_power_curve_json: Dict[str, float] = { "1": 250.0, "5": 240.0, "60": 200.0 }
    mock_calculator = mocker.patch('app.calculate_aggregate_power_curve', return_value=mock_power_curve_result)

    request_data = {"startDate": "2024-02-10", "endDate": "2024-02-14"}
    response = client.post('/api/powercurve', json=request_data)

    assert response.status_code == 200
    assert response.json == mock_power_curve_json
    assert mock_isfile.call_count == len(expected_paths_to_check)
    for path in expected_paths_to_check: mock_isfile.assert_any_call(path)
    mock_calculator.assert_called_once_with(expected_paths_to_check)

def test_powercurve_user_no_files_in_range(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture):
    """Test power curve when user has no files in the selected date range."""
    client, user = logged_in_client
    with flask_app.app_context(): f1 = FitFile(user_id=user.id, original_filename="pc_ride1.fit", storage_path=f"{user.id}/pc_uuid1.fit", activity_date=date(2024, 2, 10)); db.session.add(f1); db.session.commit()
    mock_calculator = mocker.patch('app.calculate_aggregate_power_curve')
    request_data = {"startDate": "2024-03-01", "endDate": "2024-03-31"}
    response = client.post('/api/powercurve', json=request_data)
    assert response.status_code == 200
    assert response.json == {} # Expect empty result, not error
    mock_calculator.assert_not_called()

def test_api_powercurve_bad_request_invalid_date_format_logged_in(logged_in_client: Tuple[FlaskClient, User]):
    """Test /api/powercurve with invalid date format when logged in."""
    client, _ = logged_in_client
    request_data: Dict[str, str] = {"startDate": "10-02-2024", "endDate": "11-02-2024"}
    response = client.post('/api/powercurve', json=request_data)
    assert response.status_code == 400
    assert "Invalid date format" in response.json["error"]

# === Tests for Protected Routes (Ensure still covered) ===
def test_protected_routes_unauthorized(client: FlaskClient):
    """Test accessing protected routes without logging in."""
    protected_routes = [
        ('/api/files', 'GET'),
        ('/api/files', 'POST'),
        ('/api/files/1', 'DELETE'), # Need an ID, but should fail on auth first
        ('/api/powercurve', 'POST'),
        ('/api/logout', 'POST')
    ]
    for route, method in protected_routes:
        if method == 'POST': response = client.post(route, json={})
        elif method == 'DELETE': response = client.delete(route)
        else: response = client.get(route)
        assert response.status_code == 401, f"Route {method} {route} did not return 401 Unauthorized"

