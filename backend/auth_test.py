from __future__ import annotations

import base64
import pathlib
import sys
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

_MEMBER = (200, [{'login': 'other'}, {'login': 'near'}])
_NOT_MEMBER = (200, [{'login': 'other'}])
_BAD_CREDENTIALS = (401, {'message': 'Bad credentials'})
_RATE_LIMITED = (403, {'message': 'API rate limit exceeded'})
_SERVER_ERROR = (502, {'message': 'Server Error'})
_UNEXPECTED = (200, {'message': 'not a list'})
_TIMEOUT = requests.Timeout()


def _github(answer: typing.Any) -> typing.Any:
    """Patches the GitHub API call to give the specified answer.

    Args:
        answer: Either a (status code, JSON body) tuple to respond with or an
            exception to raise.
    """
    if isinstance(answer, Exception):
        return unittest.mock.patch.object(auth.requests,
                                          'get',
                                          side_effect=answer)
    status_code, body = answer
    response = unittest.mock.Mock(status_code=status_code)
    response.json.return_value = body
    return unittest.mock.patch.object(auth.requests,
                                      'get',
                                      return_value=response)


@pytest.mark.parametrize('answer,want', [
    (_MEMBER, True),
    ((200, [{
        'login': 'nearprotocol'
    }]), True),
    (_NOT_MEMBER, False),
    ((200, []), False),
    (_BAD_CREDENTIALS, False),
    (_RATE_LIMITED, False),
])
def test_verify_organisations(answer: typing.Any, want: bool) -> None:
    with _github(answer) as get:
        assert want == auth._verify_organisations('user', 'gho_token')
    assert get.call_args.kwargs['timeout'] == auth._GITHUB_TIMEOUT


@pytest.mark.parametrize(
    'answer',
    [_SERVER_ERROR, _UNEXPECTED, _TIMEOUT,
     requests.ConnectionError()])
def test_verify_organisations_unavailable(answer: typing.Any) -> None:
    with _github(answer), pytest.raises(auth.GitHubUnavailable):
        auth._verify_organisations('user', 'gho_token')


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
