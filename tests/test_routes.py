import unittest
from unittest.mock import patch

from main import app


class StubResponse:
    def __init__(self, content=b"ok", headers=None):
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        return None


class RoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("spherex.routes.requests.get")
    def test_hips_asset_validation_and_fallback_types(self, mock_get):
        mock_get.return_value = StubResponse()

        test_cases = [
            ("properties", "text/plain"),
            ("Moc.fits", "application/fits"),
            ("Norder3/Allsky.png", "image/png"),
            ("Norder3/Dir0/Npix1.fits", "application/fits"),
        ]

        for asset, expected_content_type in test_cases:
            with self.subTest(asset=asset):
                response = self.client.get(
                    f"/api/spherex/sky/hips/D2/{asset}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers["Content-Type"],
                    expected_content_type,
                )
                upstream_url = mock_get.call_args.args[0]
                self.assertTrue(upstream_url.endswith(f"/D2/{asset}"))

    @patch("spherex.routes.requests.get")
    def test_hips_asset_rejects_unrelated_or_traversal_paths(self, mock_get):
        mock_get.return_value = StubResponse()

        invalid_assets = [
            "Norder3/Dir0/Npix1.gif",
            "../properties",
            "Norder3/Dir0/../../secret",
        ]

        for asset in invalid_assets:
            with self.subTest(asset=asset):
                response = self.client.get(
                    f"/api/spherex/sky/hips/D2/{asset}"
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error"],
                    "INVALID_HIPS_ASSET",
                )

    @patch("spherex.routes.requests.get")
    def test_sky_preview_handles_band_alias_and_dimension_errors(self, mock_get):
        mock_get.return_value = StubResponse(
            content=b"png-bytes",
            headers={"Content-Type": "image/png"},
        )

        valid = self.client.get(
            "/api/spherex/sky/preview"
            "?band=SPHEREx-D3&ra=10&dec=5&fov=0.2&width=512&height=512"
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(
            mock_get.call_args.kwargs["params"]["hips"],
            "CDS/P/SPHEREx/QR2/D3",
        )

        invalid_type = self.client.get(
            "/api/spherex/sky/preview"
            "?band=D3&ra=10&dec=5&fov=0.2&width=abc&height=512"
        )
        self.assertEqual(invalid_type.status_code, 400)
        self.assertEqual(
            invalid_type.get_json()["error"],
            "INVALID_DIMENSION",
        )

        invalid_range = self.client.get(
            "/api/spherex/sky/preview"
            "?band=D3&ra=10&dec=5&fov=0.2&width=64&height=512"
        )
        self.assertEqual(invalid_range.status_code, 400)
        self.assertEqual(
            invalid_range.get_json()["error"],
            "INVALID_DIMENSION",
        )

    def test_sky_tiles_accepts_short_band_alias(self):
        response = self.client.get(
            "/api/spherex/sky/tiles/1/0/0?band=D2"
        )
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
