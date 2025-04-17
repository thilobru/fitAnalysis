import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

# ** CHANGE: Import from app.services now **
from app.services import _perform_power_curve_calculation, RecordData, PowerCurveData

# Use pytest's approx for comparing floating point numbers
from pytest import approx

# --- Test Data Fixtures ---

@pytest.fixture
def sample_records_simple() -> List[RecordData]:
    """Provides a simple list of records for basic testing."""
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 100},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 150},
        {'timestamp': start_time + timedelta(seconds=2), 'power': 120},
        {'timestamp': start_time + timedelta(seconds=3), 'power': 200},
        {'timestamp': start_time + timedelta(seconds=4), 'power': 180},
    ]

@pytest.fixture
def sample_records_longer() -> List[RecordData]:
    """Provides a longer list of records for testing longer windows."""
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    data: List[RecordData] = []
    for i in range(600):
        power: int = 100 + (i // 10)
        data.append({'timestamp': start_time + timedelta(seconds=i), 'power': power})
    data[30]['power'] = 300
    data[31]['power'] = 350
    data[32]['power'] = 320
    return data

# --- Test Cases ---

def test_perform_power_curve_basic(sample_records_simple: List[RecordData]):
    """Test calculation with a small, simple dataset."""
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(sample_records_simple)

    assert result is not None
    assert isinstance(result, dict)
    assert 1 in result
    assert result[1] == approx(200.0)
    assert 2 in result
    assert result[2] == approx(190.0)
    assert 5 in result
    assert result[5] == approx(150.0)
    assert 10 in result
    assert result[10] == approx(result[5])

def test_perform_power_curve_longer(sample_records_longer: List[RecordData]):
    """Test calculation with a longer dataset."""
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(sample_records_longer)

    assert result is not None
    assert isinstance(result, dict)
    assert 1 in result
    assert result[1] == approx(350.0)
    assert 2 in result
    assert result[2] == approx(335.0)
    assert 3 in result
    assert result[3] == approx(323.3, abs=0.1)
    assert 60 in result
    assert result[60] > 100
    assert 600 in result

def test_perform_power_curve_empty():
    """Test with empty input data."""
    result: Optional[PowerCurveData] = _perform_power_curve_calculation([])
    assert result == {}

def test_perform_power_curve_invalid_data():
    """Test with data containing non-numeric power or invalid timestamps."""
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Use Any for mixed types before cleaning
    invalid_records: List[Dict[str, Any]] = [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 100},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 'invalid'},
        {'timestamp': None, 'power': 150},
        {'timestamp': start_time + timedelta(seconds=3), 'power': 200},
    ]
    # Cast to List[RecordData] is okay here as the function handles invalid types internally
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(invalid_records) # type: ignore

    assert result is not None
    assert isinstance(result, dict)
    assert 1 in result
    assert result[1] == approx(200.0)
    assert 2 in result
    assert result[2] == approx(200.0)
    assert 4 in result
    assert result[4] == approx(150.0)

def test_perform_power_curve_only_invalid_data():
    """Test with data containing only non-numeric power or invalid timestamps."""
    invalid_records: List[Dict[str, Any]] = [
        {'timestamp': None, 'power': 'invalid'},
        {'timestamp': "not a date", 'power': None},
    ]
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(invalid_records) # type: ignore
    assert result == {}
