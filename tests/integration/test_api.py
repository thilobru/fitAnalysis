import pytest
import json
import os
from datetime import date

# Import the Flask app instance from your app file
from app import app as flask_app

# --- Pytest Fixture for Flask Test Client ---

@pytest.fixture
def client():
    """Create a Flask test client instance for testing API requests."""
    flask_app.config['TESTING'] = True
    # Use a clearly non-existent path as default FIT_DIR for safety
    # Tests requiring file interaction will override this using tmp_path
    flask_app.config['FIT_DIR'] = 'test_api_temp_fit_dir_should_not_exist'
    with flask_app.test_client() as client:
        yield client

# --- Test Cases for API Endpoints ---

def test_index_route(client):
    """Test the main '/' route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Power Curve Analyzer" in response.data
    assert b"startDate" in response.data

# === Tests for /api/files ===

def test_api_files_success(client, mocker):
    """Test /api/files endpoint successfully returns mocked file details."""
    mock_details = [
        {"filename": "activity_2.fit", "date": "2023-10-21"},
        {"filename": "activity_1.fit", "date": "2023-10-20"}
    ]
    # Mock the function within the 'app' module that the route calls
    mocker.patch('app.get_fit_file_details', return_value=mock_details)

    response = client.get('/api/files')

    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == mock_details

def test_api_files_empty(client, mocker):
    """Test /api/files endpoint when no files are found."""
    mocker.patch('app.get_fit_file_details', return_value=[])

    response = client.get('/api/files')

    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == []

# === Tests for /api/powercurve ===

def test_api_powercurve_success(client, mocker, tmp_path):
    """Test /api/powercurve successful calculation."""
    # 1. Mock file scanner results
    mock_file_details = [
        {"filename": "test1_2023-05-10.fit", "date": "2023-05-10"},
        {"filename": "test2_2023-05-11.fit", "date": "2023-05-11"},
        {"filename": "test3_2023-05-12.fit", "date": "2023-05-12"} # Outside range
    ]
    mocker.patch('app.get_fit_file_details', return_value=mock_file_details)

    # 2. Mock calculation results
    mock_power_curve = {
        "1": 300.0, "5": 280.5, "60": 250.1
    }
    mock_calculator = mocker.patch('app.calculate_aggregate_power_curve', return_value=mock_power_curve)

    # 3. Set FIT_DIR config for this test
    # Ensure the app uses the temporary directory for path construction
    flask_app.config['FIT_DIR'] = str(tmp_path)

    # 4. Define request payload
    request_data = {"startDate": "2023-05-10", "endDate": "2023-05-11"}

    # 5. Make the POST request
    response = client.post('/api/powercurve', json=request_data)

    # 6. Assert response
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == mock_power_curve

    # 7. Verify the calculator mock was called correctly
    mock_calculator.assert_called_once() # Check it was called exactly once

    # Check the *filenames* passed, not the full paths, for robustness
    # Get the arguments the mock was called with
    actual_call_args, actual_call_kwargs = mock_calculator.call_args
    # Extract the list of file paths from the arguments
    actual_paths_passed = actual_call_args[0]
    # Extract just the basenames (filenames) from the paths passed
    actual_filenames_passed = [os.path.basename(p) for p in actual_paths_passed]

    # Define the expected filenames based on the date range
    expected_filenames = [
        "test1_2023-05-10.fit",
        "test2_2023-05-11.fit"
    ]
    # Assert that the set of passed filenames matches the expected set
    # Using sets ignores order and handles potential duplicates if logic allowed them
    assert set(actual_filenames_passed) == set(expected_filenames)

def test_api_powercurve_no_files_in_range(client, mocker, tmp_path):
    """Test /api/powercurve when date range selects no files."""
    mock_file_details = [
        {"filename": "test1_2023-05-10.fit", "date": "2023-05-10"},
    ]
    mocker.patch('app.get_fit_file_details', return_value=mock_file_details)
    mock_calculator = mocker.patch('app.calculate_aggregate_power_curve')
    flask_app.config['FIT_DIR'] = str(tmp_path)

    request_data = {"startDate": "2023-06-01", "endDate": "2023-06-02"}
    response = client.post('/api/powercurve', json=request_data)

    assert response.status_code == 404
    assert response.content_type == 'application/json'
    assert "error" in response.json
    assert "No FIT files found" in response.json["error"]
    mock_calculator.assert_not_called()

def test_api_powercurve_bad_request_missing_date(client):
    """Test /api/powercurve with missing date parameters."""
    response = client.post('/api/powercurve', json={"startDate": "2023-05-10"})
    assert response.status_code == 400
    assert "error" in response.json
    assert "Missing" in response.json["error"]

def test_api_powercurve_bad_request_invalid_date_format(client):
    """Test /api/powercurve with invalid date format."""
    request_data = {"startDate": "10-05-2023", "endDate": "11-05-2023"}
    response = client.post('/api/powercurve', json=request_data)
    assert response.status_code == 400
    assert "error" in response.json
    assert "Invalid date format" in response.json["error"]

def test_api_powercurve_calculation_error(client, mocker, tmp_path):
    """Test /api/powercurve when the calculation function returns None (error)."""
    mock_file_details = [
        {"filename": "test1_2023-05-10.fit", "date": "2023-05-10"},
    ]
    mocker.patch('app.get_fit_file_details', return_value=mock_file_details)
    mocker.patch('app.calculate_aggregate_power_curve', return_value=None) # Simulate calculation failure
    flask_app.config['FIT_DIR'] = str(tmp_path)

    request_data = {"startDate": "2023-05-10", "endDate": "2023-05-10"}
    response = client.post('/api/powercurve', json=request_data)

    assert response.status_code == 500
    assert "error" in response.json
    assert "Failed to calculate" in response.json["error"]
