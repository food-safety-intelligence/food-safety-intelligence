"""
Static bounding-box lookup for New York City neighborhoods.

Keys are title-cased neighborhood names as commonly typed.
Values are (south, west, north, east) lat/lon bounding boxes.

Source: derived from NYC Neighborhood Tabulation Areas
(NYC Department of City Planning, public domain). Boxes are approximate.
"""

BBOX: dict[str, dict[str, float]] = {
    # --- Manhattan ---
    "Financial District": {"south": 40.7020, "west": -74.0180, "north": 40.7130, "east": -74.0030},
    "Tribeca": {"south": 40.7130, "west": -74.0130, "north": 40.7230, "east": -74.0000},
    "SoHo": {"south": 40.7200, "west": -74.0060, "north": 40.7280, "east": -73.9960},
    "Chinatown": {"south": 40.7130, "west": -73.9990, "north": 40.7210, "east": -73.9910},
    "Lower East Side": {"south": 40.7130, "west": -73.9900, "north": 40.7250, "east": -73.9760},
    "Greenwich Village": {"south": 40.7280, "west": -74.0040, "north": 40.7370, "east": -73.9930},
    "East Village": {"south": 40.7220, "west": -73.9910, "north": 40.7330, "east": -73.9760},
    "West Village": {"south": 40.7300, "west": -74.0110, "north": 40.7400, "east": -74.0000},
    "Chelsea": {"south": 40.7400, "west": -74.0090, "north": 40.7530, "east": -73.9930},
    "Midtown": {"south": 40.7500, "west": -73.9900, "north": 40.7620, "east": -73.9730},
    "Hell's Kitchen": {"south": 40.7560, "west": -74.0020, "north": 40.7700, "east": -73.9880},
    "Upper East Side": {"south": 40.7620, "west": -73.9660, "north": 40.7850, "east": -73.9490},
    "Upper West Side": {"south": 40.7720, "west": -73.9880, "north": 40.7990, "east": -73.9680},
    "Harlem": {"south": 40.8020, "west": -73.9560, "north": 40.8180, "east": -73.9340},
    # --- Brooklyn ---
    "Williamsburg": {"south": 40.7040, "west": -73.9660, "north": 40.7230, "east": -73.9450},
    "Bushwick": {"south": 40.6900, "west": -73.9280, "north": 40.7060, "east": -73.9020},
    "Bedford-Stuyvesant": {"south": 40.6790, "west": -73.9500, "north": 40.6980, "east": -73.9210},
    "DUMBO": {"south": 40.7000, "west": -73.9920, "north": 40.7060, "east": -73.9840},
    "Park Slope": {"south": 40.6640, "west": -73.9880, "north": 40.6800, "east": -73.9700},
    "Crown Heights": {"south": 40.6650, "west": -73.9500, "north": 40.6790, "east": -73.9260},
    "Sunset Park": {"south": 40.6400, "west": -74.0180, "north": 40.6600, "east": -73.9930},
    "Bay Ridge": {"south": 40.6180, "west": -74.0400, "north": 40.6400, "east": -74.0200},
    "Flatbush": {"south": 40.6350, "west": -73.9660, "north": 40.6560, "east": -73.9500},
    # --- Queens ---
    "Astoria": {"south": 40.7580, "west": -73.9330, "north": 40.7760, "east": -73.9080},
    "Long Island City": {"south": 40.7370, "west": -73.9530, "north": 40.7550, "east": -73.9330},
    "Flushing": {"south": 40.7500, "west": -73.8380, "north": 40.7710, "east": -73.8130},
    "Jackson Heights": {"south": 40.7460, "west": -73.8940, "north": 40.7590, "east": -73.8730},
    "Elmhurst": {"south": 40.7330, "west": -73.8860, "north": 40.7470, "east": -73.8650},
    "Forest Hills": {"south": 40.7150, "west": -73.8530, "north": 40.7300, "east": -73.8330},
    "Jamaica": {"south": 40.6900, "west": -73.8080, "north": 40.7080, "east": -73.7830},
}

# Centroids derived from bbox midpoints — used for distance sorting.
CENTROIDS: dict[str, tuple[float, float]] = {
    name: (
        (bb["south"] + bb["north"]) / 2,
        (bb["west"] + bb["east"]) / 2,
    )
    for name, bb in BBOX.items()
}

# Whole-city fallback bbox (covers the five boroughs)
NYC_BBOX = {"south": 40.4770, "west": -74.2590, "north": 40.9180, "east": -73.7000}
NYC_CENTROID = (40.7128, -74.0060)
