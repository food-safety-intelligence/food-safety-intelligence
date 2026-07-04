"""
Static bounding-box lookup for Los Angeles neighborhoods.

Keys are title-cased neighborhood names as commonly typed.
Values are (south, west, north, east) lat/lon bounding boxes.

Source: derived from LA Times Mapping L.A. neighborhood boundaries
(public domain reference). Boxes are approximate.
"""

BBOX: dict[str, dict[str, float]] = {
    # --- Central / Downtown ---
    "Downtown LA": {"south": 34.0330, "west": -118.2620, "north": 34.0620, "east": -118.2320},
    "Chinatown": {"south": 34.0600, "west": -118.2420, "north": 34.0720, "east": -118.2300},
    "Little Tokyo": {"south": 34.0450, "west": -118.2440, "north": 34.0530, "east": -118.2350},
    "Arts District": {"south": 34.0330, "west": -118.2360, "north": 34.0470, "east": -118.2270},
    "Koreatown": {"south": 34.0540, "west": -118.3110, "north": 34.0700, "east": -118.2900},
    "Mid-Wilshire": {"south": 34.0560, "west": -118.3560, "north": 34.0700, "east": -118.3260},
    "Boyle Heights": {"south": 34.0300, "west": -118.2150, "north": 34.0500, "east": -118.1900},
    # --- East / Northeast ---
    "Echo Park": {"south": 34.0680, "west": -118.2680, "north": 34.0840, "east": -118.2470},
    "Silver Lake": {"south": 34.0800, "west": -118.2800, "north": 34.1000, "east": -118.2560},
    "Los Feliz": {"south": 34.0960, "west": -118.2980, "north": 34.1200, "east": -118.2760},
    "Atwater Village": {"south": 34.1080, "west": -118.2680, "north": 34.1260, "east": -118.2500},
    "Highland Park": {"south": 34.1050, "west": -118.2150, "north": 34.1250, "east": -118.1850},
    "Eagle Rock": {"south": 34.1300, "west": -118.2200, "north": 34.1500, "east": -118.1930},
    # --- Hollywood ---
    "Hollywood": {"south": 34.0940, "west": -118.3450, "north": 34.1100, "east": -118.3150},
    "West Hollywood": {"south": 34.0830, "west": -118.3900, "north": 34.0960, "east": -118.3600},
    "Studio City": {"south": 34.1350, "west": -118.4020, "north": 34.1520, "east": -118.3700},
    "North Hollywood": {"south": 34.1650, "west": -118.3900, "north": 34.1900, "east": -118.3600},
    "Sherman Oaks": {"south": 34.1450, "west": -118.4680, "north": 34.1650, "east": -118.4350},
    # --- Westside ---
    "Westwood": {"south": 34.0560, "west": -118.4530, "north": 34.0720, "east": -118.4300},
    "Sawtelle": {"south": 34.0300, "west": -118.4500, "north": 34.0480, "east": -118.4300},
    "Culver City": {"south": 34.0000, "west": -118.4160, "north": 34.0250, "east": -118.3800},
    "Mar Vista": {"south": 33.9930, "west": -118.4400, "north": 34.0100, "east": -118.4150},
    "Santa Monica": {"south": 34.0050, "west": -118.5000, "north": 34.0350, "east": -118.4700},
    "Venice": {"south": 33.9820, "west": -118.4780, "north": 33.9980, "east": -118.4550},
    # --- South / Coast ---
    "El Segundo": {"south": 33.9100, "west": -118.4200, "north": 33.9300, "east": -118.3900},
    "Torrance": {"south": 33.8200, "west": -118.3600, "north": 33.8600, "east": -118.3100},
    "Long Beach": {"south": 33.7600, "west": -118.2100, "north": 33.8000, "east": -118.1600},
    # --- San Gabriel Valley ---
    "Pasadena": {"south": 34.1350, "west": -118.1600, "north": 34.1650, "east": -118.1200},
    "Glendale": {"south": 34.1350, "west": -118.2700, "north": 34.1650, "east": -118.2300},
}

# Centroids derived from bbox midpoints — used for distance sorting.
CENTROIDS: dict[str, tuple[float, float]] = {
    name: (
        (bb["south"] + bb["north"]) / 2,
        (bb["west"] + bb["east"]) / 2,
    )
    for name, bb in BBOX.items()
}

# Whole-city fallback bbox (covers the dense LA County core)
LA_BBOX = {"south": 33.700, "west": -118.670, "north": 34.340, "east": -118.150}
LA_CENTROID = (34.0522, -118.2437)
