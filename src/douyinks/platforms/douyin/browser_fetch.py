import json
from typing import Any

from ...browser import BrowserPage


class DouyinAPIError(Exception):
    """Raised when the Douyin API returns a non-zero status_code."""


async def browser_fetch(
    page: BrowserPage,
    method: str,
    url: str,
    *,
    body: Any | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    extra_headers = json.dumps(headers or {})
    body_part = ""
    if body is not None:
        body_part = f"body: JSON.stringify({json.dumps(body)}),"

    js = f"""
    (async () => {{
      const res = await fetch({json.dumps(url)}, {{
        method: {json.dumps(method)},
        credentials: 'include',
        headers: {{
          'Content-Type': 'application/json',
          ...{extra_headers}
        }},
        {body_part}
      }});
      return res.json();
    }})()
    """
    result = await page.evaluate(js)
    if isinstance(result, dict) and "status_code" in result and result["status_code"] != 0:
        raise DouyinAPIError(f"Douyin API error {result['status_code']}: {result.get('status_msg', 'unknown error')}")
    return result
