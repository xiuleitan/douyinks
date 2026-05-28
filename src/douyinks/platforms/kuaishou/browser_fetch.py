import json
from typing import Any

from ...browser import BrowserPage


class KuaishouAPIError(Exception):
    """Raised when the Kuaishou API returns an error."""


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
          'Accept': 'application/json',
          ...{extra_headers}
        }},
        {body_part}
      }});
      return res.json();
    }})()
    """
    result = await page.evaluate(js)
    if isinstance(result, dict):
        code = result.get("result")
        if isinstance(code, int) and code != 1:
            raise KuaishouAPIError(f"Kuaishou API error {code}: {result.get('error_msg', 'unknown error')}")
    return result
