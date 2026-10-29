import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inklab.mcp_server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
