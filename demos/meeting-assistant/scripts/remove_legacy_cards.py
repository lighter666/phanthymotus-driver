"""Unregister only the retired meeting MCP from local Agent Core.

Stop the legacy compose service first, otherwise it registers itself again.
The meeting SQLite database is never opened or modified by this script.
"""

from __future__ import annotations

import argparse
import json
import ssl
import urllib.request


LEGACY_NAME = "Bumi Meeting Assistant"
LEGACY_URL = "http://localhost:15740/mcp"


def request_json(url: str, method: str = "GET") -> dict:
    context = ssl._create_unverified_context() if url.startswith("https://localhost:") else None
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=8, context=context) as response:
        return json.load(response)


def remove(core_url: str, apply: bool = False) -> list[dict]:
    endpoint = core_url.rstrip("/") + "/api/mcp"
    result = request_json(endpoint)
    services = result.get("data")
    if not isinstance(services, list):
        raise ValueError("Agent Core 未返回 MCP 列表，未执行删除")
    matches = [service for service in services
               if service.get("name") == LEGACY_NAME
               and service.get("url") == LEGACY_URL]
    for service in matches:
        print(f"旧会议卡片: {service.get('id')} {service.get('name')} {service.get('url')}")
        if apply:
            mcp_id = service.get("id")
            if not isinstance(mcp_id, str) or not mcp_id.startswith("mcp-"):
                raise ValueError("MCP ID 不符合预期，未执行删除")
            response = request_json(endpoint + "/" + mcp_id, method="DELETE")
            if response.get("code") != 200:
                raise RuntimeError(f"Agent Core 删除失败: {response}")
    if not matches:
        print("Agent Core 中没有旧会议 MCP 注册")
    elif apply:
        remaining = request_json(endpoint).get("data", [])
        if any(item.get("name") == LEGACY_NAME and item.get("url") == LEGACY_URL
               for item in remaining):
            raise RuntimeError("删除后仍发现旧会议 MCP；请检查服务是否还在运行")
        print(f"已注销 {len(matches)} 个旧会议 MCP；历史会议数据库未改动")
    else:
        print("预览完成；加 --apply 才会注销上面列出的旧会议 MCP")
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", default="https://localhost:15678")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    remove(args.core_url, args.apply)


if __name__ == "__main__":
    main()
