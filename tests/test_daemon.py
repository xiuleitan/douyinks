import asyncio

import pytest
from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer

from douyinks.config import CUSTOM_HEADER
from douyinks.daemon import create_app


@pytest.mark.asyncio
async def test_shutdown_closes_connected_extension_promptly():
    async with ClientSession() as browser:
        server = TestServer(create_app())
        await server.start_server()
        extension = await browser.ws_connect(server.make_url("/ext"))
        try:
            await asyncio.wait_for(server.close(), timeout=2)
            message = await asyncio.wait_for(extension.receive(), timeout=2)
            assert message.type == WSMsgType.CLOSE
            assert message.data == 1001
        finally:
            await extension.close()
            await server.close()


@pytest.mark.asyncio
async def test_local_bridge_refuses_web_origins_and_requires_command_header():
    async with TestServer(create_app()) as server, ClientSession() as client:
        async with client.get(server.make_url("/ping"), headers={"Origin": "https://example.test"}) as response:
            assert response.status == 403
        async with client.post(server.make_url("/command"), json={"id": "test"}) as response:
            assert response.status == 403
        async with client.post(server.make_url("/command"), json=[], headers={CUSTOM_HEADER: "1"}) as response:
            assert response.status == 400
        async with client.post(server.make_url("/command"), json={"id": "test"},
                               headers={CUSTOM_HEADER: "1"}) as response:
            assert response.status == 503
