import base64
import functools
import secrets
import time
import traceback
import typing

import cryptography.hazmat.primitives.ciphers.aead
import flask
import requests
import werkzeug.datastructures
import werkzeug.exceptions
import werkzeug.wrappers

from lib import config
from . import backend_db

CODE_KEY = 'nay-code'

_KIND_GITHUB = b'github'
_KIND_CODE = b'code'

__CONFIG = config.load('auth')
__CHACHA = cryptography.hazmat.primitives.ciphers.aead.ChaCha20Poly1305(
    __CONFIG.take('key', base64.urlsafe_b64decode))
__CLIENT_ID = __CONFIG.take('github-client-id', str)
__CLIENT_SECRET = __CONFIG.take('github-client-secret', str)


def _github(token: str, path: str) -> typing.Any:
    """Issues a GET request to GitHub API and returns response as JSON.

    Args:
        token: GitHub authorisation token.
        path: API path.
    Returns:
        A JSON response sent by GitHub.
    """
    headers = {
        'accept': 'application/vnd.github.v3+json',
        'authorization': f'token {token}',
    }
    return requests.get(f'https://api.github.com{path}', headers=headers).json()


def _verify_organisations(token: str) -> bool:
    """Verifies that user authorised with given token is in required org.

    Args:
        token: GitHub authorisation token.
    Returns:
        Whether user authorised with given GitHub token is in one of the
        required organisations.
    """
    try:
        for org in _github(token, '/user/orgs'):
            if org['login'] in ('near', 'nearprotocol'):
                return True
    except Exception:
        traceback.print_exc()
    return False


def _encrypt(kind: bytes,
             plaintext: bytes,
             assoc_data: typing.Optional[str] = None,
             *,
             nonce: typing.Optional[bytes] = None) -> typing.Tuple[str, bytes]:
    """Encrypts given plain text.

    Encryption uses an AEAD scheme which means that the returned data is
    encrypted in addition to being signed by a secret key.

    Args:
        kind: Kind of plain text being encrypted.  The same kind must be given
            when decryption the cipher text.  This is used to prevent attacker
            from trying to swap one kind of properly message for a different
            one.
        plaintext: Data to encrypt.
        assoc_data: Associated data which will be authenticated and also
            included unencrypted in the ciphertext.  If present, the string must
            be urlsafe.
        nonce: If given, 12-byte nonce to use instead of generating a random
            one.
    Returns:
        (urlsafe_ciphertext, nonce) tuple where first element is an URL-safe
        tagged cipher text of the given data and the second is the nonce used
        when encrypting the data.  Note that the nonce is also included in the
        ciphertext so it's not usually necessary.  The first element also
        includes plain text associated data provided as `assoc_data` argument
        (if any).
    """
    if assoc_data:
        kind = assoc_data.encode('ascii') + b':' + kind
    if nonce:
        assert len(nonce) == 12
    else:
        nonce = secrets.token_bytes(12)
    ciphertext = __CHACHA.encrypt(nonce, plaintext, kind)
    urlsafe = base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')
    if assoc_data:
        urlsafe = assoc_data + ':' + urlsafe
    return urlsafe, nonce


def _decrypt(
        kind: bytes, ciphertext_str: str
) -> typing.Tuple[typing.Optional[str], bytes, bytes]:
    """Verifies and decrypts given data.

    It's safe to pass attacker-controlled data to this function.  Decryption
    uses an AEAD schema which means that the signature of the data is verified
    and any invalid data is rejected.

    Args:
        kind: Kind of cipher text being encrypted.  Must be the same as the one
            given when encrypting.  This is used to prevent attacker from trying
            to swap one kind of properly message for a different one.
        ciphertext_str: An URL-safe encoding of the tagged cipher text to decode
            as returned by _encrypt function.
    Returns:
        A (assoc_data, plaintext, nonce) tuple where first element is associated
        data included in the ciphertext (or None if it wasn't given), the second
        is the plain text data and third one nonce is the nonce used when
        encrypting (and then decrypting) the message.
    Raises:
        ValueError: if the value is in incorrect format or the signature is
            invalid.
    """
    assoc_data = None
    pos = ciphertext_str.rfind(':')
    if pos != -1:
        assoc_data = ciphertext_str[:pos]
        ciphertext_str = ciphertext_str[pos + 1:]
        kind = assoc_data.encode('ascii') + b':' + kind

    # The nonce (which we include in cipher text) is 12-byte long and the tag is
    # 16-byte long.  The entire cipher text is therefore at least 28 bytes.
    # Encoded with base64 that’s 40 bytes thus the ciphertext_str must be at
    # least that long for it to be valid.
    if len(ciphertext_str) < 40:
        raise ValueError('Invalid cipher text (too short)')
    try:
        ciphertext = base64.urlsafe_b64decode(ciphertext_str)
        nonce = ciphertext[:12]
        return assoc_data, __CHACHA.decrypt(nonce, ciphertext[12:], kind), nonce
    except Exception as ex:
        traceback.print_exc()
        raise ValueError() from ex


class AuthCode:

    def __init__(self,
                 login: str,
                 is_authorised: bool,
                 last_check: int,
                 token: str,
                 code: typing.Optional[str] = None) -> None:
        """Should not be called directly; use from_* methods instead."""
        self.__login = login
        self.__is_authorised = is_authorised
        self.__last_check = last_check
        self.__token = token
        self.__code = code or self.__format_code()

    login = property(lambda self: self.__login)
    code = property(lambda self: self.__code)

    @classmethod
    def from_request(cls, request: flask.Request) -> 'AuthCode':
        """Extracts authentication code from the request.

        First checks Authorization HTTP header and if that's not given
        a nay-code cookie.  Does not verify the code in any way.

        Args:
            request: The flask.Request the user has made.
        Returns:
            The AuthCode object with the authentication code's format verified
            and parsed.  Validity of the actual authorisation is not performed;
            only it's format.
        Raises:
            werkzeug.exceptions.HTTPException: if code is not given or is in
                invalid format.
        """
        code = request.headers.get('authorization')
        if code is None:
            code = request.cookies.get(CODE_KEY)
        elif code.startswith(CODE_KEY + ' '):
            code = code[len(CODE_KEY) + 1:]
        else:
            code = None
        if code is None:
            raise _unauthorised('Missing authorisation code')
        return cls.from_code(code)

    @classmethod
    def from_code(cls, code: str) -> 'AuthCode':
        """Construct AuthCode object from authorisation code.

        Args:
            code: Authorisation code sent by the user.
        Returns:
            The AuthCode object with the authentication code's format verified
            and parsed.  Validity of the actual authorisation is not performed;
            only it's format.
        Raises:
            werkzeug.exceptions.HTTPException: if code is in invalid format.
        """
        try:
            assoc_data, plaintext, _ = _decrypt(_KIND_CODE, code)
            assert assoc_data, 'Missing associated data'
        except (ValueError, AssertionError) as ex:
            raise _unauthorised('Invalid authorisation code') from ex
        _code: typing.Optional[str] = code
        # Code uses `["_"] <login>` associated data and encrypted four-byte
        # timestamp followed by the token.  The "_" in associated data indicates
        # that the user is not authorised.
        last_check = int.from_bytes(plaintext[:4], 'little')
        token = 'gho_' + plaintext[4:].decode('ascii')
        if assoc_data.startswith('_'):
            is_authorised = False
            login = assoc_data[1:]
        else:
            is_authorised = True
            login = assoc_data
        return cls(code=_code,
                   login=login,
                   is_authorised=is_authorised,
                   last_check=last_check,
                   token=token)

    @classmethod
    def for_user(cls, login: str, token: str) -> 'AuthCode':
        """Constructs AuthCode object for given user with given token.

        Args:
            login: User's GitHub login name.
            token: The GitHub auth token.
        Returns:
             The AuthCode object holding provided data and a computed
             authorisation code.
        Raises:
            ValueError: If GitHub token does not start with "gho_".
        """
        if not token.startswith('gho_'):
            raise ValueError(
                f'Expected GitHub token "{token}" to start with "gho_".')
        return cls(login=login,
                   is_authorised=_verify_organisations(token),
                   last_check=int(time.time()),
                   token=token)

    def verify(self) -> bool:
        """Checks whether user is authorised to access the site.

        The function may update self.code property if a verification had to be
        performed.

        Returns:
            Whether user is authorised.
        """
        now = int(time.time())
        if self.__last_check < now - 24 * 3600:
            self.__last_check = now
            self.__is_authorised = _verify_organisations(self.__token)
            self.__code = self.__format_code()
        return self.__is_authorised

    def __format_code(self) -> str:
        """Recomputes and returns auth code."""
        assoc_data = ('' if self.__is_authorised else '_') + self.__login
        data = self.__last_check.to_bytes(4, 'little')
        data += self.__token[4:].encode('ascii')
        return _encrypt(_KIND_CODE, data, assoc_data)[0]


def generate_redirect(mode: str) -> str:
    """Generates a redirect URL to the GitHub login page.

    Args:
        mode: Either 'web' or 'cli' depending whether the login request comes
            from web interface or CLI tools.
    Returns:
        An URL to GitHub OAuth authorisation page.
    """
    timestamp = int(time.time())
    enc_ts = -timestamp if mode == 'web' else timestamp
    nonce = enc_ts.to_bytes(4, 'little', signed=True) + secrets.token_bytes(8)
    cookie = int.from_bytes(nonce[4:], 'little', signed=True)
    state, _ = _encrypt(_KIND_GITHUB, b'', nonce=nonce)
    url = ('https://github.com/login/oauth/authorize'
           f'?scope=read:org&client_id={__CLIENT_ID}&state={state}')
    with backend_db.BackendDB() as server:
        server.add_auth_cookie(timestamp, cookie)
    return url


class AuthFailed(Exception):
    pass


def get_code(state: typing.Optional[str],
             code: typing.Optional[str]) -> typing.Tuple[AuthCode, bool]:
    """Converts GitHub's provided code into authentication token.

    In GitHub OAuth flow, user first goes to GitHub page to confirm
    authorisation and then GitHub redirects them back to us with a short-lived
    code which can be converted to long-lived authorisation token.  This
    function is handling this second step of the OAuth flow.

    Args:
        state: Value of the 'state' query parameter.
        code: Value of the 'code' query parameter; the short-lived GitHub code.
    Returns:
        A (code, is_web) tuple.  is_web specifies whether we are handling web
        interface or CLI authorisation flow.
    Raises:
        AuthFailed: If the state or code is invalid.
    """
    if not state or not code:
        raise AuthFailed('Missing state or code parameters')
    try:
        _, _, nonce = _decrypt(_KIND_GITHUB, state)
    except ValueError as ex:
        raise AuthFailed('Invalid request') from ex

    timestamp = int.from_bytes(nonce[:4], 'little', signed=True)
    is_web = timestamp < 0
    if is_web:
        timestamp = -timestamp
    cookie = int.from_bytes(nonce[4:], 'little', signed=True)

    if timestamp < time.time() - 600:
        print(f'Expired: {timestamp}')
        raise AuthFailed('Request expired')

    with backend_db.BackendDB() as server:
        if not server.verify_auth_cookie(timestamp, cookie):
            print('Nonce not in database')
            raise AuthFailed('Invalid request')

    params = {
        'client_id': __CLIENT_ID,
        'client_secret': __CLIENT_SECRET,
        'code': code
    }
    res = requests.post('https://github.com/login/oauth/access_token',
                        params=params,
                        headers={'accept': 'application/json'})
    if res.status_code != 200:
        print(f'GitHub replied with {res.status_code}:\n{res.text}')
        raise AuthFailed(f'GitHub rejected the request ({res.status_code})')

    try:
        token = res.json()['access_token']
        assert token.startswith('gho_')
        login = _github(token, '/user')['login']
    except Exception as ex:
        traceback.print_exc()
        raise AuthFailed('GitHub rejected the code') from ex

    return AuthCode.for_user(login=login, token=token), is_web


def add_cookie(response: werkzeug.wrappers.Response, code: str) -> None:
    """Adds a nay-code cookie to the response."""
    max_age = 90 * 7 * 24 * 3600
    response.set_cookie(CODE_KEY, code, max_age=max_age, samesite='Lax')
    # Make sure proxies don’t cache this response so that random user’s don’t
    # get the cookie.
    response.headers['cache-control'] = 'private, max-age=0'


def authorised(
    handler: typing.Callable[..., flask.Response]
) -> typing.Callable[..., flask.Response]:
    """A decorator around Flask handler which check if user is authorised.

    Verifies whether user is authorised and only then calls the actual handler.
    On return, sets Set-Cookie header if necessary.  The handler will be called
    with additional positional argument at the front: login of the user.
    """

    @functools.wraps(handler)
    def decorated(*args: typing.Any, **kw: typing.Any) -> flask.Response:
        code = AuthCode.from_request(flask.request)
        old_code_str = code.code
        if not code.verify():
            _unauthorised(f'You ({code.login}) are not a member of Near or '
                          'Near Protocol organisation or you have revoked '
                          'GitHub authorisation for NayDuck.')
        response = flask.make_response(handler(code.login, *args, **kw))
        if code.code != old_code_str:
            add_cookie(response, code.code)
        return response

    return decorated


def _unauthorised(description: str) -> werkzeug.exceptions.Unauthorized:
    """Returns an Unauthorized HTTP exception."""
    method = werkzeug.datastructures.WWWAuthenticate(CODE_KEY)
    return werkzeug.exceptions.Unauthorized(description=description,
                                            www_authenticate=method)
