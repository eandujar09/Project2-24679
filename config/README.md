# Configuration examples

Copy `local.example.json` to repository-root `.env.local.json`, and `opencode-login.example.json` to `.env.opencode.json`. Fill in your actual connection locally. Both destination files are Git-ignored. The example values are placeholders, not working credentials.

Omit Fluent settings when only Mechanical is configured. Additional optional settings:

| Key | Value |
| --- | --- |
| `OPENCODE_CONFIG` | Absolute path to the private login JSON, if not in the default location |
| `STEP_GRADIO_DATA` | Absolute workspace-data location; keep outside Git |
| `FLUENT_MCP_PYTHON` | Isolated official MCP interpreter |
| `FLUENT_MCP_API_OBJECTS_PATH` | Optional worker-compatible API catalog JSON |
| `FLUENT_POST_PYTHON` | Isolated native-post interpreter |
| `FLUENT_POST_SERVER` | Absolute path to `integrations/fluent_post/server.py` |

On a Mac, MCP/post interpreters must be executable on that Mac if configured for local Studio; a remote Windows path cannot be launched as a local subprocess. The hosted Windows deployment uses Windows interpreters for those optional integrations. Core remote simulation uses the authenticated transport and remote worker paths.
