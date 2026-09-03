"""Cloud Run entry point for the Estafette registration service."""

from estafette_service.web import create_app

app = create_app()
