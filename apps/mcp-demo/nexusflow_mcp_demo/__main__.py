import json
import os

import uvicorn

from nexusflow_mcp_demo.server import create_app


def main():
    host = os.environ.get("MCP_DEMO_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_DEMO_PORT", "8765"))
    default_hosts = [f"localhost:{port}", f"127.0.0.1:{port}"]
    allowed_hosts = json.loads(os.environ.get("MCP_DEMO_ALLOWED_HOSTS", json.dumps(default_hosts)))
    uvicorn.run(create_app(allowed_hosts), host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
