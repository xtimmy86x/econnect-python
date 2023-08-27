import pytest
import responses
from requests.exceptions import HTTPError

from elmo import query
from elmo.api.client import ElmoClient
from elmo.api.exceptions import (
    CodeError,
    CredentialError,
    InvalidInput,
    InvalidSector,
    InvalidToken,
    LockError,
    LockNotAcquired,
    QueryNotValid,
)


def test_client_constructor_default():
    """Should build the client using the default values."""
    client = ElmoClient()
    assert client._router._base_url == "https://connect.elmospa.com"
    assert client._domain is None
    assert client._session_id is None


def test_client_constructor_v03():
    """Backward compatibility pre 0.4: the order of parameters must not change
    otherwise a breaking change is introduced.
    """
    client = ElmoClient("https://example.com", "domain")
    assert client._router._base_url == "https://example.com"
    assert client._domain == "domain"
    assert client._session_id is None


def test_client_constructor():
    """Should build the client using the base URL and the domain suffix."""
    client = ElmoClient(base_url="https://example.com", domain="domain")
    assert client._router._base_url == "https://example.com"
    assert client._domain == "domain"
    assert client._session_id is None


def test_client_constructor_with_session_id():
    """Should build the client with a provided `session_id`."""
    client = ElmoClient(session_id="test")
    assert client._session_id == "test"


def test_client_auth_success(server):
    """Should authenticate with valid credentials."""
    html = """
        {
            "SessionId": "00000000-0000-0000-0000-000000000000",
            "Username": "test",
            "Domain": "domain",
            "Language": "en",
            "IsActivated": true,
            "IsConnected": true,
            "IsLoggedIn": false,
            "IsLoginInProgress": false,
            "CanElevate": true,
            "AccountId": 100,
            "IsManaged": false,
            "Redirect": false,
            "IsElevation": false
        }
    """
    server.add(responses.GET, "https://example.com/api/login", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    # Test
    assert client.auth("test", "test") == "00000000-0000-0000-0000-000000000000"
    assert client._session_id == "00000000-0000-0000-0000-000000000000"
    assert len(server.calls) == 1


def test_client_auth_forbidden(server):
    """Should raise an exception if credentials are not valid."""
    server.add(
        responses.GET,
        "https://example.com/api/login",
        body="Username or Password is invalid",
        status=403,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    # Test
    with pytest.raises(CredentialError):
        client.auth("test", "test")
    assert client._session_id is None
    assert len(server.calls) == 1


def test_client_auth_unknown_error(server):
    """Should raise an exception if there is an unknown error."""
    server.add(responses.GET, "https://example.com/api/login", body="Server Error", status=500)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    # Test
    with pytest.raises(HTTPError):
        client.auth("test", "test")
    assert client._session_id is None
    assert len(server.calls) == 1


def test_client_auth_redirect(server):
    """Should update the client Router if a redirect is required."""
    redirect = """
        {
            "SessionId": "00000000-0000-0000-0000-000000000000",
            "Domain": "domain",
            "Redirect": true,
            "RedirectTo": "https://redirect.example.com"
        }
    """
    login = """
        {
            "SessionId": "99999999-9999-9999-9999-999999999999",
            "Username": "test",
            "Domain": "domain",
            "Language": "en",
            "IsActivated": true,
            "IsConnected": true,
            "IsLoggedIn": false,
            "IsLoginInProgress": false,
            "CanElevate": true,
            "AccountId": 100,
            "IsManaged": false,
            "Redirect": false,
            "IsElevation": false
        }
    """
    server.add(responses.GET, "https://example.com/api/login", body=redirect, status=200)
    server.add(responses.GET, "https://redirect.example.com/api/login", body=login, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    # Test
    assert client.auth("test", "test")
    assert client._router._base_url == "https://redirect.example.com"
    assert client._session_id == "99999999-9999-9999-9999-999999999999"
    assert len(server.calls) == 2


def test_client_auth_infinite_redirect(server):
    """Should prevent infinite redirects in the auth() call."""
    redirect = """
        {
            "SessionId": "00000000-0000-0000-0000-000000000000",
            "Domain": "domain",
            "Redirect": true,
            "RedirectTo": "https://redirect.example.com"
        }
    """
    server.add(responses.GET, "https://example.com/api/login", body=redirect, status=200)
    server.add(
        responses.GET,
        "https://redirect.example.com/api/login",
        body=redirect,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    # Test
    assert client.auth("test", "test")
    assert client._router._base_url == "https://redirect.example.com"
    assert client._session_id == "00000000-0000-0000-0000-000000000000"
    assert len(server.calls) == 2


def test_client_auth_without_domain(server):
    """Should authenticate without sending the domain field."""
    html = """
        {
            "SessionId": "00000000-0000-0000-0000-000000000000",
            "Redirect": false
        }
    """
    server.add(responses.GET, "https://example.com/api/login", body=html, status=200)
    client = ElmoClient(base_url="https://example.com")
    # Test
    client.auth("test", "test")
    assert len(server.calls) == 1
    assert "domain" not in server.calls[0].request.params


def test_client_auth_with_domain(server):
    """Should authenticate sending the domain field."""
    html = """
        {
            "SessionId": "00000000-0000-0000-0000-000000000000",
            "Redirect": false
        }
    """
    server.add(responses.GET, "https://example.com/api/login", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    # Test
    client.auth("test", "test")
    assert len(server.calls) == 1
    assert server.calls[0].request.params["domain"] == "domain"


def test_client_poll(server):
    """Should leverage long-polling endpoint to grab the status."""
    html = """
        {
            "ConnectionStatus": false,
            "CanElevate": false,
            "LoggedIn": false,
            "LoginInProgress": false,
            "Areas": false,
            "Events": false,
            "Inputs": false,
            "Outputs": false,
            "Anomalies": false,
            "ReadStringsInProgress": false,
            "ReadStringPercentage": 0,
            "Strings": 0,
            "ManagedAccounts": false,
            "Temperature": false,
            "StatusAdv": false,
            "Images": false,
            "AdditionalInfoSupported": true,
            "HasChanges": false
        }
    """
    server.add(responses.POST, "https://example.com/api/updates", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    ids = {
        query.SECTORS: 42,
        query.INPUTS: 4242,
    }
    # Test
    state = client.poll(ids)
    assert len(state.keys()) == 3
    # Check response
    assert state["has_changes"] is False
    assert state["inputs"] is False
    assert state["areas"] is False
    # Check request
    body = server.calls[0].request.body.split("&")
    assert "sessionId=test" in body
    assert "Areas=42" in body
    assert "Inputs=4242" in body
    assert "CanElevate=1" in body
    assert "ConnectionStatus=1" in body


def test_client_poll_with_changes(server):
    """Should return a dict with updated states."""
    html = """
        {
            "ConnectionStatus": false,
            "CanElevate": false,
            "LoggedIn": false,
            "LoginInProgress": false,
            "Areas": true,
            "Events": false,
            "Inputs": true,
            "Outputs": false,
            "Anomalies": false,
            "ReadStringsInProgress": false,
            "ReadStringPercentage": 0,
            "Strings": 0,
            "ManagedAccounts": false,
            "Temperature": false,
            "StatusAdv": false,
            "Images": false,
            "AdditionalInfoSupported": true,
            "HasChanges": true
        }
    """
    server.add(responses.POST, "https://example.com/api/updates", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    ids = {
        query.SECTORS: 42,
        query.INPUTS: 4242,
    }
    # Test
    state = client.poll(ids)
    assert len(state.keys()) == 3
    assert state["has_changes"] is True
    assert state["inputs"] is True
    assert state["areas"] is True


def test_client_poll_ignore_has_changes(server):
    """Should ignore HasChanges value to prevent `event` updates."""
    html = """
        {
            "ConnectionStatus": false,
            "CanElevate": false,
            "LoggedIn": false,
            "LoginInProgress": false,
            "Areas": false,
            "Events": true,
            "Inputs": false,
            "Outputs": false,
            "Anomalies": false,
            "ReadStringsInProgress": false,
            "ReadStringPercentage": 0,
            "Strings": 0,
            "ManagedAccounts": false,
            "Temperature": false,
            "StatusAdv": false,
            "Images": false,
            "AdditionalInfoSupported": true,
            "HasChanges": true
        }
    """
    server.add(responses.POST, "https://example.com/api/updates", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    ids = {
        query.SECTORS: 42,
        query.INPUTS: 4242,
    }
    # Test
    state = client.poll(ids)
    assert len(state.keys()) == 3
    assert state["has_changes"] is False


def test_client_poll_unknown_error(server):
    """Should raise an Exception for unknown status code."""
    server.add(
        responses.POST,
        "https://example.com/api/updates",
        body="Server Error",
        status=500,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    ids = {
        query.SECTORS: 42,
        query.INPUTS: 4242,
    }
    # Test
    with pytest.raises(HTTPError):
        client.poll(ids)
    assert len(server.calls) == 1


def test_client_lock(server, mocker):
    """Should acquire a lock if credentials are properly provided."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(responses.POST, "https://example.com/api/panel/syncLogin", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "unlock")
    # Test
    with client.lock("test"):
        assert not client._lock.acquire(False)
    assert len(server.calls) == 1


def test_client_lock_wrong_code(server, mocker):
    """Should raise a CodeError if inserted code is not correct."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": false
        }
    ]"""
    server.add(responses.POST, "https://example.com/api/panel/syncLogin", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "unlock")
    # Test
    with pytest.raises(CodeError):
        with client.lock("test"):
            pass
    assert len(server.calls) == 1


def test_client_lock_called_twice(server, mocker):
    """Should raise a CodeError if Lock() is called twice."""
    server.add(responses.POST, "https://example.com/api/panel/syncLogin", status=403)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "unlock")
    # Test
    with pytest.raises(LockError):
        with client.lock("test"):
            pass
    assert len(server.calls) == 1


def test_client_lock_unknown_error(server, mocker):
    """Should raise an Exception for unknown status code."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncLogin",
        body="Server Error",
        status=500,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "unlock")
    # Test
    with pytest.raises(HTTPError):
        with client.lock(None):
            pass
    assert len(server.calls) == 1


def test_client_lock_calls_unlock(server, mocker):
    """Should call unlock() when exiting from the context."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(responses.POST, "https://example.com/api/panel/syncLogin", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "unlock")
    # Test
    with client.lock("test"):
        pass
    assert client.unlock.called is True
    assert len(server.calls) == 1


def test_client_lock_and_unlock_with_exception(server, mocker):
    """Should call unlock() even if an exception is raised in the block."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(responses.POST, "https://example.com/api/panel/syncLogin", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "unlock")
    # Test
    with pytest.raises(Exception):
        with client.lock("test"):
            raise Exception
    assert client.unlock.called is True
    assert len(server.calls) == 1


def test_client_unlock(server):
    """Should call the API and release the system lock."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncLogout",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.unlock() is True
    assert client._lock.acquire(False)
    assert len(server.calls) == 1


def test_client_unlock_fails_missing_lock(server):
    """unlock() should fail without calling the endpoint if Lock() has not been acquired."""
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(LockNotAcquired):
        client.unlock()
    assert client._lock.acquire(False)
    assert len(server.calls) == 0


def test_client_unlock_fails_forbidden(server):
    """Should fail if wrong credentials are used."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": false
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncLogout",
        body=html,
        status=403,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(LockNotAcquired):
        client.unlock()
    assert not client._lock.locked()
    assert len(server.calls) == 1


def test_client_unlock_fails_unexpected_error(server):
    """Should raise an error and keep the lock if the server has problems."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": false
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncLogout",
        body=html,
        status=500,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(HTTPError):
        client.unlock()
    assert not client._lock.acquire(False)
    assert len(server.calls) == 1


def test_client_arm(server):
    """Should call the API and arm the system."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.arm() is True
    assert len(server.calls) == 1
    body = server.calls[0].request.body.split("&")
    assert "CommandType=1" in body
    assert "ElementsClass=1" in body
    assert "ElementsIndexes=1" in body
    assert "sessionId=test" in body


def test_client_arm_sectors(server):
    """Should call the API and arm only the given sectors."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.arm([3, 4]) is True
    assert len(server.calls) == 2
    body = server.calls[0].request.body.split("&")
    assert "CommandType=1" in body
    assert "ElementsClass=9" in body
    assert "ElementsIndexes=3" in body
    assert "sessionId=test" in body
    body = server.calls[1].request.body.split("&")
    assert "CommandType=1" in body
    assert "ElementsClass=9" in body
    assert "ElementsIndexes=4" in body
    assert "sessionId=test" in body


def test_client_arm_fails_missing_lock(server):
    """arm() should fail without calling the endpoint if Lock() has not been acquired."""
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(LockNotAcquired):
        client.arm()
    assert client._lock.acquire(False)
    assert len(server.calls) == 0


def test_client_arm_fails_missing_session(server):
    """Should fail if a wrong access token is used."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        status=401,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidToken):
        client.arm()
    assert len(server.calls) == 1


def test_client_arm_fails_wrong_sector(server):
    """Should fail if a not existing sector is used."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": false
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidSector):
        assert client.arm([200])


def test_client_arm_fails_unknown_error(server):
    """Should fail if an unknown error happens."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body="Server Error",
        status=500,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(HTTPError):
        client.arm()
    assert len(server.calls) == 1


def test_client_disarm(server):
    """Should call the API and disarm the system."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.disarm() is True
    assert len(server.calls) == 1
    body = server.calls[0].request.body.split("&")
    assert "CommandType=2" in body
    assert "ElementsClass=1" in body
    assert "ElementsIndexes=1" in body
    assert "sessionId=test" in body


def test_client_disarm_sectors(server):
    """Should call the API and disarm only the given sectors."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": true
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.disarm([3, 4]) is True
    assert len(server.calls) == 2
    body = server.calls[0].request.body.split("&")
    assert "CommandType=2" in body
    assert "ElementsClass=9" in body
    assert "ElementsIndexes=3" in body
    assert "sessionId=test" in body
    body = server.calls[1].request.body.split("&")
    assert "CommandType=2" in body
    assert "ElementsClass=9" in body
    assert "ElementsIndexes=4" in body
    assert "sessionId=test" in body


def test_client_disarm_fails_missing_lock(server):
    """disarm() should fail without calling the endpoint if Lock() has not been acquired."""
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(LockNotAcquired):
        client.disarm()
    assert client._lock.acquire(False)
    assert len(server.calls) == 0


def test_client_disarm_fails_missing_session(server):
    """Should fail if a wrong access token is used."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        status=401,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidToken):
        client.disarm()
    assert len(server.calls) == 1


def test_client_disarm_fails_wrong_sector(server):
    """Should fail if a not existing sector is used."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 5,
            "Successful": false
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidSector):
        assert client.disarm([200])


def test_client_disarm_fails_unknown_error(server):
    """Should fail if an unknown error happens."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body="Server Error",
        status=500,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "unknown"
    client._lock.acquire()
    # Test
    with pytest.raises(HTTPError):
        client.disarm()
    assert len(server.calls) == 1


def test_client_include(server):
    """Should call the API and include the given input."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 147,
            "Successful": true,
            "ErrorMessages": []
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.include([3]) is True
    assert len(server.calls) == 1
    body = server.calls[0].request.body.split("&")
    assert "CommandType=1" in body
    assert "ElementsClass=10" in body
    assert "ElementsIndexes=3" in body
    assert "sessionId=test" in body


def test_client_include_multiple_inputs(server):
    """Should call the API and include given inputs."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 147,
            "Successful": true,
            "ErrorMessages": []
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.include([3, 4]) is True
    assert len(server.calls) == 2
    body = server.calls[0].request.body.split("&")
    assert "CommandType=1" in body
    assert "ElementsClass=10" in body
    assert "ElementsIndexes=3" in body
    assert "sessionId=test" in body
    body = server.calls[1].request.body.split("&")
    assert "CommandType=1" in body
    assert "ElementsClass=10" in body
    assert "ElementsIndexes=4" in body
    assert "sessionId=test" in body


def test_client_include_fails_missing_lock(server):
    """include() should fail without calling the endpoint if Lock() has not been acquired."""
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(LockNotAcquired):
        client.include([1])
    assert client._lock.acquire(False)
    assert len(server.calls) == 0


def test_client_include_fails_missing_session(server):
    """Should fail if a wrong access token is used."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        status=401,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidToken):
        client.include([1])
    assert len(server.calls) == 1


def test_client_include_fails_wrong_input(server):
    """Should fail if a not existing input is used."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 147,
            "Successful": false,
            "ErrorMessages": ["Command failed."]
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidInput):
        assert client.include([9000])


def test_client_include_fails_unknown_error(server):
    """Should fail if an unknown error happens."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body="Server Error",
        status=500,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(HTTPError):
        client.include([1])
    assert len(server.calls) == 1


def test_client_exclude(server):
    """Should call the API and exclude only the given inputs."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 147,
            "Successful": true,
            "ErrorMessages": []
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.exclude([3]) is True
    assert len(server.calls) == 1
    body = server.calls[0].request.body.split("&")
    assert "CommandType=2" in body
    assert "ElementsClass=10" in body
    assert "ElementsIndexes=3" in body
    assert "sessionId=test" in body


def est_client_exclude_multiple_inputs(server):
    """Should call the API and exclude only the given inputs."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 147,
            "Successful": true,
            "ErrorMessages": []
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    assert client.exclude([3, 4]) is True
    assert len(server.calls) == 2
    body = server.calls[0].request.body.split("&")
    assert "CommandType=2" in body
    assert "ElementsClass=10" in body
    assert "ElementsIndexes=3" in body
    assert "sessionId=test" in body
    body = server.calls[1].request.body.split("&")
    assert "CommandType=2" in body
    assert "ElementsClass=10" in body
    assert "ElementsIndexes=4" in body
    assert "sessionId=test" in body


def test_client_exclude_fails_missing_lock(server):
    """exclude() should fail without calling the endpoint if Lock() has not been acquired."""
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(LockNotAcquired):
        client.exclude([1])
    assert client._lock.acquire(False)
    assert len(server.calls) == 0


def test_client_exclude_fails_missing_session(server):
    """Should fail if a wrong access token is used."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        status=401,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidToken):
        client.exclude([1])
    assert len(server.calls) == 1


def test_client_exclude_fails_wrong_input(server):
    """Should fail if a not existing input is used."""
    html = """[
        {
            "Poller": {"Poller": 1, "Panel": 1},
            "CommandId": 147,
            "Successful": false,
            "ErrorMessages": ["Command failed."]
        }
    ]"""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body=html,
        status=200,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    client._lock.acquire()
    # Test
    with pytest.raises(InvalidInput):
        assert client.exclude([9000])


def test_client_exclude_fails_unknown_error(server):
    """Should fail if an unknown error happens."""
    server.add(
        responses.POST,
        "https://example.com/api/panel/syncSendCommand",
        body="Server Error",
        status=500,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "unknown"
    client._lock.acquire()
    # Test
    with pytest.raises(HTTPError):
        client.exclude([1])
    assert len(server.calls) == 1


def test_client_get_descriptions(server):
    """Should retrieve inputs/sectors descriptions."""
    html = """
    [
      {
        "AccountId": 1,
        "Class": 9,
        "Index": 0,
        "Description": "S1 Living Room",
        "Created": "/Date(1546004120767+0100)/",
        "Version": "AAAAAAAAgPc="
      },
      {
        "AccountId": 1,
        "Class": 9,
        "Index": 1,
        "Description": "S2 Bedroom",
        "Created": "/Date(1546004120770+0100)/",
        "Version": "AAAAAAAAgPg="
      },
      {
        "AccountId": 1,
        "Class": 10,
        "Index": 0,
        "Description": "Alarm",
        "Created": "/Date(1546004147490+0100)/",
        "Version": "AAAAAAAAgRs="
      },
      {
        "AccountId": 1,
        "Class": 10,
        "Index": 1,
        "Description": "Entryway Sensor",
        "Created": "/Date(1546004147493+0100)/",
        "Version": "AAAAAAAAgRw="
      }
    ]
    """
    server.add(responses.POST, "https://example.com/api/strings", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    descriptions = client._get_descriptions()
    # Expected output
    assert len(server.calls) == 1
    assert descriptions == {
        9: {0: "S1 Living Room", 1: "S2 Bedroom"},
        10: {0: "Alarm", 1: "Entryway Sensor"},
    }
    # Check constants used in the code
    assert descriptions[query.SECTORS][0] == "S1 Living Room"
    assert descriptions[query.INPUTS][0] == "Alarm"


def test_client_get_descriptions_cached(server):
    """Should cache the result of get_descriptions()."""
    html = """
    [
      {
        "AccountId": 1,
        "Class": 9,
        "Index": 0,
        "Description": "S1 Living Room",
        "Created": "/Date(1546004120767+0100)/",
        "Version": "AAAAAAAAgPc="
      }
    ]
    """
    server.add(responses.POST, "https://example.com/api/strings", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    client._get_descriptions()
    client._get_descriptions()
    assert len(server.calls) == 1


def test_client_get_descriptions_unauthorized(server):
    """Should raise HTTPError if the request is unauthorized."""
    server.add(
        responses.POST,
        "https://example.com/api/strings",
        body="User not authenticated",
        status=403,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(HTTPError):
        client._get_descriptions()


def test_client_get_descriptions_error(server):
    """Should raise HTTPError if there is a client error."""
    server.add(
        responses.POST,
        "https://example.com/api/strings",
        body="Bad Request",
        status=400,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(HTTPError):
        client._get_descriptions()


def test_client_get_sectors_status(server, mocker):
    """Should query a Elmo system to retrieve sectors status."""
    html = """[
       {
           "Active": true,
           "ActivePartial": false,
           "Max": false,
           "Activable": true,
           "ActivablePartial": false,
           "InUse": true,
           "Id": 1,
           "Index": 0,
           "Element": 1,
           "CommandId": 0,
           "InProgress": false
       },
       {
           "Active": true,
           "ActivePartial": false,
           "Max": false,
           "Activable": true,
           "ActivablePartial": false,
           "InUse": true,
           "Id": 2,
           "Index": 1,
           "Element": 2,
           "CommandId": 0,
           "InProgress": false
       },
       {
           "Active": false,
           "ActivePartial": false,
           "Max": false,
           "Activable": true,
           "ActivablePartial": false,
           "InUse": true,
           "Id": 3,
           "Index": 2,
           "Element": 3,
           "CommandId": 0,
           "InProgress": false
       },
       {
           "Active": false,
           "ActivePartial": false,
           "Max": false,
           "Activable": true,
           "ActivablePartial": false,
           "InUse": false,
           "Id": 4,
           "Index": 3,
           "Element": 5,
           "CommandId": 0,
           "InProgress": false
       }
    ]"""
    # query() depends on _get_descriptions()
    server.add(responses.POST, "https://example.com/api/areas", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "_get_descriptions")
    client._get_descriptions.return_value = {
        9: {0: "Living Room", 1: "Bedroom", 2: "Kitchen", 3: "Entryway"},
    }
    # Test
    sectors = client.query(query.SECTORS)
    # Expected output
    assert client._get_descriptions.called is True
    assert len(server.calls) == 1
    assert sectors == {
        "last_id": 4,
        "sectors": {
            0: {
                "element": 1,
                "id": 1,
                "index": 0,
                "status": True,
                "excluded": False,
                "name": "Living Room",
            },
            1: {
                "element": 2,
                "id": 2,
                "index": 1,
                "status": True,
                "excluded": False,
                "name": "Bedroom",
            },
            2: {
                "element": 3,
                "id": 3,
                "index": 2,
                "status": False,
                "excluded": False,
                "name": "Kitchen",
            },
        },
    }


def test_client_get_inputs_status(server, mocker):
    """Should query a Elmo system to retrieve inputs status."""
    html = """[
       {
           "Alarm": true,
           "MemoryAlarm": false,
           "Excluded": false,
           "InUse": true,
           "IsVideo": false,
           "Id": 1,
           "Index": 0,
           "Element": 1,
           "CommandId": 0,
           "InProgress": false
       },
       {
           "Alarm": true,
           "MemoryAlarm": false,
           "Excluded": false,
           "InUse": true,
           "IsVideo": false,
           "Id": 2,
           "Index": 1,
           "Element": 2,
           "CommandId": 0,
           "InProgress": false
       },
       {
           "Alarm": false,
           "MemoryAlarm": false,
           "Excluded": true,
           "InUse": true,
           "IsVideo": false,
           "Id": 3,
           "Index": 2,
           "Element": 3,
           "CommandId": 0,
           "InProgress": false
       },
       {
           "Alarm": false,
           "MemoryAlarm": false,
           "Excluded": false,
           "InUse": false,
           "IsVideo": false,
           "Id": 4,
           "Index": 3,
           "Element": 4,
           "CommandId": 0,
           "InProgress": false
       }
    ]"""
    # query() depends on _get_descriptions()
    server.add(responses.POST, "https://example.com/api/inputs", body=html, status=200)
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "_get_descriptions")
    client._get_descriptions.return_value = {
        10: {0: "Alarm", 1: "Window kitchen", 2: "Door entryway", 3: "Window bathroom"},
    }
    # Test
    inputs = client.query(query.INPUTS)
    # Expected output
    assert client._get_descriptions.called is True
    assert len(server.calls) == 1
    assert inputs == {
        "last_id": 4,
        "inputs": {
            0: {
                "element": 1,
                "id": 1,
                "index": 0,
                "status": True,
                "excluded": False,
                "name": "Alarm",
            },
            1: {
                "element": 2,
                "id": 2,
                "index": 1,
                "status": True,
                "excluded": False,
                "name": "Window kitchen",
            },
            2: {
                "element": 3,
                "id": 3,
                "status": False,
                "index": 2,
                "excluded": True,
                "name": "Door entryway",
            },
        },
    }


def test_client_query_not_valid(client):
    """Should raise QueryNotValid if the query is not recognized."""
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    # Test
    with pytest.raises(QueryNotValid):
        client.query("wrong_query")


def test_client_query_unauthorized(server, mocker):
    """Should raise HTTPError if the request is unauthorized."""
    server.add(
        responses.POST,
        "https://example.com/api/areas",
        body="User not authenticated",
        status=403,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "_get_descriptions")
    # Test
    with pytest.raises(HTTPError):
        client.query(query.SECTORS)


def test_client_query_error(server, mocker):
    """Should raise HTTPError if there is a client error."""
    server.add(
        responses.POST,
        "https://example.com/api/areas",
        body="Bad Request",
        status=400,
    )
    client = ElmoClient(base_url="https://example.com", domain="domain")
    client._session_id = "test"
    mocker.patch.object(client, "_get_descriptions")
    # Test
    with pytest.raises(HTTPError):
        client.query(query.SECTORS)
