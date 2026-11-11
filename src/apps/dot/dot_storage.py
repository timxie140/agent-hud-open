"""No plaintext fallback: Windows DPAPI or macOS login Keychain."""
import base64
import hashlib
import sys


SERVICE = 'app.agenthud.dot'


def mac_keychain():
    # Uses native Security APIs through keyring; no security(1) argv secrets.
    from keyring.backends.macOS import Keyring
    return Keyring()


def mac_blob(value, decrypt, root):
    scope = hashlib.sha256(str(root).encode()).hexdigest()[:24]
    keychain = mac_keychain()
    if decrypt:
        account = value.decode('ascii')
        if not account.startswith('blob-' + scope + '-'):
            raise ValueError('Unknown protected blob')
        result = keychain.get_password(SERVICE, account)
        if result is None:
            raise ValueError('Protected blob unavailable')
        return base64.b64decode(result, validate=True)
    account = 'blob-' + scope + '-' + hashlib.sha256(value).hexdigest()
    keychain.set_password(SERVICE, account, base64.b64encode(value).decode())
    return account.encode('ascii')


def read_configuration(root, protect):
    if sys.platform == 'darwin':
        if not (root / 'configured').exists():
            return None
        account = 'connection-' + hashlib.sha256(str(root).encode()).hexdigest()
        return mac_keychain().get_password(SERVICE, account)
    path = root / 'connection.dpapi'
    return protect(path.read_bytes(), True) if path.exists() else None


def write_configuration(root, value, protect):
    root.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
        account = 'connection-' + hashlib.sha256(str(root).encode()).hexdigest()
        mac_keychain().set_password(SERVICE, account, value.decode())
        # This marker contains no credentials or connection parameters.
        (root / 'configured').touch()
    else:
        path = root / 'connection.dpapi'
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(protect(value))
        temporary.replace(path)
