# SPHEREx Backend API

A lightweight Flask backend for discovering SPHEREx observations and retrieving image products from the NASA/IPAC Infrared Science Archive (IRSA).

The service provides coordinate-based observation searches, PNG previews generated from FITS cutouts, original FITS cutouts, API metadata, and explicit responses for capabilities that are not currently implemented.

## Features

- Query SPHEREx observations by right ascension, declination, search radius, and spectral band.
- Query the configured SPHEREx data releases through the IRSA Simple Image Access (SIA2) service.
- Normalize IRSA metadata into a consistent JSON representation.
- Generate PNG previews from FITS image data using percentile normalization and an asinh stretch.
- Return original FITS cutouts from the upstream archive.
- Cache observation metadata and generated previews using an in-memory TTL cache backed by SQLite.
- Expose service and cache configuration through environment variables.
- Return structured JSON errors for invalid input, unavailable observations, upstream failures, and timeouts.

## API overview

The application runs on port `5000` by default and registers its main blueprint under `/api/spherex`.

### `GET /`

Returns a machine-readable service overview, including the available endpoints, defaults, configured releases, and the upstream IRSA SIA URL.

Example:

```bash
curl http://localhost:5000/
```

### `GET /api/spherex/stats`

Returns service metadata and cache information.

Example response:

```json
{
  "source": "NASA/IPAC IRSA SIA2",
  "releases": ["spherex_qr3", "spherex_qr2"],
  "query_mode": "on-demand",
  "cache": {
    "metadata_ttl_seconds": 600.0,
    "preview_cache_max_bytes": 67108864
  },
  "total_observations": null,
  "bands": null,
  "surveys_by_date": null,
  "unique_targets": null
}
```

The aggregate statistics fields are currently placeholders and return `null`.

### `GET /api/spherex/observations`

Searches for SPHEREx observations around a sky coordinate. The backend queries every release configured in `SPHEREX_RELEASES`, combines the results, removes duplicate products, filters invalid or unsuitable records, and returns up to 500 records.

#### Query parameters

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `ra` | Yes | — | Right ascension in degrees, from `0` through `360`. |
| `dec` | Yes | — | Declination in degrees, from `-90` through `90`. |
| `radius` | No | `0.1` | Search radius in degrees. Must be greater than `0` and no more than `5`. |
| `band` | No | `SPHEREx-D2` | One of `SPHEREx-D1` through `SPHEREx-D6`, or `all`. |

Supported bands and approximate wavelength ranges:

| Band | Wavelength range |
| --- | --- |
| `SPHEREx-D1` | `0.75–1.10 µm` |
| `SPHEREx-D2` | `1.10–1.62 µm` |
| `SPHEREx-D3` | `1.63–2.41 µm` |
| `SPHEREx-D4` | `2.42–3.82 µm` |
| `SPHEREx-D5` | `3.83–4.41 µm` |
| `SPHEREx-D6` | `4.42–5.00 µm` |

Example:

```bash
curl "http://localhost:5000/api/spherex/observations?ra=180&dec=0&radius=0.1&band=SPHEREx-D2"
```

Each returned observation may include fields such as:

- `obs_id` and `product_id`
- observation coordinates and angular `distance` from the query position
- `coverage_at_query`
- observation start and end dates in ISO-8601 format
- Modified Julian Date values
- wavelength band and wavelength limits in microns
- spectral resolution, exposure time, detector dimensions, pixel scale, and field of view
- target name and target type
- quality and provenance metadata
- generated `image_url` and `cutout_url` values for the preview and FITS endpoints

The response is a JSON array. Internal upstream fields are not exposed directly.

### `GET /api/spherex/image/<obs_id>`

Fetches a FITS cutout from IRSA, converts it to a PNG preview, and returns the image bytes with `Content-Type: image/png`.

#### Path parameter

- `obs_id`: Observation identifier returned by the observations endpoint.

#### Query parameters

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `product` | Recommended | — | Product identifier returned by the observations endpoint. |
| `ra` | Yes | — | Right ascension in degrees, from `0` through `360`. |
| `dec` | Yes | — | Declination in degrees, from `-90` through `90`. |
| `size` | No | `0.5` | Cutout size in degrees. Must be between `0.01` and `0.5`. |

The server stores observation metadata in memory after a successful observation search. Therefore, query `/observations` first and then use the returned image URL or provide the matching `product` value. Metadata is not guaranteed to survive a process restart or deployment with multiple independent workers.

Example:

```bash
curl -o preview.png \
  "http://localhost:5000/api/spherex/image/OBSERVATION_ID?product=PRODUCT_ID&ra=180&dec=0&size=0.1"
```

The preview conversion process:

1. Reads the first usable 2D image HDU from the FITS file.
2. Uses the 1st and 99.5th finite-pixel percentiles for contrast limits.
3. Applies an inverse hyperbolic sine stretch.
4. Converts the result to an RGB PNG with a slight blue tint.
5. Replaces invalid pixels with black.

### `GET /api/spherex/cutout`

Returns the original FITS cutout from IRSA with `Content-Type: application/fits`.

#### Query parameters

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `product` | Yes | — | Product identifier returned by the observations endpoint. |
| `ra` | Yes | — | Right ascension in degrees, from `0` through `360`. |
| `dec` | Yes | — | Declination in degrees, from `-90` through `90`. |
| `size` | No | `0.5` | Cutout size in degrees. Must be between `0.01` and `0.5`. |

Example:

```bash
curl -o cutout.fits \
  "http://localhost:5000/api/spherex/cutout?product=PRODUCT_ID&ra=180&dec=0&size=0.1"
```

The response includes an inline `Content-Disposition` filename based on the observation ID and an `X-Data-Source` header identifying the IRSA cutout service.

### `POST /api/spherex/detect-moving-objects`

Not currently implemented. The endpoint returns HTTP `501`:

```json
{
  "error": "MOVING_OBJECT_ANALYSIS_UNAVAILABLE",
  "message": "This API does not infer object classifications or motion from image metadata. Use repeated observations for human or validated downstream analysis."
}
```

### `GET /api/spherex/search`

Not currently implemented. Target-name search is not provided by the current SIA metadata integration. Search by sky coordinates instead.

The endpoint returns HTTP `501`:

```json
{
  "error": "SEARCH_UNAVAILABLE",
  "message": "Target-name search is not provided by the SIA metadata service. Search by sky coordinates instead."
}
```

## Error responses

Validation and application errors use a consistent JSON structure:

```json
{
  "error": "INVALID_COORDINATE",
  "message": "ra must be between 0 and 360."
}
```

Common error codes include:

| HTTP status | Error code | Meaning |
| --- | --- | --- |
| `400` | `INVALID_COORDINATE` | `ra` or `dec` is missing, non-numeric, or outside its valid range. |
| `400` | `INVALID_RADIUS` | The search radius is not greater than `0` or exceeds `5` degrees. |
| `400` | `INVALID_BAND` | The requested band is not supported. |
| `400` | `INVALID_CUTOUT_SIZE` | The cutout size is outside `0.01–0.5` degrees or is invalid. |
| `404` | `OBSERVATION_NOT_FOUND` | The product or observation is not present in the server's metadata cache. |
| `501` | `SEARCH_UNAVAILABLE` | Target-name search is not implemented. |
| `501` | `MOVING_OBJECT_ANALYSIS_UNAVAILABLE` | Moving-object analysis is not implemented. |
| `502` | `IRSA_UNAVAILABLE` | No configured IRSA release returned usable metadata. |
| `502` | `UPSTREAM_ERROR` | The upstream service returned an unsuccessful response or another request error occurred. |
| `504` | `UPSTREAM_TIMEOUT` | The upstream IRSA request exceeded the configured timeout. |

## Architecture

```text
Client
  |
  v
Flask application (main.py)
  |
  +--> /api/spherex routes (spherex/routes.py)
          |
          +--> observation queries (spherex/irsa.py)
          |       |
          |       +--> NASA/IPAC IRSA SIA2
          |
          +--> FITS cutout retrieval
          |       |
          |       +--> NASA/IPAC IRSA archive
          |
          +--> FITS-to-PNG conversion (spherex/fits.py)
          |
          +--> TTL caches (spherex/cache.py + SQLite)
```

### Main modules

- `main.py` — creates the Flask application, loads environment variables, registers the blueprint, exposes `/` and `/api/spherex/stats`, and starts the development server.
- `spherex/routes.py` — defines HTTP routes, validates request parameters, manages observation lookup, fetches previews and FITS files, and formats errors.
- `spherex/irsa.py` — communicates with IRSA SIA2, parses responses, normalizes observation metadata, applies coordinate and band filtering, and creates frontend-facing URLs.
- `spherex/fits.py` — reads FITS image data and converts it to PNG previews.
- `spherex/cache.py` — implements an in-memory TTL/LRU-style cache with SQLite persistence for cached values.

## Data source

The backend uses the NASA/IPAC Infrared Science Archive SIA2 service. The default endpoint is:

```text
https://irsa.ipac.caltech.edu/SIA
```

The service performs on-demand queries rather than maintaining a local observation catalog. Results are requested from the configured releases, normalized, filtered, and cached.

## Requirements

The repository is Python-based and currently does not include a `requirements.txt` or `pyproject.toml`. Install the runtime dependencies manually:

```bash
python -m pip install Flask python-dotenv requests numpy Pillow astropy
```

Python 3.10 or newer is recommended.

## Local setup

1. Clone the repository:

   ```bash
   git clone https://github.com/Hasnat4763/spherex-backend.git
   cd spherex-backend
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install Flask python-dotenv requests numpy Pillow astropy
   ```

4. Start the API:

   ```bash
   python main.py
   ```

5. Verify that it is running:

   ```bash
   curl http://localhost:5000/
   ```

The server binds to `0.0.0.0` and uses port `5000` by default.

## Configuration

Configuration is read from environment variables. A `.env` file is supported through `python-dotenv`.

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `5000` | Local HTTP port used by `main.py`. |
| `FLASK_DEBUG` | `false` | Enables Flask debug mode when set to `true`. |
| `SPHEREX_SIA_URL` | `https://irsa.ipac.caltech.edu/SIA` | Upstream IRSA SIA2 endpoint. |
| `SPHEREX_RELEASES` | `spherex_qr3,spherex_qr2` | Comma-separated list of IRSA collections to query. |
| `SPHEREX_UPSTREAM_TIMEOUT_MS` | `60000` | Timeout for upstream requests in milliseconds. |
| `SPHEREX_QUERY_CACHE_TTL_MS` | `600000` | Observation metadata cache lifetime in milliseconds. |
| `SPHEREX_IMAGE_CACHE_TTL_MS` | `1800000` | PNG preview cache lifetime in milliseconds. |
| `SPHEREX_IMAGE_CACHE_MAX_BYTES` | `67108864` | Maximum in-memory preview cache size in bytes. |
| `SPHEREX_PREVIEW_SIZE_DEGREES` | `0.5` | Default preview size in degrees. |
| `SPHEREX_REVIEW_SIZE_DEGREES` | `0.5` | Legacy/configuration value exposed by `main.py`; route defaults use `SPHEREX_PREVIEW_SIZE_DEGREES`. |
| `NODE_ENV` | — | When set to `development`, internal error details may be included in API error responses. |

Example `.env` file:

```dotenv
PORT=5000
FLASK_DEBUG=false
SPHEREX_SIA_URL=https://irsa.ipac.caltech.edu/SIA
SPHEREX_RELEASES=spherex_qr3,spherex_qr2
SPHEREX_UPSTREAM_TIMEOUT_MS=60000
SPHEREX_QUERY_CACHE_TTL_MS=600000
SPHEREX_IMAGE_CACHE_TTL_MS=1800000
SPHEREX_IMAGE_CACHE_MAX_BYTES=67108864
SPHEREX_PREVIEW_SIZE_DEGREES=0.5
NODE_ENV=production
```

## Caching and operational notes

- Observation query results are cached for 10 minutes by default.
- Generated PNG previews are cached for 30 minutes by default and are limited to 64 MiB in memory.
- The cache implementation also creates `spherex/db/cache.db` by default. This file is ignored by Git through the `*.db` rule.
- Observation metadata used by `/image/<obs_id>` and `/cutout` is stored in process memory. A client should request observations before requesting a preview or FITS cutout.
- In a multi-worker deployment, each worker has its own in-memory observation map. Use sticky behavior, a shared metadata store, or an architectural change if requests can move between workers.
- IRSA is an external dependency. Availability, response time, rate limits, and returned metadata can affect API responses.
- Do not enable Flask debug mode in production.

## Development

Run the application directly during development:

```bash
FLASK_DEBUG=true python main.py
```

Before deploying, consider adding:

- a pinned dependency file such as `requirements.txt` or `pyproject.toml`
- automated tests for validation, IRSA parsing, cache behavior, and FITS conversion
- production WSGI serving, for example Gunicorn or another supported server
- structured logging and request metrics
- a shared store for observation metadata when running multiple workers
- authentication and rate limiting if the API is exposed publicly

## License

No license is currently declared for this repository. Add a license file if you intend for others to use, modify, or redistribute the project.
