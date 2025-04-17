# tests/integration/test_api.py

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

# Import models from new location
from app.models import User, FitFile, db # Import db for direct manipulation
# Import PowerCurveData type if needed
from app.services import PowerCurveData # Import type from services

# Note: Fixtures 'client' and 'logged_in_client' are expected from tests/conftest.py

# --- Test Cases ---

def test_index_route(client: FlaskClient):
    """Test the main '/' route."""
    response = client.get('/') # Path defined in main blueprint
    assert response.status_code == 200
    assert b"Power Curve Analyzer" in response.data

# === Tests for Authentication API Endpoints ===
def test_register_success(client: FlaskClient):
    """Test successful user registration."""
    response = client.post('/api/register', json={'username': 'newuser','password': 'password123'}) # Path defined by auth blueprint
    assert response.status_code == 201
    # Verify user exists in DB using the db fixture from conftest
    user = db.session.execute(db.select(User).filter_by(username='newuser')).scalar_one_or_none()
    assert user is not None
    assert user.check_password('password123')

def test_register_username_exists(client: FlaskClient):
    """Test registration with an existing username."""
    client.post('/api/register', json={'username': 'existinguser', 'password': 'password123'})
    response = client.post('/api/register', json={'username': 'existinguser', 'password': 'anotherpassword'}) # Path defined by auth blueprint
    assert response.status_code == 409

def test_register_missing_data(client: FlaskClient):
    """Test registration with missing username or password."""
    response = client.post('/api/register', json={'username': 'newuser'}) # Path defined by auth blueprint
    assert response.status_code == 400
    response = client.post('/api/register', json={'password': 'password123'}) # Path defined by auth blueprint
    assert response.status_code == 400

def test_register_short_password(client: FlaskClient):
    """Test registration with too short password."""
    response = client.post('/api/register', json={'username': 'newuser', 'password': '123'}) # Path defined by auth blueprint
    assert response.status_code == 400

def test_login_success(logged_in_client: Tuple[FlaskClient, User]):
    """Test successful user login (implicitly tested by fixture setup)."""
    client, user = logged_in_client
    # Check status to confirm login
    response = client.get('/api/status') # Path defined by auth blueprint
    assert response.status_code == 200
    assert response.json['logged_in'] is True
    assert response.json['user']['username'] == user.username
    # Check if Set-Cookie header exists after login (handled by fixture)
    # Note: Accessing headers directly on the client after multiple requests
    # might not be reliable. Checking status is a better indicator here.

def test_login_wrong_password(client: FlaskClient):
    """Test login with incorrect password."""
    client.post('/api/register', json={'username': 'loginuser', 'password': 'password123'})
    response = client.post('/api/login', json={'username': 'loginuser', 'password': 'wrongpassword'}) # Path defined by auth blueprint
    assert response.status_code == 401 # Should be 401 now

def test_login_user_not_found(client: FlaskClient):
    """Test login with a username that doesn't exist."""
    response = client.post('/api/login', json={'username': 'nosuchuser', 'password': 'password123'}) # Path defined by auth blueprint
    assert response.status_code == 401 # Should be 401 now

def test_login_missing_data(client: FlaskClient):
    """Test login with missing username or password."""
    response = client.post('/api/login', json={'username': 'loginuser'}) # Path defined by auth blueprint
    assert response.status_code == 400 # Should be 400 now

def test_status_logged_out(client: FlaskClient):
    """Test /api/status when not logged in."""
    response = client.get('/api/status') # Path defined by auth blueprint
    assert response.status_code == 200
    assert response.json == {"logged_in": False} # Should be false now

def test_status_logged_in(logged_in_client: Tuple[FlaskClient, User]):
    """Test /api/status when logged in."""
    client, user = logged_in_client
    status_response = client.get('/api/status') # Path defined by auth blueprint
    assert status_response.status_code == 200
    assert status_response.json["logged_in"] is True
    assert status_response.json["user"]["username"] == user.username

def test_logout_success(logged_in_client: Tuple[FlaskClient, User]):
    """Test successful logout."""
    client, user = logged_in_client
    logout_response = client.post('/api/logout') # Path defined by auth blueprint
    assert logout_response.status_code == 200
    status_response = client.get('/api/status') # Path defined by auth blueprint
    assert status_response.json == {"logged_in": False}

def test_logout_when_not_logged_in(client: FlaskClient):
    """Test accessing /api/logout when not logged in."""
    response = client.post('/api/logout') # Path defined by auth blueprint
    assert response.status_code == 401

# === Tests for File Management API Endpoints ===

def test_upload_success(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture, tmp_path: Path):
    """Test successful file upload."""
    client, user = logged_in_client
    test_fit_dir = tmp_path / "test_uploads"
    user_specific_dir = test_fit_dir / str(user.id)
    user_specific_dir.mkdir(parents=True, exist_ok=True)

    mocker.patch.dict(client.application.config, {"FIT_DIR": str(test_fit_dir)})

    # Mock functions needed BEFORE the save happens or for metadata
    mock_getsize = mocker.patch('os.path.getsize', return_value=12345)

    # --- IMPORTANT: Mock the function WHERE IT IS USED ---
    # The function is called from app.files.routes
    mock_extract_date = mocker.patch(
        'app.files.routes._extract_activity_date', # Patch the function *as used* in the files blueprint routes
        return_value=date(2024, 1, 15)
    )

    mock_uuid_val = uuid.UUID('12345678-1234-5678-1234-567812345678')
    mocker.patch('uuid.uuid4', return_value=mock_uuid_val)
    mock_makedirs = mocker.patch('os.makedirs')

    expected_relative_filename = f"{user.id}/{mock_uuid_val}.fit"
    expected_save_path = test_fit_dir / expected_relative_filename

    file_data = {'file': (io.BytesIO(b"dummy fit data"), 'test_activity.fit')}
    response = client.post('/api/files', data=file_data, content_type='multipart/form-data')

    assert response.status_code == 201, f"API Response: {response.get_data(as_text=True)}"
    assert response.json['message'] == "File uploaded successfully"
    assert response.json['file']['filename'] == 'test_activity.fit'
    # *** THE KEY ASSERTION ***
    assert response.json['file']['date'] == '2024-01-15' # Check if mock worked
    assert response.json['file']['status'] == 'uploaded'
    file_id = response.json['file']['id']

    mock_makedirs.assert_called_once_with(str(user_specific_dir), exist_ok=True)
    # Check that the mocked date extraction was called with the correct path
    mock_extract_date.assert_called_once_with(str(expected_save_path))
    mock_getsize.assert_called_once_with(str(expected_save_path))

    fit_file = db.session.get(FitFile, file_id)
    assert fit_file is not None
    assert fit_file.user_id == user.id
    assert fit_file.original_filename == 'test_activity.fit'
    assert fit_file.storage_path == expected_relative_filename
    assert fit_file.filesize == 12345
    assert fit_file.activity_date == date(2024, 1, 15)


def test_upload_no_file(logged_in_client: Tuple[FlaskClient, User]):
    """Test upload request with no file part."""
    client, _ = logged_in_client
    response = client.post('/api/files', data={}, content_type='multipart/form-data') # Path from files blueprint
    assert response.status_code == 400

def test_upload_disallowed_extension(logged_in_client: Tuple[FlaskClient, User]):
    """Test upload with a non-FIT file."""
    client, _ = logged_in_client
    file_data = {'file': (io.BytesIO(b"dummy data"), 'test_activity.txt')}
    response = client.post('/api/files', data=file_data, content_type='multipart/form-data') # Path from files blueprint
    assert response.status_code == 400

# --- GET /api/files (List) ---

def test_list_files_empty(logged_in_client: Tuple[FlaskClient, User]):
    """Test listing files when user has none."""
    client, _ = logged_in_client
    response = client.get('/api/files') # Path from files blueprint
    assert response.status_code == 200
    assert response.json == []

def test_list_files_success(logged_in_client: Tuple[FlaskClient, User]):
    """Test listing files successfully."""
    client, user = logged_in_client
    # Use db fixture from conftest
    ts1 = datetime(2023,10,10,10,0,0, tzinfo=timezone.utc); ts2 = datetime(2023,10,11,11,0,0, tzinfo=timezone.utc)
    f1 = FitFile(user_id=user.id, original_filename="ride1.fit", storage_path=f"{user.id}/uuid1.fit", activity_date=date(2023, 10, 10), upload_timestamp=ts1)
    f2 = FitFile(user_id=user.id, original_filename="ride2.fit", storage_path=f"{user.id}/uuid2.fit", activity_date=date(2023, 10, 11), upload_timestamp=ts2)
    db.session.add_all([f1, f2]); db.session.commit(); f1_id, f2_id = f1.id, f2.id

    response = client.get('/api/files') # Path from files blueprint
    assert response.status_code == 200; assert len(response.json) == 2; assert response.json[0]['filename'] == 'ride2.fit'; assert response.json[1]['filename'] == 'ride1.fit'

def test_list_files_isolation(client: FlaskClient): # Use base client
    """Test that listing files only returns files for the logged-in user."""
    # User A
    client.post('/api/register', json={'username': 'user_a', 'password': 'password_a'}); client.post('/api/login', json={'username': 'user_a', 'password': 'password_a'})
    f_a_id = None; user_a = db.session.execute(db.select(User).filter_by(username='user_a')).scalar_one(); f_a = FitFile(user_id=user_a.id, original_filename="ride_a.fit", storage_path=f"{user_a.id}/uuid_a.fit"); db.session.add(f_a); db.session.commit(); f_a_id = f_a.id
    client.post('/api/logout')
    # User B
    client.post('/api/register', json={'username': 'user_b', 'password': 'password_b'}); client.post('/api/login', json={'username': 'user_b', 'password': 'password_b'})
    f_b_id = None; user_b = db.session.execute(db.select(User).filter_by(username='user_b')).scalar_one(); f_b = FitFile(user_id=user_b.id, original_filename="ride_b.fit", storage_path=f"{user_b.id}/uuid_b.fit"); db.session.add(f_b); db.session.commit(); f_b_id = f_b.id
    # Get files as B
    response = client.get('/api/files') # Path from files blueprint
    assert response.status_code == 200; assert len(response.json) == 1; assert response.json[0]['id'] == f_b_id; assert response.json[0]['filename'] == 'ride_b.fit'

# --- DELETE /api/files/<id> ---

def test_delete_file_success(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture, tmp_path: Path):
    """Test successful file deletion."""
    client, user = logged_in_client
    test_fit_dir = tmp_path / "test_delete"
    # Ensure base directory exists for get_full_path helper
    test_fit_dir.mkdir(exist_ok=True)

    # Patch config AFTER creating directory
    mocker.patch.dict(client.application.config, {"FIT_DIR": str(test_fit_dir)})

    storage_path = os.path.join(str(user.id), "delete_uuid.fit")
    # Use the FitFile model's helper method within app context to get expected path
    full_path = None
    file_id = None
    with client.application.app_context():
        fit_file = FitFile(user_id=user.id, original_filename="delete_me.fit", storage_path=storage_path)
        db.session.add(fit_file)
        db.session.commit()
        file_id = fit_file.id
        # Now that fit_file is committed and has an ID, call get_full_path
        # This needs the app context to access current_app.config['FIT_DIR']
        full_path = fit_file.get_full_path()

    assert full_path is not None, "Could not determine full path in test setup"
    # Create the user directory and dummy file to be deleted
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w') as f: f.write("dummy data")

    # Mock os.remove - os.path.exists will work because we created the file
    mock_remove = mocker.patch('os.remove')
    mock_exists = mocker.patch('os.path.exists', return_value=True) # Can still mock exists if needed

    response = client.delete(f'/api/files/{file_id}') # Path from files blueprint

    assert response.status_code == 200
    mock_exists.assert_called_once_with(full_path) # Check that exists was called
    mock_remove.assert_called_once_with(full_path) # Check that remove was called
    assert db.session.get(FitFile, file_id) is None

def test_delete_file_not_found(logged_in_client: Tuple[FlaskClient, User]):
    """Test deleting a non-existent file ID."""
    client, _ = logged_in_client
    response = client.delete('/api/files/99999') # Path from files blueprint
    assert response.status_code == 404

def test_delete_file_wrong_user(client: FlaskClient): # Use base client
    """Test deleting a file belonging to another user."""
    # User A creates file
    client.post('/api/register', json={'username': 'user_a', 'password': 'password_a'}); client.post('/api/login', json={'username': 'user_a', 'password': 'password_a'})
    file_id_a = None; user_a = db.session.execute(db.select(User).filter_by(username='user_a')).scalar_one(); f_a = FitFile(user_id=user_a.id, original_filename="ride_a.fit", storage_path=f"{user_a.id}/uuid_a.fit"); db.session.add(f_a); db.session.commit(); file_id_a = f_a.id
    client.post('/api/logout')
    # User B logs in
    client.post('/api/register', json={'username': 'user_b', 'password': 'password_b'}); client.post('/api/login', json={'username': 'user_b', 'password': 'password_b'})
    # User B tries delete User A's file
    response = client.delete(f'/api/files/{file_id_a}') # Path from files blueprint
    assert response.status_code == 404 # API returns 404 as file not found for this user

# --- POST /api/powercurve (User Specific) ---

# FIX 2: Corrected test_powercurve_user_specific_success
def test_powercurve_user_specific_success(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture, tmp_path: Path):
    """Test successful power curve calculation for logged-in user's files."""
    client, user = logged_in_client
    user_id_str = str(user.id)
    test_fit_dir = tmp_path / "test_pc"
    test_fit_dir.mkdir() # Create base directory for FIT files

    # Patch config
    mocker.patch.dict(client.application.config, {"FIT_DIR": str(test_fit_dir)})

    expected_paths_to_check = []
    # Use db fixture from conftest
    # Use app context for database operations and get_full_path
    with client.application.app_context():
        # Define relative storage paths
        f1_sp = os.path.join(user_id_str, "pc_uuid1.fit")
        f2_sp = os.path.join(user_id_str, "pc_uuid2.fit")
        f3_sp = os.path.join(user_id_str, "pc_uuid3.fit")

        # Create FitFile records in DB
        f1 = FitFile(user_id=user.id, original_filename="pc_ride1.fit", storage_path=f1_sp, activity_date=date(2024, 2, 10))
        f2 = FitFile(user_id=user.id, original_filename="pc_ride2.fit", storage_path=f2_sp, activity_date=date(2024, 2, 11))
        f3 = FitFile(user_id=user.id, original_filename="pc_ride3.fit", storage_path=f3_sp, activity_date=date(2024, 2, 15)) # Outside date range
        db.session.add_all([f1, f2, f3])
        db.session.commit()

        # Get expected full paths using the model's helper method *after* commit
        f1_refetched = db.session.get(FitFile, f1.id)
        f2_refetched = db.session.get(FitFile, f2.id)
        expected_paths_to_check = [f1_refetched.get_full_path(), f2_refetched.get_full_path()]

        # --- IMPORTANT: Create dummy files/dirs ---
        # The route checks os.path.isfile, so we need the files OR mock isfile
        # Mocking isfile is easier if we ONLY want to test the route logic and mock the calculation
        # If we wanted the calculation to run on dummy data, we'd create files here.
        # Let's mock isfile as the original test did.
        mock_isfile = mocker.patch('os.path.isfile', return_value=True) # Mock this to bypass filesystem check in route

        # Define mock results for power curve
        mock_power_curve_result: PowerCurveData = { 1: 250.0, 5: 240.0, 60: 200.0 }
        mock_power_curve_json: Dict[str, float] = { "1": 250.0, "5": 240.0, "60": 200.0 }

        # --- IMPORTANT: Mock the function WHERE IT IS USED ---
        # The function is imported and used in app.analysis.routes
        mock_calculator = mocker.patch(
            'app.analysis.routes.calculate_aggregate_power_curve', # Target the usage location
            return_value=mock_power_curve_result
        )

        # Define request data
        request_data = {"startDate": "2024-02-10", "endDate": "2024-02-14"}

        # --- Perform API Call ---
        response = client.post('/api/powercurve', json=request_data) # Path from analysis blueprint

        # --- Assertions ---
        assert response.status_code == 200, f"API Response: {response.get_data(as_text=True)}"
        assert response.json == mock_power_curve_json

        # Check that os.path.isfile was called for the files in range
        assert mock_isfile.call_count == len(expected_paths_to_check) # Should be called for f1 and f2
        for path in expected_paths_to_check:
            mock_isfile.assert_any_call(path)

        # Check that the mocked calculator was called correctly
        mock_calculator.assert_called_once_with(expected_paths_to_check) # Verify mock called with correct full paths


def test_powercurve_user_no_files_in_range(logged_in_client: Tuple[FlaskClient, User], mocker: MockerFixture, tmp_path: Path):
    """Test power curve when user has no files in the selected date range."""
    client, user = logged_in_client
    test_fit_dir = tmp_path / "test_pc_no_files"
    test_fit_dir.mkdir()
    mocker.patch.dict(client.application.config, {"FIT_DIR": str(test_fit_dir)})

    with client.application.app_context(): # Use app context
        # Add a file outside the test range
        f1 = FitFile(user_id=user.id, original_filename="pc_ride1.fit", storage_path=f"{user.id}/pc_uuid1.fit", activity_date=date(2024, 2, 10))
        db.session.add(f1); db.session.commit()

    # Mock the calculation function (even though it shouldn't be called)
    mock_calculator = mocker.patch('app.analysis.routes.calculate_aggregate_power_curve')

    request_data = {"startDate": "2024-03-01", "endDate": "2024-03-31"}
    response = client.post('/api/powercurve', json=request_data) # Path from analysis blueprint

    assert response.status_code == 200
    assert response.json == {} # Expect empty JSON for no data
    mock_calculator.assert_not_called() # Verify calculation wasn't triggered


def test_api_powercurve_bad_request_invalid_date_format_logged_in(logged_in_client: Tuple[FlaskClient, User]):
    """Test /api/powercurve with invalid date format when logged in."""
    client, _ = logged_in_client
    request_data: Dict[str, str] = {"startDate": "10-02-2024", "endDate": "11-02-2024"}
    response = client.post('/api/powercurve', json=request_data) # Path from analysis blueprint
    assert response.status_code == 400

# === Tests for Protected Routes ===
def test_protected_routes_unauthorized(client: FlaskClient):
    """Test accessing protected routes without logging in."""
    # Note: Paths are now prefixed with /api from blueprints
    protected_routes = [
        ('/api/files', 'GET'),
        ('/api/files', 'POST'),
        ('/api/files/1', 'DELETE'),
        ('/api/powercurve', 'POST'),
        ('/api/logout', 'POST') # Auth blueprint also uses /api prefix
    ]
    for route, method in protected_routes:
        if method == 'POST': response = client.post(route, json={})
        elif method == 'DELETE': response = client.delete(route)
        else: response = client.get(route)
        assert response.status_code == 401, f"Route {method} {route} did not return 401 Unauthorized"