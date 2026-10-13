"""Check the smoke's 500 metre EPSG:3857 point buffer independently."""
import json
import math
import sys


def validate(result):
    feature = result["outputFeatureLayer"]["value"]
    if feature["type"] == "FeatureCollection":
        if len(feature["features"]) != 1:
            raise ValueError("expected one buffered feature")
        feature = feature["features"][0]
    geometry = feature["geometry"]
    if feature["type"] != "Feature" or geometry["type"] != "Polygon":
        raise ValueError("expected a polygon feature")
    rings = geometry["coordinates"]
    if len(rings) != 1 or len(rings[0]) < 4 or rings[0][0] != rings[0][-1]:
        raise ValueError("expected a closed exterior ring without holes")
    ring = rings[0]
    xs, ys = zip(*[(point[0], point[1]) for point in ring])
    if not all(math.isfinite(value) for value in (*xs, *ys)):
        raise ValueError("non-finite coordinate")
    bounds = [min(xs), min(ys), max(xs), max(ys)]
    if any(not math.isclose(a, b, abs_tol=1e-6) for a, b in zip(bounds, [-500, -500, 500, 500])):
        raise ValueError(f"incorrect buffer bounds: {bounds}")
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))) / 2
    if not math.isclose(area, math.pi * 500**2, rel_tol=0.01):
        raise ValueError(f"incorrect buffer area: {area}")
    return {"bounds": bounds, "area": area, "srid": 3857, "distance": 500}


if __name__ == "__main__":
    with open(sys.argv[1]) as stream:
        print(json.dumps(validate(json.load(stream))))
