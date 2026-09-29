# SPHEREx Backend API

A Flask backend for discovering SPHEREx observations and retrieving image products from the NASA/IPAC Infrared Science Archive (IRSA).

The service supports coordinate-based observation searches, FITS cutouts, PNG previews generated from FITS data, CDS SPHEREx HiPS sky-map assets, HiPS-generated sky previews, sky-tile metadata, health checks, caching, and structured JSON errors.

## Features

- Query SPHEREx observations by right ascension, declination, search radius, and spectral band.
- Query configured SPHEREx releases through the IRSA Simple Image Access 2 (SIA2) service.
- Query configured releases concurrently and combine their results.
- Normalize IRSA metadata into a consistent JSON representation.
- Generate PNG previews from FITS image data using percentile normalization and an inverse hyperbolic sine stretch.
- Return original FITS cutouts from the upstream archive.
- Proxy official CDS SPHEREx HiPS assets for all supported bands.
- Generate HiPS PNG previews through the CDS `hips2fits` service.
- Provide sky-tile metadata and observation results for sky-map clients.
- Cache observation metadata and generated previews using an in-memory TTL cache backed by SQLite.
- Automatically create the SQLite database directory, database, and cache table in a new environment.
- Support cross-origin requests for frontend clients through Flask-CORS.
- Return structured JSON errors for invalid input, unavailable observations, upstream failures, and timeouts.

## API overview

The application runs on port `5000` by default and registers its main blueprint under `/api/spherex`.

### `GET /`

Returns a machine-readable service overview, including the available core endpoints, configured releases, and the upstream IRSA SIA URL.

```bash
curl http://localhost:5000/
```

### `GET /health`
### `GET /api/health`

Returns a simple process health response:

```json
{
  "status": "ok"
}
```

Example:

```bash
curl http://localhost:5000/health
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

Supported bands:

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

Returned records may include coordinates, angular distance, coverage information, observation dates, Modified Julian Dates, wavelength information, spectral resolution, release metadata, exposure details, detector dimensions, target information, quality and provenance metadata, and generated frontend URLs.

### `GET /api/spherex/image/<obs_id>`

Fetches a FITS cutout from IRSA, converts it to a PNG preview, and returns the image with `Content-Type: image/png`.

#### Query parameters

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `product` | Recommended | — | Product identifier returned by the observations endpoint. |
| `ra` | Yes | — | Right ascension in degrees. |
| `dec` | Yes | — | Declination in degrees. |
| `size` | No | `0.5` | Cutout size in degrees. Must be between `0.01` and `0.5`. |

The observation metadata must have been loaded through `/observations` first because the product lookup is maintained in process memory.

```bash
curl -o preview.png \
  "http://localhost:5000/api/spherex/image/OBSERVATION_ID?product=PRODUCT_ID&ra=180&dec=0&size=0.1"
```

### `GET /api/spherex/cutout`

Returns the original FITS cutout from IRSA with `Content-Type: application/fits`.

#### Query parameters

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `product` | Yes | — | Product identifier returned by the observations endpoint. |
| `ra` | Yes | — | Right ascension in degrees. |
| `dec` | Yes | — | Declination in degrees. |
| `size` | No | `0.5` | Cutout size in degrees. Must be between `0.01` and `0.5`. |

```bash
curl -o cutout.fits \
  "http://localhost:5000/api/spherex/cutout?product=PRODUCT_ID&ra=180&dec=0&size=0.1"
```

### `GET /api/spherex/sky/preview`

Generates a PNG sky preview using the CDS SPHEREx HiPS `hips2fits` service.

#### Query parameters

| Parameter | Required | Default | Description |
| --- | --- | --- | --- |
| `band` | No | `D2` | `D1` through `D6`, or `SPHEREx-D1` through `SPHEREx-D6`. |
| `ra` | Yes | — | Right ascension in degrees, from `0` through `360`. |
| `dec` | Yes | — | Declination in degrees, from `-90` through `90`. |
| `fov` | Yes | — | Field of view in degrees, from `0.01` through `0.5`. |
| `width` | No | `512` | Output width in pixels, from `128` through `1024`. |
| `height` | No | `512` | Output height in pixels, from `128` through `1024`. |

Example:

```bash
curl -o sky-preview.png \
  "http://localhost:5000/api/spherex/sky/preview?band=D6&ra=180&dec=0&fov=0.1&width=512&height=512"
```

The endpoint returns `image/png` and includes cache and data-source headers.

### `GET /api/spherex/sky/hips/<band>/`
### `GET /api/spherex/sky/hips/<band>/<asset>`

Proxies official CDS SPHEREx HiPS assets. Supported bands are `D1` through `D6`, and the route accepts both a trailing slash and a specific asset path.

Supported asset paths include:

```text
properties
Moc.fits
Norder<number>/Allsky.png
Norder<number>/Allsky.jpg
Norder<number>/Allsky.fits
Norder<number>/Dir<number>/Npix<number>.png
Norder<number>/Dir<number>/Npix<number>.jpg
Norder<number>/Dir<number>/Npix<number>.fits
```

Examples:

```bash
curl http://localhost:5000/api/spherex/sky/hips/D6/properties
curl -o Moc.fits http://localhost:5000/api/spherex/sky/hips/D6/Moc.fits
curl -o allsky.png http://localhost:5000/api/spherex/sky/hips/D6/Norder3/Allsky.png
```

The proxy validates asset paths before requesting the upstream service and rejects path traversal attempts. Response content types are taken from the upstream response when available, with fallbacks of `text/plain` for `properties`, `application/fits` for FITS assets, and `image/png` for image assets.

### `GET /api/spherex/sky/tiles/<z>/<x>/<y>`

Returns metadata for an equirectangular sky tile.

- `z` must be between `0` and `20`.
- `y` must be within the valid tile range for the zoom level.
- `x` wraps horizontally across right ascension.
- Tiles below zoom level `6` return coordinate-overview metadata without querying IRSA.
- Tiles at zoom level `6` and above query the relevant sky region and return matching observations.

The optional `band` query parameter accepts `D1` through `D6`, `SPHEREx-D1` through `SPHEREx-D6`, or `all`.

Example:

```bash
curl "http://localhost:5000/api/spherex/sky/tiles/6/32/20?band=D6"
```

## Observation response URLs

Observation records expose URLs for related products when a usable product identifier is available:

- `image_url` — generated PNG preview from the observation FITS cutout.
- `cutout_url` — original FITS cutout.
- `hips_preview_url` — CDS HiPS PNG preview for the observation position and band.

## Not currently implemented

### `POST /api/spherex/detect-moving-objects`

Returns HTTP `501` because the backend does not infer object classifications or motion from image metadata.

```json
{
  "error": "MOVING_OBJECT_ANALYSIS_UNAVAILABLE",
  "message": "This API does not infer object classifications or motion from image metadata. Use repeated observations for human or validated downstream analysis."
}
```

### `GET /api/spherex/search`

Returns HTTP `501` because target-name search is not provided by the current SIA metadata integration. Search by sky coordinates instead.

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
| `400` | `INVALID_CUTOUT_SIZE` | The cutout or preview field of view is outside `0.01–0.5` degrees. |
| `400` | `INVALID_DIMENSION` | HiPS preview width or height is not an integer from `128` through `1024`. |
| `400` | `INVALID_HIPS_ASSET` | The requested HiPS asset path is not allowed. |
| `400` | `INVALID_TILE` | The requested sky tile coordinates are invalid. |
| `404` | `OBSERVATION_NOT_FOUND` | The product or observation is not present in the server's metadata cache. |
| `501` | `SEARCH_UNAVAILABLE` | Target-name search is not implemented. |
| `501` | `MOVING_OBJECT_ANALYSIS_UNAVAILABLE` | Moving-object analysis is not implemented. |
| `502` | `IRSA_UNAVAILABLE` | No configured IRSA release returned usable metadata. |
| `502` | `UPSTREAM_ERROR` | An upstream service returned an unsuccessful response or another request error occurred. |
| `504` | `UPSTREAM_TIMEOUT` | An upstream request exceeded the configured timeout. |

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
          +--> HiPS proxy and sky previews
          |       |
          |       +--> CDS SPHEREx HiPS / hips2fits
          |
          +--> FITS-to-PNG conversion (spherex/fits.py)
          |
          +--> TTL caches (spherex/cache.py + SQLite)
```

### Main modules

- `main.py` — creates the Flask application, enables CORS, loads environment variables, registers the blueprint, exposes the service overview, stats, and health endpoints, and starts the development server.
- `spherex/routes.py` — defines HTTP routes, validates request parameters, manages observation lookup, serves FITS and PNG products, proxies HiPS assets, generates sky previews, creates sky-tile metadata, and formats errors.
- `spherex/irsa.py` — communicates with IRSA SIA2, parses responses, normalizes observation metadata, applies coordinate and band filtering, and creates frontend-facing URLs.
- `spherex/fits.py` — reads FITS image data and converts it to PNG previews.
- `spherex/cache.py` — implements an in-memory TTL/LRU-style cache with SQLite persistence. It creates the database directory, SQLite database, and cache table automatically when needed.

## Data sources

The backend uses these external services:

- NASA/IPAC IRSA SIA2: `https://irsa.ipac.caltech.edu/SIA`
- CDS SPHEREx HiPS assets: `https://alasky.cds.unistra.fr/SPHEREx`
- CDS HiPS image service: `https://alasky.cds.unistra.fr/hips-image-services/hips2fits`

Observation queries are performed on demand rather than against a local observation catalog. Results are requested from configured IRSA releases, normalized, filtered, and cached.

## Requirements

The project includes a pinned `requirements.txt` file. Install dependencies with:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
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
   python -m pip install -r requirements.txt
   ```

4. Start the API:

   ```bash
   python main.py
   ```

5. Verify that it is running:

   ```bash
   curl http://localhost:5000/health
   curl http://localhost:5000/api/spherex/stats
   ```

The server binds to `0.0.0.0` and uses port `5000` by default.

## Automatic database initialization

The cache uses SQLite at:

```text
spherex/db/cache.db
```

On startup, the backend automatically:

1. Creates the `spherex/db` directory if it does not exist.
2. Creates `cache.db` if it does not exist.
3. Creates the `cache` table if it does not exist.
4. Commits the schema transaction.

No manual database migration or initialization command is required for a new environment.

The generated database is ignored by Git through the `*.db` rule.

The SQLite database stores cache data only. Observation records used by `/image/<obs_id>` and `/cutout` remain in process memory. In a multi-worker deployment, each worker has its own observation map, so use sticky routing or a shared metadata store if requests can move between workers.

## Configuration

Configuration is read from environment variables. A `.env` file is supported through `python-dotenv`.

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `5000` | Local HTTP port used by `main.py`. |
| `FLASK_DEBUG` | `false` | Enables Flask debug mode when set to `true`. |
| `SPHEREX_SIA_URL` | `https://irsa.ipac.caltech.edu/SIA` | Upstream IRSA SIA2 endpoint. |
| `SPHEREX_HIPS_BASE_URL` | `https://alasky.cds.unistra.fr/SPHEREx` | Base URL for proxied CDS SPHEREx HiPS assets. |
| `SPHEREX_HIPS2FITS_URL` | `https://alasky.cds.unistra.fr/hips-image-services/hips2fits` | CDS HiPS image-generation endpoint. |
| `SPHEREX_RELEASES` | `spherex_qr3,spherex_qr2` | Comma-separated list of IRSA collections to query. |
| `SPHEREX_UPSTREAM_TIMEOUT_MS` | `60000` | Timeout for upstream requests in milliseconds. |
| `SPHEREX_QUERY_CACHE_TTL_MS` | `600000` | Observation metadata cache lifetime in milliseconds. |
| `SPHEREX_IMAGE_CACHE_TTL_MS` | `1800000` | PNG preview cache lifetime in milliseconds. |
| `SPHEREX_IMAGE_CACHE_MAX_BYTES` | `67108864` | Maximum in-memory preview cache size in bytes. |
| `SPHEREX_PREVIEW_SIZE_DEGREES` | `0.5` | Default preview and cutout size in degrees. |
| `NODE_ENV` | — | When set to `development`, internal error details may be included in API error responses. |

Example `.env` file:

```dotenv
PORT=5000
FLASK_DEBUG=false
SPHEREX_SIA_URL=https://irsa.ipac.caltech.edu/SIA
SPHEREX_HIPS_BASE_URL=https://alasky.cds.unistra.fr/SPHEREx
SPHEREX_HIPS2FITS_URL=https://alasky.cds.unistra.fr/hips-image-services/hips2fits
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
- The SQLite cache is initialized automatically on application startup.
- Full FITS files are fetched from IRSA and are not stored permanently in the cache.
- Observation metadata used by `/image/<obs_id>` and `/cutout` is stored in process memory. A client should request observations before requesting a preview or FITS cutout.
- In a multi-worker deployment, each worker has its own in-memory observation map. Use sticky behavior, a shared metadata store, or an architectural change if requests can move between workers.
- IRSA and CDS are external dependencies. Availability, response time, rate limits, and returned metadata can affect API responses.
- Do not enable Flask debug mode in production.
- CORS is enabled for frontend clients. Restrict the allowed origins before deploying publicly if your security model requires it.

## Development

Run the application directly during development:

```bash
FLASK_DEBUG=true python main.py
```

Before deploying, consider adding:

- automated tests for validation, IRSA parsing, HiPS paths, cache behavior, and FITS conversion
- production WSGI serving, for example Gunicorn or another supported server
- structured logging and request metrics
- a shared store for observation metadata when running multiple workers
- authentication and rate limiting if the API is exposed publicly

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
