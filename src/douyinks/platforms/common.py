import asyncio
import re
from pathlib import Path

import httpx


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\n\r]', "_", name).strip()
    name = re.sub(r"_+", "_", name)
    return (name[:max_len] if len(name) > max_len else name) or "unknown"


async def download_single(url: str, output_path: Path, referer: str) -> bool:
    headers = {"User-Agent": USER_AGENT, "Referer": referer}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    return False
                with open(output_path, "wb") as file:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        file.write(chunk)
        return True
    except Exception:
        if output_path.exists():
            output_path.unlink()
        return False


async def pause_between_items(index: int, total: int, delay: float) -> None:
    if index < total and delay > 0:
        await asyncio.sleep(delay)
