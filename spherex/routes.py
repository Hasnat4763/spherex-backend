import os
from urllib.parse import urlencode, urlparse, urlunparse

import requests
from flask import Blueprint, Response, jsonify, request

from .cache import TTLCache
from .fits import fits_to_png
from .irsa import (
    APIError,
    BAND_RANGES_MICRONS,
    DEFAULT_RELEASES,
    IMAGE_CACHE_MAX_BYTES,
    PREVIEW_SIZE_DEGREES,
    UPSTREAM_TIMEOUT_MS,
    get_observations,
    parse_coordinate,
    parse_radius,
)


spherex_bp = Blueprint(
    "spherex",
    __name__,
    url_prefix="/api/spherex",
)


# ---------------------------------------------------------------------------
# Image cache
# ---------------------------------------------------------------------------

IMAGE_CACHE_TTL_MS = int(
    os.getenv(
        "SPHEREX_IMAGE_CACHE_TTL_MS",
        str(30 * 60 * 1000)
    )
)

image_cache = TTLCache(
    max_bytes=IMAGE_CACHE_MAX_BYTES
)


# ---------------------------------------------------------------------------
# Observation lookup
# ---------------------------------------------------------------------------

# The original Node API stores records in memory after an observations query.
# We do the same here.
records_by_product = {}


def store_records(records):
    for record in records:
        product_id = record.get("product_id")

        if product_id:
            records_by_product[product_id] = record


def get_record(product=None, obs_id=None):
    """
    Find an observation by product ID or observation ID.
    """

    if product:
        record = records_by_product.get(product)

        if record:
            return record

    if obs_id:
        for record in records_by_product.values():
            if record.get("obs_id") == obs_id:
                return record

    return None


# ---------------------------------------------------------------------------
# Cutout URL
# ---------------------------------------------------------------------------

def cutout_url(record, ra, dec, size):
    """
    Build the upstream IRSA cutout URL from the observation's
    original access URL.
    """

    upstream_url = record.get("_upstream_url")

    if not upstream_url:
        raise APIError(
            502,
            "UPSTREAM_URL_MISSING",
            "The observation does not have an upstream archive URL."
        )

    parsed = urlparse(upstream_url)

    query = urlencode({
        "center": f"{ra},{dec}d",
        "size": str(size),
    })

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        query,
        parsed.fragment,
    ))


# ---------------------------------------------------------------------------
# Cutout size validation
# ---------------------------------------------------------------------------

def validate_cutout_size(value):
    if value is None:
        size = PREVIEW_SIZE_DEGREES
    else:
        try:
            size = float(value)
        except (TypeError, ValueError):
            size = float("nan")

    if (
        not size == size
        or size < 0.01
        or size > 0.5
    ):
        raise APIError(
            400,
            "INVALID_CUTOUT_SIZE",
            "size must be between 0.01 and 0.5 degrees."
        )

    return size


# ---------------------------------------------------------------------------
# Preview fetching
# ---------------------------------------------------------------------------

def fetch_preview(record, ra, dec, size):
    """
    Fetch a FITS cutout from IRSA and convert it to PNG.
    """

    product_id = record.get("product_id")

    key = (
        f"{product_id}:"
        f"{ra:.6f}:"
        f"{dec:.6f}:"
        f"{size}"
    )

    cached = image_cache.get(key)

    if cached is not None:
        return cached

    url = cutout_url(
        record,
        ra,
        dec,
        size,
    )

    timeout = UPSTREAM_TIMEOUT_MS / 1000

    try:
        response = requests.get(
            url,
            timeout=timeout,
            stream=False,
        )

        response.raise_for_status()

        png = fits_to_png(
            response.content
        )

    except requests.HTTPError as error:
        # IRSA can reject an exact query position for an edge
        # product. Retry at the real product center.
        if (
            error.response is None
            or error.response.status_code != 422
            or record.get("ra") is None
            or record.get("dec") is None
        ):
            raise

        fallback_url = cutout_url(
            record,
            record["ra"],
            record["dec"],
            size,
        )

        fallback_response = requests.get(
            fallback_url,
            timeout=timeout,
            stream=False,
        )

        fallback_response.raise_for_status()

        png = fits_to_png(
            fallback_response.content
        )

    image_cache.set(
        key,
        png,
        IMAGE_CACHE_TTL_MS / 1000,
        len(png),
    )

    return png


# ---------------------------------------------------------------------------
# Error conversion
# ---------------------------------------------------------------------------

def error_response(error):
    """
    Convert our APIError into the JSON format used by the original API.
    """

    details = None

    if (
        os.getenv("NODE_ENV", "").lower()
        == "development"
        and error.details
    ):
        details = error.details

    payload = {
        "error": error.code,
        "message": error.message,
    }

    if details is not None:
        payload["details"] = details

    return jsonify(payload), error.status


# ---------------------------------------------------------------------------
# GET /observations
# ---------------------------------------------------------------------------

@spherex_bp.get("/observations")
def observations():


    try:
        ra = parse_coordinate(
            request.args.get("ra"),
            "ra",
            0,
            360,
        )

        dec = parse_coordinate(
            request.args.get("dec"),
            "dec",
            -90,
            90,
        )

        radius = parse_radius(
            request.args.get("radius")
        )

        band = (
            request.args.get("band")
            or "SPHEREx-D2"
        )


        if (
            band != "all"
            and band not in BAND_RANGES_MICRONS
        ):
            raise APIError(
                400,
                "INVALID_BAND",
                "band must be one of SPHEREx-D1 through "
                "SPHEREx-D6, or all."
            )


        records = get_observations(
            ra=ra,
            dec=dec,
            radius=radius,
            band=None if band == "all" else band,
        )


        store_records(records)


        public_records = []

        for record in records[:500]:
            public_record = {
                key: value
                for key, value in record.items()
                if not key.startswith("_")
            }

            public_records.append(
                public_record
            )

        return jsonify(public_records)

    except APIError as error:
        return error_response(error)

    except requests.RequestException as error:
        return jsonify({
            "error": "UPSTREAM_ERROR",
            "message": str(error),
        }), 502

    except Exception as error:
        return jsonify({
            "error": "UPSTREAM_ERROR",
            "message": str(error),
        }), 502

# ---------------------------------------------------------------------------
# GET /image/<obsId>
# ---------------------------------------------------------------------------

@spherex_bp.get("/image/<obs_id>")
def image(obs_id):
    try:
        ra = parse_coordinate(
            request.args.get("ra"),
            "ra",
            0,
            360,
        )

        dec = parse_coordinate(
            request.args.get("dec"),
            "dec",
            -90,
            90,
        )

        size = validate_cutout_size(
            request.args.get("size")
        )

        product = request.args.get("product")

        record = get_record(
            product=product,
            obs_id=obs_id,
        )

        if not record:
            raise APIError(
                404,
                "OBSERVATION_NOT_FOUND",
                "Observation metadata is no longer in "
                "the server cache. Query observations again first."
            )

        png = fetch_preview(
            record,
            ra,
            dec,
            size,
        )

        response = Response(
            png,
            mimetype="image/png",
        )

        response.headers["Cache-Control"] = (
            f"public, max-age="
            f"{IMAGE_CACHE_TTL_MS // 1000}"
        )

        response.headers["X-Data-Source"] = (
            "NASA/IPAC IRSA SPHEREx cutout"
        )

        return response

    except APIError as error:
        return error_response(error)

    except requests.Timeout:
        return jsonify({
            "error": "UPSTREAM_TIMEOUT",
            "message": (
                "The SPHEREx data service timed out."
            ),
        }), 504

    except requests.RequestException as error:
        return jsonify({
            "error": "UPSTREAM_ERROR",
            "message": str(error),
        }), 502

    except Exception as error:
        return jsonify({
            "error": "UPSTREAM_ERROR",
            "message": str(error),
        }), 502


# ---------------------------------------------------------------------------
# GET /cutout
# ---------------------------------------------------------------------------

@spherex_bp.get("/cutout")
def cutout():
    try:
        product = request.args.get("product")

        record = get_record(
            product=product
        )

        if not record:
            raise APIError(
                404,
                "OBSERVATION_NOT_FOUND",
                "Observation metadata is no longer in "
                "the server cache. Query observations again first."
            )

        ra = parse_coordinate(
            request.args.get("ra"),
            "ra",
            0,
            360,
        )

        dec = parse_coordinate(
            request.args.get("dec"),
            "dec",
            -90,
            90,
        )

        size = validate_cutout_size(
            request.args.get("size")
        )

        url = cutout_url(
            record,
            ra,
            dec,
            size,
        )

        response = requests.get(
            url,
            timeout=UPSTREAM_TIMEOUT_MS / 1000,
        )

        response.raise_for_status()

        result = Response(
            response.content,
            mimetype="application/fits",
        )

        result.headers["Content-Disposition"] = (
            "inline; "
            f'filename="{record.get("obs_id")}-cutout.fits"'
        )

        result.headers["X-Data-Source"] = (
            "NASA/IPAC IRSA SPHEREx cutout service"
        )

        return result

    except APIError as error:
        return error_response(error)

    except requests.Timeout:
        return jsonify({
            "error": "UPSTREAM_TIMEOUT",
            "message": (
                "The SPHEREx data service timed out."
            ),
        }), 504

    except requests.RequestException as error:
        return jsonify({
            "error": "UPSTREAM_ERROR",
            "message": str(error),
        }), 502

    except Exception as error:
        return jsonify({
            "error": "UPSTREAM_ERROR",
            "message": str(error),
        }), 502


# ---------------------------------------------------------------------------
# POST /detect-moving-objects
# ---------------------------------------------------------------------------

@spherex_bp.post("/detect-moving-objects")
def detect_moving_objects():
    return jsonify({
        "error": "MOVING_OBJECT_ANALYSIS_UNAVAILABLE",
        "message": (
            "This API does not infer object classifications "
            "or motion from image metadata. Use repeated "
            "observations for human or validated downstream analysis."
        ),
    }), 501


# ---------------------------------------------------------------------------
# GET /search
# ---------------------------------------------------------------------------
@spherex_bp.get("/search")
def search():
    return jsonify({
        "error": "SEARCH_UNAVAILABLE",
        "message": (
            "Target-name search is not provided by the SIA "
            "metadata service. Search by sky coordinates instead."
        ),
    }), 501