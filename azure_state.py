from __future__ import annotations

import logging
import os
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

log = logging.getLogger("azure-state")

STATE_FILES = (
    "state.json",
    "html_report_state.json",
    "dashboard_state.json",
)


def _container_client():
    connection_string = os.environ.get("AzureWebJobsStorage", "").strip()
    if not connection_string:
        raise RuntimeError("Missing AzureWebJobsStorage app setting")

    service = BlobServiceClient.from_connection_string(connection_string)
    container_name = os.environ.get("AZURE_STATE_CONTAINER", "bot-state").strip() or "bot-state"
    container = service.get_container_client(container_name)
    try:
        container.create_container()
    except ResourceExistsError:
        pass
    return container


def pull_state(workdir: Path) -> None:
    """Restore the persistent state files before the scheduled run."""
    container = _container_client()
    for name in STATE_FILES:
        try:
            payload = container.download_blob(name).readall()
        except ResourceNotFoundError:
            log.info("No Azure state blob yet for %s; using packaged seed if present", name)
            continue
        target = workdir / name
        target.write_bytes(payload)
        log.info("Restored %s from Azure Blob Storage (%d bytes)", name, len(payload))


def push_state(workdir: Path) -> None:
    """Persist state after every run so Azure Functions can be stateless."""
    container = _container_client()
    for name in STATE_FILES:
        source = workdir / name
        if not source.exists():
            continue
        payload = source.read_bytes()
        container.upload_blob(name=name, data=payload, overwrite=True)
        log.info("Saved %s to Azure Blob Storage (%d bytes)", name, len(payload))
