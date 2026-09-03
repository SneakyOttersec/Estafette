import datetime as dt
from unittest import TestCase
from unittest.mock import patch

from build_pdf import resolve_run_day


class ResolveRunDayTests(TestCase):
    @patch.dict("os.environ", {"PDF_RUN_DATE": "2026-08-24"})
    def test_historical_run_date_override(self) -> None:
        self.assertEqual(resolve_run_day(), dt.date(2026, 8, 24))

    @patch.dict("os.environ", {"PDF_RUN_DATE": "24-08-2026"})
    def test_invalid_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            resolve_run_day()
