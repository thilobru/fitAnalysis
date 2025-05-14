import pytest
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

# Assuming RecordData and PowerCurveData types are defined in app.services
# and _perform_power_curve_calculation is the function we are testing.
from app.services import _perform_power_curve_calculation, RecordData, PowerCurveData

# Use pytest's approx for comparing floating point numbers
from pytest import approx

# --- Test Data Fixtures --- (Fixtures remain the same as your latest version)

@pytest.fixture
def sample_records_simple() -> List[RecordData]:
    """Provides a simple list of records for basic testing (no significant gaps)."""
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
    """Provides a longer list of records for testing longer windows (no significant gaps)."""
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    data: List[RecordData] = []
    for i in range(600): # 10 minutes of data
        power: int = 100 + (i // 10) # Gradually increasing power
        data.append({'timestamp': start_time + timedelta(seconds=i), 'power': power})
    data[30]['power'] = 300 
    data[31]['power'] = 350
    data[32]['power'] = 320
    return data

@pytest.fixture
def records_with_sub_2s_gaps_not_filled() -> List[RecordData]:
    """
    Data with gaps of 1.5s. The gap-filling logic (>=1.0s outer, >=1.0s inner for fill)
    should NOT insert zeros for these sub-integer-second gaps if they don't cross a full second boundary
    in a way that leaves a whole second empty.
    """
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 200},
        {'timestamp': start_time + timedelta(seconds=1, milliseconds=500), 'power': 200}, 
        {'timestamp': start_time + timedelta(seconds=3), 'power': 200},                   
        {'timestamp': start_time + timedelta(seconds=4, milliseconds=500), 'power': 200},
    ]

@pytest.fixture
def records_user_specific_2s_gaps_filled() -> List[RecordData]:
    """
    Simulates original data like [0:100, 2:100, 4:100].
    Input to _perform_power_curve_calculation (after gap filling with >=1.0s threshold):
    t0: 100, t1: 0 (filled), t2: 100, t3: 0 (filled), t4: 100
    """
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 100.0},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 0.0},
        {'timestamp': start_time + timedelta(seconds=2), 'power': 100.0},
        {'timestamp': start_time + timedelta(seconds=3), 'power': 0.0},
        {'timestamp': start_time + timedelta(seconds=4), 'power': 100.0},
    ]

@pytest.fixture
def records_with_3s_gap_between_segments_filled() -> List[RecordData]:
    """
    Original data: t0=200, t1=200, then t4=200, t5=200. Gap t1 to t4 is 3 seconds.
    Filled: t0:200, t1:200, t2:0, t3:0, t4:200, t5:200
    """
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 200.0},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 200.0},
        {'timestamp': start_time + timedelta(seconds=2), 'power': 0.0}, 
        {'timestamp': start_time + timedelta(seconds=3), 'power': 0.0},  
        {'timestamp': start_time + timedelta(seconds=4), 'power': 200.0},
        {'timestamp': start_time + timedelta(seconds=5), 'power': 200.0},
    ]

@pytest.fixture
def records_with_medium_gap_filled_zeros() -> List[RecordData]:
    """
    Original: t0=200, t1=200, then t6=200, t7=200. Gap t1 to t6 is 5 seconds.
    Filled: t2,t3,t4,t5 with 0s.
    Data: [ (t0,200), (t1,200), (t2,0), (t3,0), (t4,0), (t5,0), (t6,200), (t7,200) ]
    """
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 200.0}, 
        {'timestamp': start_time + timedelta(seconds=1), 'power': 200.0}, 
        {'timestamp': start_time + timedelta(seconds=2), 'power': 0.0},   
        {'timestamp': start_time + timedelta(seconds=3), 'power': 0.0},   
        {'timestamp': start_time + timedelta(seconds=4), 'power': 0.0},   
        {'timestamp': start_time + timedelta(seconds=5), 'power': 0.0},   
        {'timestamp': start_time + timedelta(seconds=6), 'power': 200.0}, 
        {'timestamp': start_time + timedelta(seconds=7), 'power': 200.0}, 
    ]

@pytest.fixture
def records_with_long_gap_filled_zeros() -> List[RecordData]:
    """
    Original: t0=300, t1=300, then t12=300, t13=300. Gap t1 to t12 is 11 seconds.
    Filled: t2 through t11 with 0s.
    Data: [ (t0,300), (t1,300), (t2,0)...(t11,0), (t12,300), (t13,300) ]
    """
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    data = [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 300.0},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 300.0},
    ]
    for i in range(2, 12): 
        data.append({'timestamp': start_time + timedelta(seconds=i), 'power': 0.0})
    data.extend([
        {'timestamp': start_time + timedelta(seconds=12), 'power': 300.0},
        {'timestamp': start_time + timedelta(seconds=13), 'power': 300.0},
    ])
    return data

# --- Test Cases ---

def test_perform_power_curve_basic(sample_records_simple: List[RecordData]):
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(sample_records_simple)
    assert result is not None
    assert result.get(1) == approx(200.0)
    assert result.get(2) == approx(190.0)
    assert result.get(5) == approx(150.0)
    assert 10 not in result # Not enough data for 10s window with min_periods=10

def test_perform_power_curve_longer(sample_records_longer: List[RecordData]):
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(sample_records_longer)
    assert result is not None
    assert result.get(1) == approx(350.0)
    assert result.get(2) == approx(335.0)
    assert result.get(3) == approx(323.333, abs=1e-2) # (300+350+320)/3
    assert result.get(60) is not None and result.get(60) > 100 
    assert result.get(600) is not None

def test_perform_power_curve_empty():
    result: Optional[PowerCurveData] = _perform_power_curve_calculation([])
    assert result == {}

def test_perform_power_curve_invalid_data_types_handled_by_dataframe():
    start_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    invalid_records: List[Dict[str, Any]] = [
        {'timestamp': start_time + timedelta(seconds=0), 'power': 100},
        {'timestamp': start_time + timedelta(seconds=1), 'power': 'invalid_power'},
        {'timestamp': "not_a_date", 'power': 150},
        {'timestamp': start_time + timedelta(seconds=3), 'power': 200},
        {'timestamp': start_time + timedelta(seconds=4), 'power': None},
    ]
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(invalid_records) # type: ignore
    assert result is not None
    # After cleaning by pandas: [{'ts': t0, 'p': 100}, {'ts': t0+3s, 'p': 200}]
    assert result.get(1) == approx(200.0) 
    assert 2 not in result # min_periods=2, not enough points for a 2s window
    assert 3 not in result # min_periods=3
    assert 4 not in result # min_periods=4

def test_perform_power_curve_only_invalid_data():
    invalid_records: List[Dict[str, Any]] = [
        {'timestamp': None, 'power': 'invalid'},
        {'timestamp': "not a date", 'power': None},
    ]
    result: Optional[PowerCurveData] = _perform_power_curve_calculation(invalid_records) # type: ignore
    assert result == {}

# --- UPDATED AND NEW TEST CASES FOR GAP HANDLING (min_periods=duration_sec) ---

def test_power_curve_with_sub_2s_gaps_not_filled(records_with_sub_2s_gaps_not_filled: List[RecordData]):
    """
    Data: t0=200, t1.5=200, t3.0=200, t4.5=200 (4 points)
    The time-based windowing with min_periods=duration_sec is tricky here.
    Pandas rolling by time string 'Xs' considers actual timestamps.
    If points are t0, t1.5, t3, t4.5
    For '1s' window (min_periods=1): max of individual points is 200.
    For '2s' window (min_periods=2):
        - Window ending t1.5 includes t0, t1.5. Avg=200.
        - Window ending t3 includes t1.5, t3. Avg=200.
        - Window ending t4.5 includes t3, t4.5. Avg=200. Max=200.
    For '3s' window (min_periods=3):
        - Window ending t3 includes t0, t1.5, t3. Avg=200. Max=200.
    For '4s' window (min_periods=4):
        - Window ending t4.5 includes t0, t1.5, t3, t4.5. Avg=200. Max=200.
    """
    result = _perform_power_curve_calculation(records_with_sub_2s_gaps_not_filled)
    assert result is not None
    assert result.get(1) == approx(200.0)
    assert result.get(2) == approx(200.0) 
    assert 3 not in result 
    assert 4 not in result 
    assert 5 not in result # min_periods=5, only 4 points

def test_power_curve_user_specific_2s_gaps_filled(records_user_specific_2s_gaps_filled: List[RecordData]):
    """
    Data: t0:100, t1:0, t2:100, t3:0, t4:100 (5 points)
    """
    result = _perform_power_curve_calculation(records_user_specific_2s_gaps_filled)
    assert result is not None
    assert result.get(1) == approx(100.0)
    assert result.get(2) == approx(50.0)   # Max of [100,0], [0,100], [100,0], [0,100]
    assert result.get(3) == approx(66.666, abs=1e-2) # Max of [100,0,100], [0,100,0]
    assert result.get(4) == approx(50.0)   # Max of [100,0,100,0], [0,100,0,100]
    assert result.get(5) == approx(60.0)   # (100+0+100+0+100)/5

def test_power_curve_with_3s_gap_filled(records_with_3s_gap_between_segments_filled: List[RecordData]):
    """
    Data: t0:200, t1:200, t2:0, t3:0, t4:200, t5:200 (6 points)
    """
    result = _perform_power_curve_calculation(records_with_3s_gap_between_segments_filled)
    assert result is not None
    assert result.get(1) == approx(200.0)
    assert result.get(2) == approx(200.0) 
    assert result.get(3) == approx(133.333, abs=1e-2) # Max of [200,200,0] or [0,200,200]
    assert result.get(4) == approx(100.0) # Max of [200,200,0,0] or [0,0,200,200]
    assert result.get(5) == approx(120.0) # Max of [200,200,0,0,200] or [200,0,0,200,200]
    assert result.get(6) == approx(133.333, abs=1e-2) # (800)/6

def test_power_curve_with_medium_gap_filled_zeros(records_with_medium_gap_filled_zeros: List[RecordData]):
    """
    Data: [ (t0,200), (t1,200), (t2,0), (t3,0), (t4,0), (t5,0), (t6,200), (t7,200) ] (8 points)
    """
    result = _perform_power_curve_calculation(records_with_medium_gap_filled_zeros)
    assert result is not None
    assert result.get(1) == approx(200.0)
    assert result.get(2) == approx(200.0)
    assert result.get(3) == approx(133.333, abs=1e-2) # Max of [200,200,0]
    assert result.get(4) == approx(100.0) # Max of [200,200,0,0]
    assert result.get(7) == approx(85.714, abs=1e-2) # Max of [200,200,0,0,0,0,200] -> 600/7
    assert result.get(8) == approx(100.0) # (200*4)/8

def test_power_curve_with_long_gap_filled_zeros(records_with_long_gap_filled_zeros: List[RecordData]):
    """
    Data: [ (t0,300), (t1,300), (t2,0)...(t11,0), (t12,300), (t13,300) ] (14 points)
    """
    result = _perform_power_curve_calculation(records_with_long_gap_filled_zeros)
    assert result is not None
    assert result.get(1) == approx(300.0)
    assert result.get(2) == approx(300.0)
    assert result.get(3) == approx(200.0) # Max of [300,300,0]
    assert result.get(5) == approx(120.0) # Max of [300,300,0,0,0]
    assert result.get(12) == approx(50.0) # Max of [300,300,0...0(10x)] or [0...0(10x),300,300] etc. -> 600/12
    assert 14 not in result
