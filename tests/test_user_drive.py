from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from estafette_service.drive import FOLDER_MIME, ensure_delivery_folder, upload_pdf


class UserDriveTests(TestCase):
    @patch("estafette_service.drive._drive")
    def test_reuses_the_recorded_delivery_folder(self, make_drive) -> None:
        service = make_drive.return_value
        service.files.return_value.get.return_value.execute.return_value = {
            "id": "folder-id",
            "mimeType": FOLDER_MIME,
            "trashed": False,
        }

        folder_id = ensure_delivery_folder(
            MagicMock(), name="Estafette", existing_folder_id="folder-id"
        )

        self.assertEqual(folder_id, "folder-id")
        service.files.return_value.create.assert_not_called()

    @patch("estafette_service.drive._drive")
    def test_creates_an_app_managed_folder_when_none_is_recorded(
        self, make_drive
    ) -> None:
        service = make_drive.return_value
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "new-folder-id"
        }

        folder_id = ensure_delivery_folder(MagicMock(), name="Estafette")

        self.assertEqual(folder_id, "new-folder-id")
        create = service.files.return_value.create
        body = create.call_args.kwargs["body"]
        self.assertEqual(body["name"], "Estafette")
        self.assertEqual(body["mimeType"], FOLDER_MIME)
        self.assertEqual(body["appProperties"]["estafette"], "delivery-folder")

    @patch("estafette_service.drive.MediaFileUpload")
    @patch("estafette_service.drive._drive")
    def test_same_pdf_name_is_updated_instead_of_duplicated(
        self, make_drive, media_upload
    ) -> None:
        service = make_drive.return_value
        service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "existing-file-id"}]
        }
        service.files.return_value.update.return_value.execute.return_value = {
            "id": "existing-file-id"
        }

        with TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "GENERAL_03_09_2026.pdf"
            pdf.write_bytes(b"%PDF-test")
            file_id = upload_pdf(MagicMock(), "folder-id", pdf)

        self.assertEqual(file_id, "existing-file-id")
        service.files.return_value.update.assert_called_once()
        service.files.return_value.create.assert_not_called()
        media_upload.assert_called_once()
