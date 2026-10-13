"""Independent conversion oracle for the native worker Kubernetes smoke."""
import json
import sys


def validate(outputs):
    if len(outputs) != 1:
        raise ValueError("expected one conversion output")
    member = next(iter(outputs.values()))
    if member["mediaType"] != "application/geo+json":
        raise ValueError("expected GeoJSON output")
    collection = member["value"]
    features = collection["features"]
    if collection["type"] != "FeatureCollection" or len(features) != 2:
        raise ValueError("expected two converted features")
    by_name = {feature["properties"]["name"]: feature for feature in features}
    for name, value, xyz in [("alpha", "17", [12.25, -4.5, 7.75]), ("beta", "29", [-23.5, 8.25, -2.5])]:
        feature = by_name[name]
        if str(feature["properties"]["value"]) != value or feature["geometry"] != {"type": "Point", "coordinates": xyz}:
            raise ValueError(f"conversion changed coordinates or attributes for {name}")
    return {"process": "gdal.ogr2ogr", "featureCount": 2, "coordinatesAndAttributesVerified": True}


if __name__ == "__main__":
    with open(sys.argv[1]) as stream:
        print(json.dumps(validate(json.load(stream))))
