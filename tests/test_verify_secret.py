import hashlib
import hmac
import mock

from flux.constants import API_GITHUB, API_GOGS
from flux.models import Repository
from flux.utils import verify_secret



class FakeRequest(object):
    def __init__(self, data, headers=None):
        self.data = bytes(data, 'utf-8')
        self.headers = {}
        if headers is not None:
            self.headers = headers


def test_verify_secret_from_gogs_body_incorrect():
    request = FakeRequest('{"secret": 123}')
    repo = Repository(secret=321)

    ret = verify_secret(request, repo, API_GOGS)
    assert ret is False


def test_verify_secret_from_gogs_body_correct():
    request = FakeRequest('{"secret": 123}')
    repo = Repository(secret=123)

    ret = verify_secret(request, repo, API_GOGS)
    assert ret is True


def test_verify_secret_from_github_uses_header_incorrect():
    request = FakeRequest('{}', {'X-Hub-Signature': 'sha1=abcdefgh'})
    repo = Repository(secret="123")

    ret = verify_secret(request, repo, API_GITHUB)
    assert ret is False


def test_verify_secret_from_github_uses_header_correct():
    payload = bytes('{}', 'utf-8')
    repo = Repository(secret="123")
    signature = hmac.new(bytes(repo.secret, 'utf-8'), payload, hashlib.sha1).hexdigest()
    request = FakeRequest('{}', {'X-Hub-Signature': 'sha1={}'.format(signature)})

    ret = verify_secret(request, repo, API_GITHUB)
    assert ret is True
