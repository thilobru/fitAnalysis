import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone

# Import the internal function we want to test from your Flask app file
# Assuming your Flask app file is named app.py and is in the project root
# Adjust the import path if your structure is different
from app import _perform_power_curve_calculation

# Use pytest's approx for comparing floating point numbers
from pytest import approx

# --- Test Data Fixtures (Optional but good practice) ---

@pytest.fixture
def sample_records_simple():
    """Provides a simple list of records for basic testing."""
    # Timestamps are 1 second apart
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 100},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 150},
        {'timestamp': start_time + timedelta(seconds=2), 'power': 120},
        {'timestamp': start_time + timedelta(seconds=3), 'power': 200},
        {'timestamp': start_time + timedelta(seconds=4), 'power': 180},
    ]

@pytest.fixture
def sample_records_longer():
    """Provides a longer list of records for testing longer windows."""
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    data = []
    # Simulate 10 minutes (600 seconds) of data
    for i in range(600):
        # Simple pattern: power increases slightly
        power = 100 + (i // 10)
        data.append({'timestamp': start_time + timedelta(seconds=i), 'power': power})
    # Add a short burst
    data[30]['power'] = 300
    data[31]['power'] = 350
    data[32]['power'] = 320
    return data

# --- Test Cases ---

def test_perform_power_curve_basic(sample_records_simple):
    """Test calculation with a small, simple dataset."""
    result = _perform_power_curve_calculation(sample_records_simple)

    assert result is not None # Should return a dict, not None
    assert isinstance(result, dict)

    # Check some expected values (adjust based on exact rolling window logic)
    # Note: pandas rolling(window).mean() looks back from the current point.
    # Max 1s power is the max individual power reading
    assert 1 in result
    assert result[1] == approx(200.0)

    # Max 2s power: windows are [100, 150](avg 125), [150, 120](avg 135), [120, 200](avg 160), [200, 180](avg 190)
    assert 2 in result
    assert result[2] == approx(190.0)

    # Max 5s power: window is [100, 150, 120, 200, 180] (avg 150)
    assert 5 in result
    assert result[5] == approx(150.0)

    # Check a duration longer than the data - should not be in the result keys
    # as calculation might yield NaN which we filter out
    assert 10 not in result # Or check if result[10] is None if you handle it differently

def test_perform_power_curve_longer(sample_records_longer):
    """Test calculation with a longer dataset."""
    result = _perform_power_curve_calculation(sample_records_longer)

    assert result is not None
    assert isinstance(result, dict)

    # Check the burst power for short durations
    assert 1 in result
    assert result[1] == approx(350.0) # Max single power reading during burst
    assert 2 in result
    assert result[2] == approx(335.0) # Avg of [300, 350] or [350, 320]? Check pandas logic. Window ending at 31s is [300, 350] avg 325. Window ending at 32s is [350, 320] avg 335. Max is 335.
    assert 3 in result
    assert result[3] == approx(323.3) # Avg of [300, 350, 320]

    # Check a longer duration - should be close to the average power over that period
    # Power ranges from 100 to 100 + (599//10) = 159, ignoring burst
    assert 60 in result # 1 minute
    # The max 60s average will likely include the burst period
    assert result[60] > 100 # Should be higher than baseline due to burst

    assert 600 in result # 10 minutes (full duration)
    # The max 10min avg is just the average of the whole dataset
    # Calculate expected average for comparison if needed
    # total_power = sum(r['power'] for r in sample_records_longer)
    # expected_avg_600 = total_power / 600
    # assert result[600] == approx(expected_avg_600, abs=0.1) # Allow small tolerance

def test_perform_power_curve_empty():
    """Test with empty input data."""
    result = _perform_power_curve_calculation([])
    # Expecting an empty dictionary based on refactored function
    assert result == {}

def test_perform_power_curve_invalid_data():
    """Test with data containing non-numeric power or invalid timestamps."""
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    invalid_records = [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 100},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 'invalid'}, # Invalid power
        {'timestamp': None, 'power': 150},                            # Invalid timestamp
        {'timestamp': start_time + timedelta(seconds=3), 'power': 200},
    ]
    result = _perform_power_curve_calculation(invalid_records)

    assert result is not None
    assert isinstance(result, dict)

    # Should calculate based only on the valid records [100, 200]
    assert 1 in result
    assert result[1] == approx(200.0) # Max of valid points
    assert 2 not in result # Not enough consecutive valid points for 2s window in this specific case
    assert 5 not in result

def test_perform_power_curve_only_invalid_data():
    """Test with data containing only non-numeric power or invalid timestamps."""
    invalid_records = [
        {'timestamp': None, 'power': 'invalid'},
        {'timestamp': "not a date", 'power': None},
    ]
    result = _perform_power_curve_calculation(invalid_records)
    # Expecting an empty dictionary as dropna will remove all rows
    assert result == {}