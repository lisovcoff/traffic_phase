from scripts.audit_ew_events_2b1 import support, HashReader
import io
import hashlib


def test_support_reports_raw_units_without_stop_or_signal_classification():
    ds = [{"millis":t,"centroid_x":x,"centroid_y":0,"speed":s} for t,x,s in
          [(0,0,10),(1000,1,12),(2000,4,20)]]
    result = support(ds,1000)
    assert result["observation_interval_ms"] == [0,1000]
    assert result["before_count"] == 1 and result["after_count"] == 2
    assert result["after_image_motion"]["median"] == 2
    assert result["before_raw_speed"]["median"] == 10
    assert "stop" not in result and "signal_state" not in result


def test_missing_support_stays_missing_and_gap_is_observed():
    ds = [{"millis":0,"speed":None},{"millis":5000,"speed":0}]
    result = support(ds,0)
    assert result["observation_interval_ms"] is None
    assert result["before_raw_speed"]["n"] == 0
    assert result["before_image_motion"]["median"] is None


def test_hashing_reader_hashes_same_bytes_in_single_pass():
    reader = HashReader(io.BytesIO(b"[{},{}]"))
    parts = [reader.read(3),reader.read(3),reader.read(3),reader.read(3)]
    assert reader.hash.hexdigest() == hashlib.sha256(b"".join(parts)).hexdigest()
