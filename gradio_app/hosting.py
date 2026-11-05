"""Authenticated hosting on a private Tailscale interface."""
import base64
import binascii
from ipaddress import ip_address, ip_network
import json
from pathlib import Path
import secrets

from starlette.responses import PlainTextResponse


def hosting_settings(host, config_path=None):
    address = ip_address(host)
    if not address.is_loopback and address not in ip_network('100.64.0.0/10'):
        raise ValueError('Bind to loopback or this machine’s Tailscale IPv4 address.')
    if not config_path:
        if not address.is_loopback:
            raise ValueError('Tailscale hosting requires --auth-config with a username and password.')
        return None
    try:
        config = json.loads(Path(config_path).read_text(encoding='utf-8'))
        username, password = config['username'], config['password']
        if not isinstance(username, str) or not isinstance(password, str) or not username or not password or ':' in username:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('The private auth config must contain a nonempty username and password.') from exc
    return {'username': username, 'password': password}


class PrivateDemoAuth:
    """Protect the UI, mounted Gradio routes, MCP, uploads and result files alike."""
    def __init__(self, app, username, password):
        self.app = app
        self.username = username.encode('utf-8')
        self.password = password.encode('utf-8')

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        valid = False
        try:
            authorization = dict(scope.get('headers', [])).get(b'authorization', b'')
            scheme, _, encoded = authorization.partition(b' ')
            if scheme.lower() == b'basic':
                username, separator, password = base64.b64decode(encoded, validate=True).partition(b':')
                valid = (secrets.compare_digest(username, self.username)
                         & secrets.compare_digest(password, self.password)
                         & bool(separator))
        except (ValueError, binascii.Error):
            pass
        if valid:
            return await self.app(scope, receive, send)
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1008})
        response = PlainTextResponse('Sign in to Simulation Studio.', status_code=401,
                                    headers={'WWW-Authenticate': 'Basic realm="Simulation Studio", charset="UTF-8"',
                                             'Cache-Control': 'no-store'})
        await response(scope, receive, send)
