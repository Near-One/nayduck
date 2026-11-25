from __future__ import annotations

import base64
import pathlib
import sys
import time
import typing
import unittest.mock

import flask
import pytest
import requests
import werkzeug.exceptions

from lib import config

_CONFIG = config.Config(
    {
        'key': base64.urlsafe_b64encode(bytes(32)).decode('ascii'),
        'github-client-id': 'client-id',
        'github-client-secret': 'client-secret',
    }, pathlib.Path('auth.json'))

# Importing the auth module reads its configuration and, through backend_db,
# connects to the database.  Neither is available in tests.
with unittest.mock.patch.object(config, 'load', return_value=_CONFIG), \
     unittest.mock.patch.dict(
         sys.modules, {f'{__package__}.backend_db': unittest.mock.Mock()}):
    from . import auth

_APP = flask.Flask(__name__)
_DAY = 24 * 3600

_MEMBER = (200, [{'login': 'other'}, {'login': 'near'}])
_NOT_MEMBER = (200, [{'login': 'other'}])
_BAD_CREDENTIALS = (401, {'message': 'Bad credentials'})
_RATE_LIMITED = (403, {'message': 'API rate limit exceeded'})
_SERVER_ERROR = (502, {'message': 'Server Error'})
_UNEXPECTED = (200, {'message': 'not a list'})
_TIMEOUT = requests.Timeout()
# Stands for a body which is not JSON.
_MALFORMED = ValueError('malformed JSON')
_REJECTED_NO_BODY = [(401, _MALFORMED), (403, _MALFORMED)]
_OK_NO_BODY = (200, _MALFORMED)


def _code(is_authorised: bool, age: int) -> auth.AuthCode:
    """Returns a code whose last membership check was `age` seconds ago."""
    return auth.AuthCode(login='user',
                         is_authorised=is_authorised,
                         last_check=int(time.time()) - age,
                         token='gho_token')


def _response(answer: typing.Any) -> typing.Any:
    """Returns what a GitHub API call gives for the specified answer."""
    if isinstance(answer, Exception):
        return answer
    status_code, body = answer
    response = unittest.mock.Mock(status_code=status_code)
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    return response


def _github(*answers: typing.Any) -> typing.Any:
    """Patches the GitHub API call to give the specified answers.

    Args:
        answers: Answers to consecutive calls.  Each is either a (status
            code, JSON body) tuple to respond with or an exception to raise.
            If there is just one, it is the answer to every call.
    """
    responses = [_response(answer) for answer in answers]
    get = unittest.mock.Mock(side_effect=responses)
    if len(responses) == 1 and isinstance(responses[0], Exception):
        get = unittest.mock.Mock(side_effect=responses[0])
    elif len(responses) == 1:
        get = unittest.mock.Mock(return_value=responses[0])
    return unittest.mock.patch.object(auth.requests, 'get', get)


def _request(code: auth.AuthCode) -> tuple[int, bool, typing.Optional[str]]:
    """Sends a request with given code to a handler requiring authorisation.

    Returns:
        A (status code, whether the handler was called, value of the nay-code
        cookie set by the response if any) tuple.
    """
    calls = []

    @auth.authorised
    def handler(login: str) -> flask.Response:
        calls.append(login)
        return flask.Response('ok')

    headers = {'authorization': f'{auth.CODE_KEY} {code.code}'}
    with _APP.test_request_context('/api/run/new',
                                   method='POST',
                                   headers=headers):
        try:
            response = handler()
        except werkzeug.exceptions.HTTPException as ex:
            return ex.code or 0, bool(calls), None
    cookie = None
    for value in response.headers.getlist('set-cookie'):
        if value.startswith(auth.CODE_KEY + '='):
            cookie = value[len(auth.CODE_KEY) + 1:].split(';')[0]
    return response.status_code, bool(calls), cookie


@pytest.mark.parametrize('answer,want', [
    (_MEMBER, True),
    ((200, [{
        'login': 'nearprotocol'
    }]), True),
    (_NOT_MEMBER, False),
    ((200, []), False),
    (_BAD_CREDENTIALS, False),
    (_RATE_LIMITED, False),
    (_REJECTED_NO_BODY[0], False),
    (_REJECTED_NO_BODY[1], False),
])
def test_verify_organisations(answer: typing.Any, want: bool) -> None:
    with _github(answer) as get:
        assert want == auth._verify_organisations('user', 'gho_token')
    assert get.call_args.kwargs['timeout'] == auth._GITHUB_TIMEOUT


@pytest.mark.parametrize('answer', [
    _SERVER_ERROR, _UNEXPECTED, _OK_NO_BODY, _TIMEOUT,
    requests.ConnectionError()
])
def test_verify_organisations_unavailable(answer: typing.Any) -> None:
    with _github(answer), pytest.raises(auth.GitHubUnavailable):
        auth._verify_organisations('user', 'gho_token')


def _page_of(*last: str) -> tuple[int, list[dict[str, str]]]:
    """Returns a full page of organisations ending with the given ones."""
    count = auth._ORGANISATIONS_PER_PAGE - len(last)
    logins = [f'other-{i}' for i in range(count)] + list(last)
    return 200, [{'login': login} for login in logins]


def _pages_requested(get: typing.Any) -> list[str]:
    return [call.args[0].split('?')[1] for call in get.call_args_list]


def test_verify_organisations_reads_further_pages() -> None:
    with _github(_page_of(), _page_of(), _MEMBER) as get:
        assert auth._verify_organisations('user', 'gho_token')
    assert _pages_requested(get) == [
        'per_page=100&page=1', 'per_page=100&page=2', 'per_page=100&page=3'
    ]

    # The last page may be empty if the count is a multiple of the page size.
    for last_page in (_NOT_MEMBER, (200, [])):
        with _github(_page_of(), last_page) as get:
            assert not auth._verify_organisations('user', 'gho_token')
        assert len(get.call_args_list) == 2


def test_verify_organisations_stops_at_a_match() -> None:
    with _github(_page_of('near'), _TIMEOUT) as get:
        assert auth._verify_organisations('user', 'gho_token')
    assert _pages_requested(get) == ['per_page=100&page=1']


def test_verify_organisations_failure_on_a_further_page() -> None:
    with _github(_page_of(), _BAD_CREDENTIALS):
        assert not auth._verify_organisations('user', 'gho_token')
    for answer in (_SERVER_ERROR, _UNEXPECTED, _TIMEOUT):
        with _github(_page_of(), answer), \
             pytest.raises(auth.GitHubUnavailable):
            auth._verify_organisations('user', 'gho_token')


def test_fresh_code_is_not_rechecked() -> None:
    with _github(_NOT_MEMBER) as get:
        assert (200, True, None) == _request(_code(True, age=3600))
        assert (401, False, None) == _request(_code(False, age=3600))
    get.assert_not_called()


@pytest.mark.parametrize('was_authorised', [True, False])
def test_stale_code_of_a_member(was_authorised: bool) -> None:
    with _github(_MEMBER):
        status, called, cookie = _request(_code(was_authorised, age=2 * _DAY))
    assert (200, True) == (status, called)
    # The refreshed code is sent back and does not need another check.
    assert cookie
    with _github(_NOT_MEMBER) as get:
        assert auth.AuthCode.from_code(cookie).verify()
    get.assert_not_called()


@pytest.mark.parametrize(
    'answer',
    [_NOT_MEMBER, _BAD_CREDENTIALS, _RATE_LIMITED, *_REJECTED_NO_BODY])
@pytest.mark.parametrize('was_authorised', [True, False])
def test_stale_code_of_a_non_member(answer: typing.Any,
                                    was_authorised: bool) -> None:
    with _github(answer):
        got = _request(_code(was_authorised, age=2 * _DAY))
    assert (401, False, None) == got


@pytest.mark.parametrize('answer', [
    _SERVER_ERROR, _UNEXPECTED, _OK_NO_BODY, _TIMEOUT,
    requests.ConnectionError()
])
def test_github_unavailable_keeps_last_result(answer: typing.Any) -> None:
    with _github(answer):
        # No cookie: the code is not refreshed so the next request checks
        # again.
        assert (200, True, None) == _request(_code(True, age=2 * _DAY))
        assert (401, False, None) == _request(_code(False, age=2 * _DAY))


def test_missing_or_invalid_code() -> None:

    @auth.authorised
    def handler(_login: str) -> flask.Response:
        raise AssertionError('handler must not be called')

    for headers in ({}, {'authorization': f'{auth.CODE_KEY} user:bogus'}):
        with _APP.test_request_context('/api/run/new', headers=headers):
            with pytest.raises(werkzeug.exceptions.Unauthorized):
                handler()


def test_for_user() -> None:
    with _github(_MEMBER):
        assert auth.AuthCode.for_user('user', 'gho_token').verify()
    with _github(_NOT_MEMBER):
        assert not auth.AuthCode.for_user('user', 'gho_token').verify()
    with _github(_TIMEOUT), pytest.raises(auth.GitHubUnavailable):
        auth.AuthCode.for_user('user', 'gho_token')
