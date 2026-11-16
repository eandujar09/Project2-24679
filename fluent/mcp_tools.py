"""Read-only Studio access to the official Fluent MCP server over stdio.

Simulation execution remains in the existing bounded worker. This adapter cannot
launch Fluent, connect to a solver, execute code, or mutate a solver session.
"""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TOOLS = frozenset({'find_api','get_help','validate_code'})


def call_mcp(tool, arguments):
    if tool not in TOOLS:
        raise ValueError('Studio exposes only Fluent MCP discovery, help and code validation.')
    python = os.environ.get('FLUENT_MCP_PYTHON','')
    if not python or not Path(python).is_file():
        raise ValueError('Configure FLUENT_MCP_PYTHON with the isolated requirements-fluent-mcp.txt interpreter.')
    keep = {'SYSTEMROOT','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','HOME','APPDATA','LOCALAPPDATA'}
    env = {k:v for k,v in os.environ.items() if k.upper() in keep}
    env.update(PYTHONPATH=str(ROOT),PYTHONIOENCODING='utf-8')
    catalog=os.environ.get('FLUENT_MCP_API_OBJECTS_PATH')
    if catalog:
        if not Path(catalog).is_file():
            raise ValueError('The configured Fluent worker API catalog does not exist.')
        env['FLUIDS_MCP_API_OBJECTS_PATH']=catalog
    try:
        result = subprocess.run([python,'-m','fluent.mcp_tools'],
            input=json.dumps({'tool':tool,'arguments':arguments}),capture_output=True,
            text=True,encoding='utf-8',env=env,cwd=ROOT,timeout=90)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Fluent MCP inspection timed out; no simulation was submitted.') from exc
    if result.returncode:
        raise ValueError('Fluent MCP inspection failed; check the isolated server environment. No simulation was submitted.')
    if len(result.stdout)>500000:
        raise ValueError('Fluent MCP response is too large; narrow the query.')
    try:
        response = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError('Fluent MCP returned invalid JSON.') from exc
    if not isinstance(response,dict):
        raise ValueError('Fluent MCP returned an invalid tool response.')
    return {'server':'ansys-fluent','solverLaunched':False,'validationScope':'offline',
            'catalogSource':'configured-worker' if catalog else 'server-default',
            'response':response}


async def request(tool, arguments):
    if tool not in TOOLS:
        raise ValueError('Unsupported Fluent MCP inspection tool.')
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    # Exactly the official startup used by the native OpenCode registration.
    params = StdioServerParameters(command=sys.executable,args=[
        str(ROOT/'scripts/fluent-mcp-server.py'),'--transport','stdio'],env=dict(os.environ))
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=60)) as session:
            await session.initialize()
            available = await session.list_tools()
            if tool not in {item.name for item in available.tools}:
                raise ValueError('The installed Fluent MCP server does not expose the requested tool.')
            result = await session.call_tool(tool,arguments)
            return result.model_dump(mode='json',exclude_none=True)


if __name__=='__main__':
    payload=json.load(sys.stdin)
    print(json.dumps(asyncio.run(request(payload['tool'],payload['arguments'])),allow_nan=False))
