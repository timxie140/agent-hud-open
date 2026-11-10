"""Windows sidecar lifecycle and current-user encrypted configuration."""
import argparse
from contextlib import closing
import ctypes
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time

import hud_dot as hud
from dot_storage import read_configuration, write_configuration


def config_path():
    return hud.ROOT / 'connection.dpapi'


def load_config():
    try:
        raw = read_configuration(hud.ROOT, hud.protect)
        return json.loads(raw) if raw else {'enabled': False, 'proxy': suggested_proxy()}
    except Exception:
        raise hud.Rejected('Dot connection secure storage is unavailable to this user')


def suggested_proxy():
    candidates = [os.environ.get('HTTPS_PROXY', ''), os.environ.get('HTTP_PROXY', '')]
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
                if winreg.QueryValueEx(key, 'ProxyEnable')[0]:
                    value = winreg.QueryValueEx(key, 'ProxyServer')[0]
                    candidates.extend(part.partition('=')[2] if '=' in part else part for part in value.split(';'))
        except OSError:
            pass
    elif sys.platform == 'darwin':
        try:
            output = subprocess.run(['/usr/sbin/scutil', '--proxy'], capture_output=True,
                                    text=True, timeout=2).stdout
            fields = dict(re.findall(r'^\s*(HTTPS?(?:Enable|Proxy|Port))\s*:\s*([^\r\n]+)', output, re.M))
            for kind in ('HTTPS', 'HTTP'):
                if fields.get(kind + 'Enable') == '1':
                    host = fields.get(kind + 'Proxy', '').strip()
                    if ':' in host and not host.startswith('['):
                        host = '[' + host + ']'
                    candidates.append('http://' + host + ':' + fields.get(kind + 'Port', ''))
        except (OSError, subprocess.TimeoutExpired):
            pass
    for candidate in candidates:
        if candidate:
            value = candidate if '://' in candidate else 'http://' + candidate
            try:
                hud.loopback_proxy(value)
                return value
            except hud.Rejected:
                pass
    return ''


def save_config(arguments):
    previous = load_config()
    enabled = arguments.get('enabled') is True
    tunnel = arguments.get('tunnelId', previous.get('tunnelId', ''))
    key = arguments.get('runtimeApiKey') or previous.get('runtimeApiKey', '')
    proxy = arguments.get('proxy', previous.get('proxy', ''))
    if not isinstance(tunnel, str) or (tunnel and not re.fullmatch(r'tunnel_[A-Za-z0-9_-]+', tunnel)):
        raise hud.Rejected('Invalid tunnel ID')
    if not isinstance(key, str) or len(key) > 4096:
        raise hud.Rejected('Invalid runtime credential')
    if enabled and (not tunnel or not key):
        raise hud.Rejected('Tunnel ID and runtime API key are required')
    if proxy:
        hud.loopback_proxy(proxy)
    value = {'enabled': enabled, 'tunnelId': tunnel, 'runtimeApiKey': key,
             'proxy': proxy, 'localToken': previous.get('localToken') or secrets.token_urlsafe(32),
             'dotToken': previous.get('dotToken') or secrets.token_urlsafe(32),
             'instance': previous.get('instance') or secrets.token_hex(16)}
    write_configuration(hud.ROOT, hud.canonical(value).encode(), hud.protect)
    # A non-secret hint avoids spawning/decrypting anything for disabled clients.
    # Every operation still verifies the protected configuration itself.
    (hud.ROOT / 'enabled').write_text('true' if enabled else 'false')
    return value


def rpc(config, method, params):
    connection = http.client.HTTPConnection('127.0.0.1', 8787, timeout=15)
    try:
        connection.request('POST', '/mcp', hud.canonical({
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode(),
            {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['localToken']})
        response = connection.getresponse()
        if response.status != 200:
            raise hud.Rejected('Dot listener is not the configured authenticated instance')
        result = json.load(response)
        if 'error' in result:
            raise hud.Rejected(result['error'].get('message', 'Dot operation refused'))
        return result['result']
    finally:
        connection.close()


def status(config):
    result = {'enabled': config.get('enabled', False), 'tunnelId': config.get('tunnelId', ''),
              'hasRuntimeApiKey': bool(config.get('runtimeApiKey')), 'proxy': config.get('proxy', ''),
              'running': False, 'subscribed': False, 'ready': False, 'notice': None}
    if not result['enabled']:
        return result
    try:
        value = rpc(config, 'tools/call', {'name': 'hud_dot_status', 'arguments': {}})
        snapshot = json.loads(value['content'][0]['text'])
        result.update(running=True, subscribed=snapshot.get('subscribed', False),
                      adapterVersion=snapshot.get('adapterVersion'), expires=snapshot.get('expires'),
                      confirmedReplies=snapshot.get('confirmedReplies', 0),
                      lastConfirmedReplyId=snapshot.get('lastConfirmedReplyId'),
                      lastConfirmedAt=snapshot.get('lastConfirmedAt'))
        from urllib.parse import urlsplit
        health = hud.ROOT / 'tunnel-health.url'
        if health.exists():
            endpoint = urlsplit(health.read_text().strip())
            if (endpoint.scheme == 'http' and endpoint.hostname == '127.0.0.1' and endpoint.port
                    and not endpoint.username and not endpoint.password and not endpoint.query
                    and not endpoint.fragment and endpoint.path in ('', '/')):
                connection = http.client.HTTPConnection('127.0.0.1', endpoint.port, timeout=2)
                try:
                    connection.request('GET', '/readyz')
                    response = connection.getresponse()
                    result['ready'] = response.status == 200
                    response.read(100)
                    if result['ready']:
                        connection.request('GET', '/health?details=true')
                        response = connection.getresponse()
                        details = json.load(response)
                        plane = details.get('components', {}).get('control-plane', {})
                        result['ready'] = plane.get('status') == 'ok' and plane.get('state') == 'polling'
                finally:
                    connection.close()
    except Exception:
        result['notice'] = 'Dot runtime is starting or unavailable; no message was retried'
        state = hud.ROOT / 'runtime-state.json'
        if state.exists() and json.loads(state.read_text()).get('notice') == 'port_conflict':
            result['notice'] = 'Port 8787 is occupied. Stop the previous temporary Dot listener and tunnel before enabling the packaged runtime.'
    return result


def control(request):
    config = load_config()
    action, arguments = request.get('action'), request.get('arguments', {})
    if action == 'configure':
        config = save_config(arguments)
        return status(config)
    if action == 'status':
        return status(config)
    if not config.get('enabled'):
        raise hud.Rejected('Dot is disabled in HUD settings')
    if action in {'pending', 'claim', 'complete', 'confirm'}:
        return rpc(config, 'hud/internal/' + action, arguments)
    if action in {'send', 'get'}:
        source = arguments.get('source')
        if not isinstance(source, str) or not source.startswith('codex:'):
            raise hud.Rejected('Actual Codex caller identity required')
        meta = {'threadId': source[6:]}
        tool_args = {'id': arguments.get('id')}
        if action == 'send':
            tool_args['text'] = arguments.get('text')
        value = rpc(config, 'tools/call', {'name': 'hud_send_to_dot' if action == 'send' else 'hud_get_message',
                    'arguments': tool_args, '_meta': meta})
        return json.loads(value['content'][0]['text'])
    raise hud.Rejected('Unknown Dot control operation')


def _drain(stream, sensitive=()):
    # Bounded/redacted transport log. Never enable unsafe HTTP logging.
    for raw in iter(stream.readline, b''):
        text = raw.decode('utf-8', 'replace')
        for secret in sensitive:
            if secret:
                text = text.replace(secret, '[REDACTED]')
        text = re.sub(r'(?i)Bearer\s+\S+', '[REDACTED]', text)
        text = re.sub(r'\b(?:sk-|whsec_)[A-Za-z0-9_-]+', '[REDACTED]', text)
        text = re.sub(r'(?i)((?:api[_-]?key|secret|token|authorization)\s*[=:]\s*)[^\r\n]+',
                      r'\1[REDACTED]', text)
        path = hud.ROOT / 'transport.log'
        try:
            if not path.exists() or path.stat().st_size < 1024 * 1024:
                with path.open('a', encoding='utf-8') as output:
                    output.write(text[:3000])
        except OSError:
            pass  # Continue draining so a log failure cannot stall the tunnel.


def _stop(children):
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def supervise(hud_pid):
    if sys.platform == 'darwin':
        return supervise_macos(hud_pid)
    if sys.platform != 'win32':
        raise hud.Rejected('Packaged Dot lifecycle requires macOS or Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\AgentHudDot-' + str(hud.ROOT).replace('\\', '_'))
    if not mutex or ctypes.get_last_error() == 183:
        if mutex:
            kernel.CloseHandle(mutex)
        return
    # A held process handle identifies this exact HUD process across PID reuse.
    parent = kernel.OpenProcess(0x100000, False, hud_pid)
    if not parent:
        kernel.CloseHandle(mutex)
        raise hud.Rejected('Cannot watch owning HUD process')
    try:
        run_owned(lambda: kernel.WaitForSingleObject(parent, 1000) == 258)
    finally:
        kernel.CloseHandle(parent)
        kernel.CloseHandle(mutex)


def supervise_macos(hud_pid):
    import fcntl
    import select
    with (hud.ROOT / 'supervisor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with closing(select.kqueue()) as watcher:
            try:
                watcher.control([select.kevent(hud_pid, filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                    fflags=select.KQ_NOTE_EXIT)], 0, 0)
            except ProcessLookupError:
                return
            # Kernel process-exit registration, not PID polling or per-second ps.
            run_owned(lambda: not watcher.control(None, 1, 1))


def port_available():
    with socket.socket() as probe:
        if sys.platform == 'win32':
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', 8787))
            return True
        except OSError:
            return False


def run_owned(alive):
    children, current = [], None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        while alive():
            config = load_config()
            fingerprint = hud.canonical(config)
            if fingerprint != current or (children and any(c.poll() is not None for c in children)):
                _stop(children)
                children = []
                current = fingerprint
                if not config.get('enabled'):
                    continue
                if not port_available():
                    (hud.ROOT / 'runtime-state.json').write_text('{"notice":"port_conflict"}')
                    current = None
                    time.sleep(4)
                    continue
                (hud.ROOT / 'runtime-state.json').write_text('{"notice":null}')
                env = {k: v for k, v in os.environ.items() if not k.startswith('HUD_DOT_')}
                env.update(HUD_DOT_LOCAL_TOKEN=config['localToken'], HUD_DOT_DOT_TOKEN=config['dotToken'],
                           AGENTHUD_DOT_DATA=str(hud.ROOT), CONTROL_PLANE_API_KEY=config['runtimeApiKey'],
                           HUD_DOT_UPSTREAM_AUTH='Bearer ' + config['dotToken'])
                bundle = Path(sys.executable).parent
                listener = subprocess.Popen([sys.executable, '--listen'], env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=flags)
                children.append(listener)
                # No other listener is killed or adopted on a port conflict.
                time.sleep(1)
                if listener.poll() is not None:
                    time.sleep(4)
                    continue
                tunnel = bundle / ('tunnel-client.exe' if sys.platform == 'win32' else 'tunnel-client')
                child = subprocess.Popen([str(tunnel), 'run', '--control-plane.tunnel-id', config['tunnelId'],
                    '--control-plane.api-key', 'env:CONTROL_PLANE_API_KEY',
                    '--mcp.server-url', 'http://127.0.0.1:8787/mcp',
                    '--mcp.extra-headers', 'Authorization: env:HUD_DOT_UPSTREAM_AUTH',
                    '--mcp.discovery-extra-headers', 'Authorization: env:HUD_DOT_UPSTREAM_AUTH',
                    '--health.listen-addr', '127.0.0.1:0', '--health.url-file', str(hud.ROOT / 'tunnel-health.url'),
                    '--log.http-raw-unsafe=false'], env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, creationflags=flags)
                children.append(child)
                threading.Thread(target=_drain, args=(child.stdout,
                    (config['runtimeApiKey'], config['localToken'], config['dotToken'])), daemon=True).start()
    finally:
        _stop(children)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if sys.platform != 'win32':
        os.umask(0o077)
    hud.ROOT.mkdir(parents=True, exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--control-stdin', action='store_true')
    parser.add_argument('--listen', action='store_true')
    parser.add_argument('--supervise', type=int, metavar='HUD_PID')
    args = parser.parse_args()
    try:
        if args.control_stdin:
            raw = sys.stdin.buffer.read(hud.LIMIT + 1)
            if len(raw) > hud.LIMIT:
                raise hud.Rejected('Control request too large')
            result = control(json.loads(raw))
            print(hud.canonical({'result': result}))
        elif args.listen:
            from functools import partial
            config = load_config()
            hud.serve(hud.Adapter(hud.ROOT / 'state.sqlite', post=partial(hud.webhook_post, proxy=config.get('proxy') or None)),
                      8787, config['localToken'], config['dotToken'])
        elif args.supervise:
            supervise(args.supervise)
        else:
            parser.error('Choose --control-stdin, --listen or --supervise')
    except Exception as error:
        message = str(error) if isinstance(error, hud.Rejected) else 'Dot operation failed; no message retried'
        print(hud.canonical({'error': message}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
