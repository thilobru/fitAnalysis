import pytest
import json
import os
from datetime import date
from typing import List, Dict, Generator, Any
from flask.testing import FlaskClient
from pathlib import Path
from pytest_mock import MockerFixture # Import mocker type hint

# Import the Flask app instance from your app file
from app import app as flask_app, FitFileDetail, PowerCurveData # Import types

# --- Pytest Fixture for Flask Test Client ---

@pytest.fixture
def client() -> Generator[FlaskClient, None, None]:
    """Create a Flask test client instance for testing API requests."""
    flask_app.config['TESTING'] = True
    # No longer set FIT_DIR here, rely on env var mocking per test

    with flask_app.test_client() as client:
        yield client

# --- Test Cases for API Endpoints ---

def test_index_route(client: FlaskClient):
    """Test the main '/' route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Power Curve Analyzer" in response.data

# === Tests for /api/files ===

def test_api_files_success(client: FlaskClient, mocker: MockerFixture):
    """Test /api/files endpoint successfully returns mocked file details."""
    mock_details: List[FitFileDetail] = [
        {"filename": "activity_2.fit", "date": "2023-10-21"},
        {"filename": "activity_1.fit", "date": "2023-10-20"}
    ]
    # Mock the helper function that scans the directory
    mock_scanner = mocker.patch('app.get_fit_file_details', return_value=mock_details)
    # Mock os.getenv specific to how it's used for FIT_DIR in the route
    mocker.patch('os.getenv', return_value='mock_fit_dir') # Return a dummy dir path

    response = client.get('/api/files')

    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == mock_details
    # Verify scanner was called with the mocked directory path
    mock_scanner.assert_called_once_with('mock_fit_dir')

def test_api_files_empty(client: FlaskClient, mocker: MockerFixture):
    """Test /api/files endpoint when no files are found."""
    mock_scanner = mocker.patch('app.get_fit_file_details', return_value=[])
    mocker.patch('os.getenv', return_value='mock_fit_dir')

    response = client.get('/api/files')

    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == []
    mock_scanner.assert_called_once_with('mock_fit_dir')

# === Tests for /api/powercurve ===

def test_api_powercurve_success(client: FlaskClient, mocker: MockerFixture, tmp_path: Path):
    """Test /api/powercurve successful calculation."""
    # 1. Mock file scanner results
    mock_file_details: List[FitFileDetail] = [
        {"filename": "test1_2023-05-10.fit", "date": "2023-05-10"},
        {"filename": "test2_2023-05-11.fit", "date": "2023-05-11"},
        {"filename": "test3_2023-05-12.fit", "date": "2023-05-12"} # Outside range
    ]
    mock_scanner = mocker.patch('app.get_fit_file_details', return_value=mock_file_details)

    # 2. Mock calculation results (using string keys as returned by API)
    mock_power_curve_result: PowerCurveData = { 1: 300.0, 5: 280.5, 60: 250.1 }
    mock_power_curve_json: Dict[str, float] = { "1": 300.0, "5": 280.5, "60": 250.1 }
    mock_calculator = mocker.patch('app.calculate_aggregate_power_curve', return_value=mock_power_curve_result)

    # 3. Mock environment variable for FIT_DIR used within the route
    test_fit_dir = str(tmp_path)
    mocker.patch('os.getenv', return_value=test_fit_dir)

    # 4. Define request payload
    request_data: Dict[str, str] = {"startDate": "2023-05-10", "endDate": "2023-05-11"}

    # 5. Make the POST request
    response = client.post('/api/powercurve', json=request_data)

    # 6. Assert response
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == mock_power_curve_json # Compare with JSON-like dict

    # 7. Verify mocks were called correctly
    mock_scanner.assert_called_once_with(test_fit_dir)
    mock_calculator.assert_called_once()
    actual_call_args, _ = mock_calculator.call_args
    actual_paths_passed = actual_call_args[0]
    actual_filenames_passed = [os.path.basename(p) for p in actual_paths_passed]
    expected_filenames = ["test1_2023-05-10.fit", "test2_2023-05-11.fit"]
    assert set(actual_filenames_passed) == set(expected_filenames)

def test_api_powercurve_no_files_in_range(client: FlaskClient, mocker: MockerFixture, tmp_path: Path):
    """Test /api/powercurve when date range selects no files."""
    mock_file_details: List[FitFileDetail] = [
        {"filename": "test1_2023-05-10.fit", "date": "2023-05-10"},
    ]
    mock_scanner = mocker.patch('app.get_fit_file_details', return_value=mock_file_details)
    mock_calculator = mocker.patch('app.calculate_aggregate_power_curve')
    test_fit_dir = str(tmp_path)
    mocker.patch('os.getenv', return_value=test_fit_dir)

    request_data: Dict[str, str] = {"startDate": "2023-06-01", "endDate": "2023-06-02"}
    response = client.post('/api/powercurve', json=request_data)

    assert response.status_code == 404
    assert response.content_type == 'application/json'
    assert "error" in response.json
    assert "No FIT files found" in response.json["error"]
    mock_scanner.assert_called_once_with(test_fit_dir)
    mock_calculator.assert_not_called()

def test_api_powercurve_bad_request_missing_date(client: FlaskClient):
    """Test /api/powercurve with missing date parameters."""
    response = client.post('/api/powercurve', json={"startDate": "2023-05-10"})
    assert response.status_code == 400
    assert "error" in response.json
    assert "Missing" in response.json["error"]

def test_api_powercurve_bad_request_invalid_date_format(client: FlaskClient):
    """Test /api/powercurve with invalid date format."""
    request_data: Dict[str, str] = {"startDate": "10-05-2023", "endDate": "11-05-2023"}
    response = client.post('/api/powercurve', json=request_data)
    assert response.status_code == 400
    assert "error" in response.json
    assert "Invalid date format" in response.json["error"]

def test_api_powercurve_calculation_error(client: FlaskClient, mocker: MockerFixture, tmp_path: Path):
    """Test /api/powercurve when the calculation function returns None (error)."""
    mock_file_details: List[FitFileDetail] = [
        {"filename": "test1_2023-05-10.fit", "date": "2023-05-10"},
    ]
    mock_scanner = mocker.patch('app.get_fit_file_details', return_value=mock_file_details)
    mocker.patch('app.calculate_aggregate_power_curve', return_value=None) # Simulate calculation failure
    test_fit_dir = str(tmp_path)
    mocker.patch('os.getenv', return_value=test_fit_dir)

    request_data: Dict[str, str] = {"startDate": "2023-05-10", "endDate": "2023-05-10"}
    response = client.post('/api/powercurve', json=request_data)

    assert response.status_code == 500
    assert "error" in response.json
    assert "Failed to calculate" in response.json["error"]
    mock_scanner.assert_called_once_with(test_fit_dir)
