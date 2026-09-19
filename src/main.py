"""Main entry point for the CSM Dashboard application."""

import logging

import typer

from .cli.commands import app as cli_app

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Create main app that includes all CLI commands
app = typer.Typer(
    name="csm-dashboard",
    help="Lido CSM Operator Dashboard - Track your validator earnings",
)

# Add all CLI commands from the commands module
app.add_typer(cli_app, name="")


@app.command()
def serve(
    host: str | None = typer.Option(
        None, help="Host to bind to (env: HOST, default: 127.0.0.1)"
    ),
    port: int | None = typer.Option(
        None, help="Port to bind to (env: PORT, default: 8080)"
    ),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development"),
):
    """Start the web dashboard server."""
    import uvicorn

    from .core.config import resolve_bind
    from .web.app import create_app

    logger = logging.getLogger(__name__)
    effective_host, effective_port = resolve_bind(host, port)
    logger.info(f"Starting CSM Dashboard server on {effective_host}:{effective_port}")

    web_app = create_app()
    uvicorn.run(
        web_app if not reload else "src.web.app:create_app",
        host=effective_host,
        port=effective_port,
        reload=reload,
        factory=reload,
        log_level="info",
    )


if __name__ == "__main__":
    app()
