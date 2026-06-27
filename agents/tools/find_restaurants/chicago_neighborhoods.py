"""
Static bounding-box lookup for Chicago neighborhoods.

Keys are title-cased neighborhood names as commonly typed.
Values are (south, west, north, east) lat/lon bounding boxes.

Source: derived from Chicago Community Areas shapefile
(City of Chicago Data Portal, public domain).
"""

BBOX: dict[str, dict[str, float]] = {
    # --- North Side ---
    "Rogers Park": {"south": 41.9900, "west": -87.6900, "north": 42.0228, "east": -87.6500},
    "West Ridge": {"south": 41.9900, "west": -87.7200, "north": 42.0228, "east": -87.6900},
    "Uptown": {"south": 41.9580, "west": -87.6700, "north": 41.9900, "east": -87.6400},
    "Lincoln Square": {"south": 41.9580, "west": -87.7050, "north": 41.9900, "east": -87.6700},
    "Edgewater": {"south": 41.9780, "west": -87.6650, "north": 41.9980, "east": -87.6480},
    "Andersonville": {"south": 41.9750, "west": -87.6700, "north": 41.9900, "east": -87.6550},
    # --- Northwest ---
    "Albany Park": {"south": 41.9580, "west": -87.7350, "north": 41.9900, "east": -87.7050},
    "Logan Square": {"south": 41.9160, "west": -87.7200, "north": 41.9580, "east": -87.6950},
    "Avondale": {"south": 41.9370, "west": -87.7200, "north": 41.9580, "east": -87.6980},
    "Irving Park": {"south": 41.9580, "west": -87.7500, "north": 41.9900, "east": -87.7200},
    "Portage Park": {"south": 41.9580, "west": -87.7750, "north": 41.9900, "east": -87.7500},
    # --- Near North ---
    "Lincoln Park": {"south": 41.9100, "west": -87.6650, "north": 41.9580, "east": -87.6320},
    "Lakeview": {"south": 41.9370, "west": -87.6700, "north": 41.9580, "east": -87.6370},
    "Lakeview East": {"south": 41.9370, "west": -87.6480, "north": 41.9580, "east": -87.6320},
    "Wrigleyville": {"south": 41.9440, "west": -87.6560, "north": 41.9580, "east": -87.6410},
    "Wicker Park": {"south": 41.8950, "west": -87.6850, "north": 41.9160, "east": -87.6600},
    "Bucktown": {"south": 41.9160, "west": -87.6850, "north": 41.9370, "east": -87.6620},
    "Old Town": {"south": 41.9100, "west": -87.6480, "north": 41.9370, "east": -87.6300},
    "River North": {"south": 41.8880, "west": -87.6380, "north": 41.9100, "east": -87.6200},
    "Streeterville": {"south": 41.8880, "west": -87.6200, "north": 41.9100, "east": -87.6060},
    "Gold Coast": {"south": 41.9000, "west": -87.6400, "north": 41.9160, "east": -87.6230},
    "Magnificent Mile": {"south": 41.8900, "west": -87.6300, "north": 41.9050, "east": -87.6200},
    # --- Loop / Near South ---
    "Loop": {"south": 41.8740, "west": -87.6420, "north": 41.8880, "east": -87.6200},
    "West Loop": {"south": 41.8740, "west": -87.6650, "north": 41.8880, "east": -87.6420},
    "South Loop": {"south": 41.8580, "west": -87.6350, "north": 41.8740, "east": -87.6200},
    "Printer's Row": {"south": 41.8680, "west": -87.6330, "north": 41.8780, "east": -87.6250},
    # --- West Side ---
    "Humboldt Park": {"south": 41.8960, "west": -87.7350, "north": 41.9160, "east": -87.7050},
    "East Garfield Park": {"south": 41.8740, "west": -87.7200, "north": 41.8960, "east": -87.6980},
    "West Town": {"south": 41.8880, "west": -87.6870, "north": 41.9100, "east": -87.6620},
    "Ukrainian Village": {"south": 41.8850, "west": -87.6800, "north": 41.9000, "east": -87.6620},
    "Noble Square": {"south": 41.8940, "west": -87.6700, "north": 41.9050, "east": -87.6580},
    "Pilsen": {"south": 41.8500, "west": -87.6700, "north": 41.8680, "east": -87.6450},
    "Little Village": {"south": 41.8370, "west": -87.7350, "north": 41.8580, "east": -87.7050},
    # --- South Side ---
    "Hyde Park": {"south": 41.7770, "west": -87.6100, "north": 41.8050, "east": -87.5820},
    "South Shore": {"south": 41.7500, "west": -87.6100, "north": 41.7770, "east": -87.5700},
    "Bridgeport": {"south": 41.8320, "west": -87.6650, "north": 41.8580, "east": -87.6380},
    "Chinatown": {"south": 41.8480, "west": -87.6350, "north": 41.8600, "east": -87.6250},
    "Bronzeville": {"south": 41.8220, "west": -87.6250, "north": 41.8550, "east": -87.6050},
    "Greater Grand Crossing": {
        "south": 41.7440,
        "west": -87.6250,
        "north": 41.7770,
        "east": -87.5950,
    },
    "Chatham": {"south": 41.7280, "west": -87.6450, "north": 41.7580, "east": -87.6050},
    "Roseland": {"south": 41.6900, "west": -87.6400, "north": 41.7280, "east": -87.5900},
    "Pullman": {"south": 41.6900, "west": -87.6180, "north": 41.7100, "east": -87.5900},
    "Mount Greenwood": {"south": 41.6900, "west": -87.7250, "north": 41.7280, "east": -87.6850},
    # --- Far North ---
    "Sauganash": {"south": 41.9900, "west": -87.7500, "north": 42.0100, "east": -87.7200},
    "Jefferson Park": {"south": 41.9580, "west": -87.7850, "north": 41.9900, "east": -87.7500},
    "Norwood Park": {"south": 41.9900, "west": -87.8100, "north": 42.0228, "east": -87.7800},
}

# Centroids derived from bbox midpoints — used for distance sorting.
CENTROIDS: dict[str, tuple[float, float]] = {
    name: (
        (bb["south"] + bb["north"]) / 2,
        (bb["west"] + bb["east"]) / 2,
    )
    for name, bb in BBOX.items()
}

# Whole-city fallback bbox
CHICAGO_BBOX = {"south": 41.644, "west": -87.940, "north": 42.023, "east": -87.524}
CHICAGO_CENTROID = (41.8781, -87.6298)
