# tests/integration/test_services.py
"""Integration tests for service layer functions."""

import pytest
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Tuple, List, Dict, Any, Generator
from flask import Flask
from pytest_mock import MockerFixture
import fitdecode # Import to mock FitDecodeError

# Import app components needed for testing
from app.models import User, FitFile, PowerCurvePoint, db
from app.services import calculate_and_save_single_file_power_curve, _perform_power_curve_calculation

# --- Fixtures ---

# Use the existing app and db fixtures from conftest.py

@pytest.fixture(scope="function")
def test_user(db: Any) -> User:
    """Creates a test user in the database."""
    user = User(username="service_tester")
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture(scope="function")
def pending_fit_file(db: Any, test_user: User, tmp_path: Path, app: Flask) -> FitFile:
    """Creates a FitFile record pointing to a path in tmp_path."""
    fit_dir = tmp_path / "service_fit_files"
    fit_dir.mkdir(exist_ok=True)
    app.config['FIT_DIR'] = str(fit_dir)

    relative_path = os.path.join(str(test_user.id), "test_service_file.fit")
    full_path = fit_dir / relative_path
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    fit_file = FitFile(
        user_id=test_user.id,
        original_filename="test_service_file.fit",
        storage_path=relative_path,
        activity_date=date(2024, 4, 1),
        filesize=1000,
        processing_status='analysis_pending'
    )
    db.session.add(fit_file)
    db.session.commit()
    return fit_file


# --- Mock Data & Helpers ---
SAMPLE_RECORDS = [
    {'timestamp': datetime(2024, 4, 1, 12, 0, 0, tzinfo=timezone.utc), 'power': 100.0},
    {'timestamp': datetime(2024, 4, 1, 12, 0, 1, tzinfo=timezone.utc), 'power': 150.0},
    {'timestamp': datetime(2024, 4, 1, 12, 0, 2, tzinfo=timezone.utc), 'power': 120.0},
    {'timestamp': datetime(2024, 4, 1, 12, 0, 3, tzinfo=timezone.utc), 'power': 200.0},
    {'timestamp': datetime(2024, 4, 1, 12, 0, 4, tzinfo=timezone.utc), 'power': 180.0},
]
EXPECTED_POWER_CURVE = {1: 200.0, 2: 190.0, 3: 166.7, 4: 162.5, 5: 150.0}


# --- Test Cases for calculate_and_save_single_file_power_curve ---

def test_calc_single_success(
    app: Flask, db: Any, test_user: User, pending_fit_file: FitFile, mocker: MockerFixture
):
    """Test successful calculation and saving for a single file."""
    file_id = pending_fit_file.id
    full_path = pending_fit_file.get_full_path()
    with open(full_path, "wb") as f: f.write(b"dummy_content")

    mock_fit_frame = mocker.Mock()
    mock_fit_frame.frame_type = fitdecode.FIT_FRAME_DATA
    mock_fit_frame.name = 'record'
    # Use a shared counter for the side effect
    call_counter = mocker.Mock()
    call_counter.count = -1
    def get_value_side_effect(key, fallback=None):
        if key == 'timestamp':
            call_counter.count += 1
            return SAMPLE_RECORDS[call_counter.count % len(SAMPLE_RECORDS)]['timestamp']
        elif key == 'power':
             return SAMPLE_RECORDS[call_counter.count % len(SAMPLE_RECORDS)]['power']
        return fallback
    mock_fit_frame.get_value = mocker.Mock(side_effect=get_value_side_effect)

    mock_fit_reader_instance = mocker.MagicMock()
    # Simulate yielding the mock frame N times
    mock_fit_reader_instance.__enter__.return_value = iter([mock_fit_frame] * len(SAMPLE_RECORDS))
    mock_fit_reader = mocker.patch('fitdecode.FitReader', return_value=mock_fit_reader_instance)

    mocker.patch('app.services._perform_power_curve_calculation', return_value=EXPECTED_POWER_CURVE)

    with app.app_context():
        success = calculate_and_save_single_file_power_curve(file_id)

    assert success is True
    mock_fit_reader.assert_called_once_with(full_path)
    db.session.refresh(pending_fit_file)
    assert pending_fit_file.processing_status == 'processed'
    points = PowerCurvePoint.query.filter_by(fit_file_id=file_id).order_by(PowerCurvePoint.duration_seconds).all()
    assert len(points) == len(EXPECTED_POWER_CURVE)
    # (Optional: add detailed point comparison as before)


def test_calc_single_file_not_found(
    app: Flask, db: Any, test_user: User, pending_fit_file: FitFile, mocker: MockerFixture
):
    """Test handling when the FIT file is missing from the filesystem."""
    file_id = pending_fit_file.id
    with app.app_context():
        success = calculate_and_save_single_file_power_curve(file_id)
    assert success is False
    db.session.refresh(pending_fit_file)
    assert pending_fit_file.processing_status == 'analysis_failed'
    assert PowerCurvePoint.query.filter_by(fit_file_id=file_id).count() == 0


def test_calc_single_fitdecode_error(
    app: Flask, db: Any, test_user: User, pending_fit_file: FitFile, mocker: MockerFixture
):
    """Test handling when fitdecode raises an error during file reading."""
    file_id = pending_fit_file.id
    full_path = pending_fit_file.get_full_path()
    with open(full_path, "wb") as f: f.write(b"invalid fit data")
    mock_fit_reader = mocker.patch('fitdecode.FitReader')
    mock_fit_reader.side_effect = fitdecode.FitError("Simulated decode error")

    with app.app_context():
        success = calculate_and_save_single_file_power_curve(file_id)

    assert success is False
    mock_fit_reader.assert_called_once_with(full_path)
    db.session.refresh(pending_fit_file)
    assert pending_fit_file.processing_status == 'analysis_failed'
    assert PowerCurvePoint.query.filter_by(fit_file_id=file_id).count() == 0


def test_calc_single_no_records(
    app: Flask, db: Any, test_user: User, pending_fit_file: FitFile, mocker: MockerFixture
):
    """Test handling when a valid FIT file has no power/timestamp records."""
    file_id = pending_fit_file.id
    full_path = pending_fit_file.get_full_path()
    with open(full_path, "wb") as f: f.write(b"valid_but_no_records")
    mock_fit_reader_instance = mocker.MagicMock()
    mock_fit_reader_instance.__enter__.return_value = iter([]) # Return empty iterator
    mock_fit_reader = mocker.patch('fitdecode.FitReader', return_value=mock_fit_reader_instance)

    with app.app_context():
        success = calculate_and_save_single_file_power_curve(file_id)

    assert success is True
    mock_fit_reader.assert_called_once_with(full_path)
    db.session.refresh(pending_fit_file)
    assert pending_fit_file.processing_status == 'processed'
    assert PowerCurvePoint.query.filter_by(fit_file_id=file_id).count() == 0


# --- FIXED TEST ---
def test_calc_single_calculation_error(
    app: Flask, db: Any, test_user: User, pending_fit_file: FitFile, mocker: MockerFixture
):
    """Test handling when _perform_power_curve_calculation returns None."""
    file_id = pending_fit_file.id
    full_path = pending_fit_file.get_full_path()
    with open(full_path, "wb") as f: f.write(b"dummy_content")

    # --- FIXED MOCK ---
    # Mock FitReader to return *some* valid records data so calculation is attempted
    mock_fit_frame = mocker.Mock()
    mock_fit_frame.frame_type = fitdecode.FIT_FRAME_DATA
    mock_fit_frame.name = 'record'
    # Use a shared counter for the side effect
    call_counter = mocker.Mock()
    call_counter.count = -1
    def get_value_side_effect(key, fallback=None):
        if key == 'timestamp':
            call_counter.count += 1
            # Only need one record for this test path
            return SAMPLE_RECORDS[0]['timestamp'] if call_counter.count == 0 else None
        elif key == 'power':
             return SAMPLE_RECORDS[0]['power'] if call_counter.count == 0 else None
        return fallback
    mock_fit_frame.get_value = mocker.Mock(side_effect=get_value_side_effect)

    mock_fit_reader_instance = mocker.MagicMock()
    # Simulate yielding the mock frame ONCE
    mock_fit_reader_instance.__enter__.return_value = iter([mock_fit_frame])
    mocker.patch('fitdecode.FitReader', return_value=mock_fit_reader_instance)
    # --- END FIXED MOCK ---

    # Mock the calculation function to return None (simulating internal error)
    mock_calculator = mocker.patch('app.services._perform_power_curve_calculation', return_value=None)

    # --- Action ---
    with app.app_context():
        success = calculate_and_save_single_file_power_curve(file_id)

    # --- Assertions ---
    assert success is False # Now expect False because calculation error path is hit
    mock_calculator.assert_called_once() # Ensure calculation was attempted

    # Verify DB state
    db.session.refresh(pending_fit_file)
    assert pending_fit_file.processing_status == 'analysis_failed'
    assert PowerCurvePoint.query.filter_by(fit_file_id=file_id).count() == 0

