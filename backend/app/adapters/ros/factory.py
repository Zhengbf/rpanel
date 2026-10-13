from __future__ import annotations
from app.db.models import RouterDevice
from app.security import decrypt_secret
from app.adapters.ros.rest_client import RestRouterOsClient
from app.adapters.ros.ssh_client import SshRouterOsClient
from app.adapters.ros.base import RouterOsClient


async def create_client_for_device(dev: RouterDevice) -> RouterOsClient:
    password = decrypt_secret(dev.encrypted_password)
    if dev.auth_method == "ssh":
        return SshRouterOsClient(host=dev.host, port=dev.port, username=dev.username,
                                 password=password, timeout=dev.timeout)
    return RestRouterOsClient(host=dev.host, port=dev.port, username=dev.username,
                              password=password, verify_tls=dev.verify_tls, timeout=dev.timeout)
