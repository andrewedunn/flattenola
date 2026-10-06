"""Checks that do not need the downloaded street graph."""
from nola_flat_routes.config import DEMO_TRIPS, SF_BBOX
from nola_flat_routes.webgraph import encode_polyline


def test_demo_trips_sit_inside_orleans_parish():
    lon_min, lon_max, lat_min, lat_max = SF_BBOX
    assert len(DEMO_TRIPS) >= 2
    labels = [t["label"] for t in DEMO_TRIPS]
    assert any("French Quarter" in s and "Uptown" in s for s in labels)
    assert any("Mid-City" in s and "Bywater" in s for s in labels)
    for trip in DEMO_TRIPS:
        for which in ("from", "to"):
            lon, lat = trip[which]
            assert lon_min < lon < lon_max
            assert lat_min < lat < lat_max


def test_polyline_roundtrip_is_stable():
    coords = [(-90.06295, 29.95747), (-90.07, 29.95), (-90.12629, 29.93051)]
    encoded = encode_polyline(coords)
    # Google's algorithm: decode by the inverse of the encoder.
    factor = 1e5
    lat = lon = 0
    i = 0
    out = []
    while i < len(encoded):
        for coord in range(2):
            shift = result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if coord == 0:
                lat += delta
            else:
                lon += delta
        out.append((lon / factor, lat / factor))
    for (lon, lat), (elon, elat) in zip(coords, out):
        assert abs(lon - elon) < 1e-5
        assert abs(lat - elat) < 1e-5
