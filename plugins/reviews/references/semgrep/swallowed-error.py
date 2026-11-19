"""Fresh rule-test target for saga.swallowed-error. Never executed; only scanned."""


def fetch_timeout():
    try:
        return read_config()
    # ruleid: saga.swallowed-error
    except TimeoutError:
        pass


def fetch_anything():
    try:
        return read_config()
    # ruleid: saga.swallowed-error
    except Exception:
        ...


def fetch_inline():
    try:
        return read_config()
    # ruleid: saga.swallowed-error
    except TimeoutError: pass


def fetch_logged():
    try:
        return read_config()
    # ok: saga.swallowed-error
    except TimeoutError:
        log("config unreadable")
        raise


def fetch_default():
    try:
        return read_config()
    # ok: saga.swallowed-error
    except TimeoutError:
        return None


def fetch_reraise():
    try:
        return read_config()
    # ok: saga.swallowed-error
    except TimeoutError:
        raise
