import os

from flask import Flask, jsonify
from dotenv import load_dotenv
from spherex.routes import spherex_bp

app = Flask(__name__)
load_dotenv()

app.register_blueprint(spherex_bp)

IRSA_SIA_URL = os.getenv("SPHEREX_SIA_URL",
                "https://irsa.ipac.caltech.edu/SIA"
)

DEFAULT_RELEASE = [
    value.strip()
    for value in os.getenv("SPHEREX_RELEASES",
                           "spherex_qr3, spherex_qr2"
    ).split(",")
    if value.strip()
]


UPSTREAM_TIMEOUT_MS = int(os.getenv("SPHEREX_UPSTREAM_TIMEOUT_MS", "60000"))

QUERY_CACHE_TTL_MS = int(os.getenv("SPHEREX_QUERY_CACHE_TTL_MS", str(10 * 60 * 1000)))

IMAGE_CACHE_TTL_MS = int(os.getenv("SPHEREX_IMAGE_CACHE_TTL_MS", str(30 * 60 * 1000)))

IMAGE_CACHE_MAX_BYTES = int(
    os.getenv(
        "SPHEREX_IMAGE_CACHE_MAX_BYTES",
        str(64 * 1024 * 1024)
    )
)

REVIEW_SIZE_DEGREES = float(
    os.getenv(
        "SPHEREX_REVIEW_SIZE_DEGREES",
        "0.5"
    )
)

@app.get("/")
def index():
    return jsonify({
        "name": "SPHEREx API",
        "description": "API for querying SPHEREx observations and retrieving image cutouts from NASA/IPAC IRSA.",
        "version": "1.0.0",

        "endpoints": {
            "GET /": {
                "description": "API documentation and endpoint overview."
            },

            "GET /api/spherex/observations": {
                "description": "Search for SPHEREx observations around a sky coordinate.",
                "parameters": {
                    "ra": "Right ascension in degrees (0-360).",
                    "dec": "Declination in degrees (-90 to 90).",
                    "radius": "Search radius in degrees (0-5). Defaults to 0.1.",
                    "band": "SPHEREx-D1 through SPHEREx-D6, or 'all'. Defaults to SPHEREx-D2."
                },
                "example": "/api/spherex/observations?ra=180&dec=0&radius=0.1&band=SPHEREx-D2"
            },

            "GET /api/spherex/image/<obsId>": {
                "description": "Generate a PNG preview of a SPHEREx observation.",
                "parameters": {
                    "obsId": "Observation ID returned by the observations endpoint.",
                    "ra": "Right ascension in degrees.",
                    "dec": "Declination in degrees.",
                    "size": "Preview size in degrees (0.01-0.5)."
                }
            },

            "GET /api/spherex/cutout": {
                "description": "Retrieve the original FITS cutout for an observation.",
                "parameters": {
                    "product": "Product ID returned by the observations endpoint.",
                    "ra": "Right ascension in degrees.",
                    "dec": "Declination in degrees.",
                    "size": "Cutout size in degrees (0.01-0.5)."
                }
            },


            "GET /api/spherex/stats": {
                "description": "Returns information about the API, data source, releases, and cache configuration."
            }
        },

        "data_source": {
            "name": "NASA/IPAC IRSA SIA2",
            "url": IRSA_SIA_URL
        }
    })


@app.get("/api/spherex/stats")
def stats():
    return jsonify({
        "source": "NASA/IPAC IRSA SIA2",
        "releases": DEFAULT_RELEASE,
        "query_mode": "on-demand",
        "cache": {
            "metadata_ttl_seconds": QUERY_CACHE_TTL_MS / 1000,
            "preview_cache_max_bytes": IMAGE_CACHE_MAX_BYTES
        },
        "total_observations": None,
        "bands": None,
        "surveys_by_date": None,
        "unique_targets": None
    })



if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )