"""Write examples only; never modify the user's actual client configuration."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
command = str(Path(sys.executable).resolve())
config = {"mcpServers": {"inklab": {
    "command": command,
    "args": [str(root / "scripts/run_mcp.py")],
    "env": {"PYTHONUTF8": "1"},
}}}
(root / "mcp-config.example.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
toml = ("[mcp_servers.inklab]\n" +
        f"command = {json.dumps(command)}\n" +
        f"args = [{json.dumps(str(root / 'scripts/run_mcp.py'))}]\n" +
        "startup_timeout_sec = 60\ntool_timeout_sec = 180\n\n[mcp_servers.inklab.env]\nPYTHONUTF8 = \"1\"\n")
(root / "codex-mcp.example.toml").write_text(toml, encoding="utf-8")
print("Wrote mcp-config.example.json and codex-mcp.example.toml")
