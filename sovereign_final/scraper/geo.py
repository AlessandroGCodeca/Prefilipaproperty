"""
scraper/geo.py — a listing's own map pin, read off the portal's data.

The LV debt filter resolves a pin to the building parcel under it
(kataster_scraper.parcel_at), so a pin is only taken from the listing's own
structured data — schema.org JSON-LD `geo`, an API item's location fields,
OpenGraph place meta — never geocoded from an address, which lands on a street
or district centroid. Coordinates outside Slovakia are dropped: a 0,0 or a
swapped lat/lng would otherwise resolve to somebody else's parcel.

Which of these each portal actually ships could not be checked live while this
was written (the portals were unreachable); every reader returns None when its
fields are absent, so a portal without pins simply leaves listings UNVERIFIED.
"""

import re

# Slovakia's bounding box, with a little slack at the borders.
_LAT_RANGE = (47.70, 49.65)
_LNG_RANGE = (16.80, 22.60)

_PAIRS = (("latitude", "longitude"), ("lat", "lng"), ("lat", "lon"),
          ("gpsLatitude", "gpsLongitude"), ("gpsLat", "gpsLng"))
_NESTED = ("geo", "gps", "location", "coordinates", "position", "point",
           "address", "map", "mapPosition")


def _num(v):
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f


def as_pin(lat, lng):
    """(lat, lng) as floats when they're a point in Slovakia, else None."""
    lat, lng = _num(lat), _num(lng)
    if lat is None or lng is None:
        return None
    if _LAT_RANGE[0] <= lat <= _LAT_RANGE[1] and _LNG_RANGE[0] <= lng <= _LNG_RANGE[1]:
        return lat, lng
    return None


def pin_from_item(obj, depth: int = 0):
    """A pin from a JSON object: lat/lng-style key pairs on the object itself
    or on a nested location-ish object (`geo`, `gps`, `location`, …)."""
    if not isinstance(obj, dict) or depth > 2:
        return None
    for lat_key, lng_key in _PAIRS:
        if lat_key in obj and lng_key in obj:
            pin = as_pin(obj[lat_key], obj[lng_key])
            if pin:
                return pin
    for key in _NESTED:
        pin = pin_from_item(obj.get(key), depth + 1)
        if pin:
            return pin
    return None


def pin_from_ld(ld):
    """A pin from a schema.org JSON-LD blob: its `geo` (GeoCoordinates), the
    blob itself when it IS GeoCoordinates, or a nested Place."""
    if not isinstance(ld, dict):
        return None
    return pin_from_item(ld)


_OG_LAT = re.compile(
    r'<meta[^>]+(?:property|name)="(?:place:location:latitude|og:latitude)"'
    r'[^>]+content="([^"]+)"', re.I)
_OG_LNG = re.compile(
    r'<meta[^>]+(?:property|name)="(?:place:location:longitude|og:longitude)"'
    r'[^>]+content="([^"]+)"', re.I)


def pin_from_meta(html: str):
    """A pin from OpenGraph place meta tags."""
    lat, lng = _OG_LAT.search(html or ""), _OG_LNG.search(html or "")
    if lat and lng:
        return as_pin(lat.group(1), lng.group(1))
    return None
