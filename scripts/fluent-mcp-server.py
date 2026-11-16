"""Start the official PyFluent MCP server, matching the Mechanical integration.

On Windows, preload PyFluent/NumPy on the main thread: a first NumPy import in
the server's discovery worker thread can stall native DLL initialization.
No Fluent session is launched by importing PyFluent or starting this server.
"""


def main():
    import ansys.fluent.core  # noqa: F401 - main-thread native-library initialization
    from ansys.fluent.mcp.server import launcher
    launcher()


if __name__ == '__main__':
    main()
