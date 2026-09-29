import json
import math
import os
from urllib.parse import urlencode

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .cache import TTLCache


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IRSA_SIA_URL = os.getenv(
    "SPHEREX_SIA_URL",
    "https://irsa.ipac.caltech.edu/SIA"
)
HIPS_BASE_URL = os.getenv(
    "SPHEREX_HIPS_BASE_URL",
    "https://alasky.cds.unistra.fr/SPHEREx"
)

HIPS2FITS_URL = os.getenv(
    "SPHEREX_HIPS2FITS_URL",
    "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
)



DEFAULT_RELEASES = [
    value.strip()
    for value in os.getenv(
        "SPHEREX_RELEASES",
        "spherex_qr3,spherex_qr2"
    ).split(",")
    if value.strip()
]

UPSTREAM_TIMEOUT_MS = int(
    os.getenv("SPHEREX_UPSTREAM_TIMEOUT_MS", "60000")
)

QUERY_CACHE_TTL_MS = int(
    os.getenv(
        "SPHEREX_QUERY_CACHE_TTL_MS",
        str(10 * 60 * 1000)
    )
)

PREVIEW_SIZE_DEGREES = float(
    os.getenv("SPHEREX_PREVIEW_SIZE_DEGREES", "0.5")
)


IMAGE_CACHE_MAX_BYTES = int(
    os.getenv(
        "SPHEREX_IMAGE_CACHE_MAX_BYTES",
        str(64 * 1024 * 1024)
    )
)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

query_cache = TTLCache()


# ---------------------------------------------------------------------------
# SPHEREx bands
# ---------------------------------------------------------------------------

BAND_RANGES_MICRONS = {
    "SPHEREx-D1": (0.75, 1.10),
    "SPHEREx-D2": (1.10, 1.62),
    "SPHEREx-D3": (1.63, 2.41),
    "SPHEREx-D4": (2.42, 3.82),
    "SPHEREx-D5": (3.83, 4.41),
    "SPHEREx-D6": (4.42, 5.00),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class APIError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)

        self.status = status
        self.code = code
        self.message = message
        self.details = details


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def parse_coordinate(value, name, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise APIError(
            400,
            "INVALID_COORDINATE",
            f"{name} must be between {minimum} and {maximum}."
        )

    if not math.isfinite(number) or number < minimum or number > maximum:
        raise APIError(
            400,
            "INVALID_COORDINATE",
            f"{name} must be between {minimum} and {maximum}."
        )

    return number


def parse_radius(value):
    if value is None:
        radius = 0.1
    else:
        try:
            radius = float(value)
        except (TypeError, ValueError):
            radius = float("nan")

    if (
        not math.isfinite(radius)
        or radius <= 0
        or radius > 5
    ):
        raise APIError(
            400,
            "INVALID_RADIUS",
            "radius must be greater than 0 and no more than 5 degrees."
        )

    return radius


def as_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if math.isfinite(number) else None


# ---------------------------------------------------------------------------
# Astronomy helpers
# ---------------------------------------------------------------------------

def mjd_to_iso(mjd):
    """
    Convert Modified Julian Date to an ISO-8601 timestamp.
    """

    number = as_number(mjd)

    if number is None:
        return None

    # Same conversion as:
    # (MJD + 2400000.5 - 2440587.5) * 86400000
    unix_seconds = (
        number + 2400000.5 - 2440587.5
    ) * 86400

    try:
        from datetime import datetime, timezone

        date = datetime.fromtimestamp(
            unix_seconds,
            tz=timezone.utc
        )

        return date.isoformat(timespec="milliseconds").replace(
            "+00:00",
            "Z"
        )

    except (OverflowError, OSError, ValueError):
        return None


def angular_distance(ra1, dec1, ra2, dec2):
    """
    Calculate angular separation in degrees.
    """

    values = [ra1, dec1, ra2, dec2]

    if not all(
        isinstance(value, (int, float))
        and math.isfinite(value)
        for value in values
    ):
        return None

    to_rad = math.pi / 180

    a = (
        math.sin((dec2 - dec1) * to_rad / 2) ** 2
        +
        math.cos(dec1 * to_rad)
        * math.cos(dec2 * to_rad)
        * math.sin((ra2 - ra1) * to_rad / 2) ** 2
    )

    a = min(1, max(0, a))

    return (
        2 * math.asin(math.sqrt(a))
        / to_rad
    )


def point_in_footprint(footprint, ra, dec):
    """
    Basic point-in-polygon test for an IRSA POLYGON footprint.

    Returns:
        True / False if a valid polygon was provided.
        None if the footprint cannot be interpreted.
    """

    if not footprint or not footprint.startswith("POLYGON"):
        return None

    import re

    values = re.findall(
        r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?",
        footprint
    )

    if len(values) < 6:
        return None

    points = []

    for index in range(0, len(values) - 1, 2):
        point_ra = float(values[index])
        point_dec = float(values[index + 1])

        relative_ra = (
            (point_ra - ra + 540) % 360
        ) - 180

        points.append(
            (relative_ra, point_dec)
        )

    x = 0
    inside = False

    previous = len(points) - 1

    for index in range(len(points)):
        xi, yi = points[index]
        xj, yj = points[previous]

        if yi == yj:
            intersects = False
        else:
            intersects = (
                ((yi > dec) != (yj > dec))
                and
                (
                    x
                    <
                    (xj - xi)
                    * (dec - yi)
                    / (yj - yi)
                    + xi
                )
            )

        if intersects:
            inside = not inside

        previous = index

    return inside


# ---------------------------------------------------------------------------
# SIA response parsing
# ---------------------------------------------------------------------------

def parse_sia_json(payload):
    """
    Convert IRSA SIA2 JSON/VOTable representation into a list of dictionaries.
    """

    try:
        resources = payload["VOTABLE"]["RESOURCE_ARRAY"]
    except (KeyError, TypeError):
        raise ValueError(
            "IRSA returned an unexpected SIA response."
        )

    if not isinstance(resources, list):
        raise ValueError(
            "IRSA returned an unexpected SIA response."
        )

    result = next(
        (
            resource
            for resource in resources
            if (
                isinstance(resource, dict)
                and resource.get("<xmlattr>", {}).get("type")
                == "results"
            )
        ),
        None
    )

    if not result:
        raise ValueError(
            "IRSA returned an unexpected SIA response."
        )

    table = result.get("TABLE")

    if not table:
        raise ValueError(
            "IRSA returned an unexpected SIA response."
        )

    field_array = table.get("FIELD_ARRAY")
    rows = table.get("DATA", {}).get("TABLEDATA")

    if not isinstance(field_array, list) or not isinstance(rows, list):
        raise ValueError(
            "IRSA returned an unexpected SIA response."
        )

    fields = [
        field.get("<xmlattr>", {}).get("name")
        for field in field_array
    ]

    return [
        {
            field: row[index] if index < len(row) else ""
            for index, field in enumerate(fields)
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Record normalization
# ---------------------------------------------------------------------------

def normalize_record(row, ra, dec, requested_release):
    cloud_access = None

    try:
        if row.get("cloud_access"):
            cloud_access = json.loads(row["cloud_access"])
    except (json.JSONDecodeError, TypeError):
        cloud_access = None

    product_id = (
        row.get("obs_publisher_did")
        or row.get("access_url")
    )

    s_ra = as_number(row.get("s_ra"))
    s_dec = as_number(row.get("s_dec"))

    em_min = as_number(row.get("em_min"))
    em_max = as_number(row.get("em_max"))

    record = {
        "obs_id": row.get("obs_id") or product_id,
        "product_id": product_id,

        "ra": s_ra,
        "dec": s_dec,

        "distance": angular_distance(
            ra,
            dec,
            s_ra,
            s_dec
        ),

        "coverage_at_query": point_in_footprint(
            row.get("s_region"),
            ra,
            dec
        ),

        "obs_date": mjd_to_iso(
            row.get("t_min")
        ),

        "obs_date_end": mjd_to_iso(
            row.get("t_max")
        ),

        "mjd": as_number(row.get("t_min")),
        "mjd_end": as_number(row.get("t_max")),

        "wavelength_band": (
            row.get("energy_bandpassname")
            or None
        ),

        "wavelength_min_microns": (
            None
            if em_min is None
            else em_min * 1e6
        ),

        "wavelength_max_microns": (
            None
            if em_max is None
            else em_max * 1e6
        ),

        "spectral_resolution": as_number(
            row.get("em_res_power")
        ),

        "data_release": (
            row.get("obs_collection")
            or requested_release
        ),

        "access_url": row.get("access_url") or None,
        "original_archive_url": row.get("access_url") or None,

        "cutout_url": None,
        "image_url": None,

        "access_format": row.get("access_format") or None,

        "estimated_size_bytes": as_number(
            row.get("access_estsize")
        ),

        "exposure_seconds": as_number(
            row.get("t_exptime")
        ),

        "detector_pixels": (
            f"{row['s_xel1']} × {row['s_xel2']}"
            if row.get("s_xel1") and row.get("s_xel2")
            else None
        ),

        "pixel_scale_arcsec": as_number(
            row.get("s_pixel_scale")
        ),

        "field_of_view_degrees": as_number(
            row.get("s_fov")
        ),

        "target_name": row.get("target_name") or None,
        "target_type": row.get("target_type") or None,

        "target_moving": row.get("target_moving") == "1",

        "quality": {
            "calibration_level": as_number(
                row.get("calib_level")
            ),
            "intent": row.get("obs_intent") or None,
            "environment_photometric": (
                row.get("environment_photometric")
                or None
            ),
        },

        "provenance": {
            "service": "IRSA SIA2",
            "collection": (
                row.get("obs_collection")
                or requested_release
            ),
            "publisher_did": (
                row.get("obs_publisher_did")
                or None
            ),
            "cloud_access": cloud_access,
        },

        # Internal field; don't expose directly in API JSON.
        "_upstream_url": row.get("access_url"),
    }

    product = product_id
    obs_id = record["obs_id"]

    if product:
        params = urlencode({
            "product": product,
            "ra": str(ra),
            "dec": str(dec),
            "size": str(PREVIEW_SIZE_DEGREES),
        })

        record["image_url"] = (
            f"/api/spherex/image/"
            f"{obs_id}?{params}"
        )

        record["cutout_url"] = (
            f"/api/spherex/cutout?{params}"
        )

        hips_band = (
            row.get("energy_bandpassname") or "SPHEREx-D2"
        ).replace("SPHEREx-", "")

        record["hips_preview_url"] = (
            "/api/spherex/sky/preview?"
            + urlencode({
                "band": hips_band,
                "ra": str(ra),
                "dec": str(dec),
                "fov": str(PREVIEW_SIZE_DEGREES),
                "width": "512",
                "height": "512",
            })
        )

    return record


# ---------------------------------------------------------------------------
# IRSA querying
# ---------------------------------------------------------------------------

def query_release(ra, dec, radius, band, release):
    """
    Query one SPHEREx release through IRSA SIA2.
    """

    params = {
        "COLLECTION": release,
        "POS": f"circle {ra} {dec} {radius}",
        "RESPONSEFORMAT": "JSON",
        "MAXREC": "500",
    }

    wavelength_range = BAND_RANGES_MICRONS.get(band)

    if wavelength_range:
        params["BAND"] = (
            f"{wavelength_range[0] * 1e-6} "
            f"{wavelength_range[1] * 1e-6}"
        )

    timeout = UPSTREAM_TIMEOUT_MS / 1000

    response = requests.get(
        IRSA_SIA_URL,
        params=params,
        timeout=timeout,
    )

    response.raise_for_status()

    return parse_sia_json(response.json())


# ---------------------------------------------------------------------------
# Observation search
# ---------------------------------------------------------------------------

def get_observations(ra, dec, radius, band):
    """
    Query all configured SPHEREx releases and combine their results.
    """

    band_key = band or ""

    key = (
        f"{ra:.6f}:"
        f"{dec:.6f}:"
        f"{radius:.5f}:"
        f"{band_key}:"
        f"{','.join(DEFAULT_RELEASES)}"
    )

    cached = query_cache.get(key)

    if cached is not None:
        return cached

    rows = []
    failures = []

    with ThreadPoolExecutor(
        max_workers=len(DEFAULT_RELEASES)
    ) as executor:

        futures = {
            executor.submit(
                query_release,
                ra,
                dec,
                radius,
                band,
                release,
            ): release
            for release in DEFAULT_RELEASES
        }

    for future in as_completed(futures):
        release = futures[future]

        try:
            release_rows = future.result()

            for row in release_rows:
                rows.append(
                    (
                        row,
                        release,
                    )
                )

        except Exception as error:
            failures.append(error)

    if not rows and len(failures) == len(DEFAULT_RELEASES):
        details = str(failures[0]) if failures else None

        raise APIError(
            502,
            "IRSA_UNAVAILABLE",
            "IRSA did not return observation metadata.",
            details,
        )

    records = []

    for row, release in rows:
        record = normalize_record(
            row,
            ra,
            dec,
            release,
        )

        # Must have usable coordinates and an access URL
        if not record["access_url"]:
            continue

        if record["ra"] is None or record["dec"] is None:
            continue

        # If footprint explicitly says we're outside it, discard it.
        if record["coverage_at_query"] is False:
            continue

        # Additional band filtering
        if (
            band
            and record["wavelength_band"] != band
        ):
            continue

        # Avoid previews that don't fit within the observation FOV.
        fov = record["field_of_view_degrees"]
        distance = record["distance"]

        if (
            fov is not None
            and distance is not None
            and distance
            > (fov / 2)
            - (PREVIEW_SIZE_DEGREES / 2)
        ):
            continue

        records.append(record)

    # Remove duplicate products
    seen = set()
    unique_records = []

    for record in records:
        product_id = record["product_id"]

        if product_id in seen:
            continue

        seen.add(product_id)
        unique_records.append(record)

    # Sort by observation date, then distance
    unique_records.sort(
        key=lambda record: (
            record["mjd"]
            if record["mjd"] is not None
            else float("inf"),

            record["distance"]
            if record["distance"] is not None
            else float("inf"),
        )
    )

    query_cache.set(
        key,
        unique_records,
        QUERY_CACHE_TTL_MS / 1000,
    )

    return unique_records