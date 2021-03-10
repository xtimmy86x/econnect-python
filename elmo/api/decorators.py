from requests.exceptions import HTTPError

from .exceptions import MissingToken, InvalidToken, LockNotAcquired


def require_session(func):
    """Decorator applied to functions that require a valid Session.
    The session ID is verified in the instance for the attribute
    `_session_id`.

    Raises:
        MissingToken: if a `session_id` is not available.
        InvalidToken: if stored `session_id` is not valid (returns 401).
    """

    def func_wrapper(*args, **kwargs):
        self = args[0]
        if self._session_id is None:
            raise MissingToken
        else:
            try:
                return func(*args, **kwargs)
            except HTTPError as e:
                # Translate 401 into InvalidToken exception
                # Bubble up any other exception
                if e.response.status_code == 401:
                    raise InvalidToken
                raise e

    return func_wrapper


def require_lock(func):
    """Decorator applied to functions that require to obtain a system lock.
    The lock is verified in the instance for the attribute `_lock` that must
    be a `threading.Lock` class.

    Raises:
        LockNotAcquired: if a Lock is not acquired.
    """

    def func_wrapper(*args, **kwargs):
        self = args[0]
        # If the Lock() acquisition succeed it means a locking is not occurring
        # and so bail-out the execution (and release the lock).
        if not self._lock.locked():
            raise LockNotAcquired("A lock must be acquired via `lock()` method.")
        else:
            return func(*args, **kwargs)

    return func_wrapper
