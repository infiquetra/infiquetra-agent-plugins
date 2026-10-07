"""Fresh rule-test target for saga.release-shares-cleanup-block. Never executed."""


def renew_lease_shared():
    lease = acquire_lease()
    try:
        rotate(lease)
    # ruleid: saga.release-shares-cleanup-block
    finally:
        audit_rotation()
        lease.release()


def renew_lease_release_first():
    lease = acquire_lease()
    try:
        rotate(lease)
    # ruleid: saga.release-shares-cleanup-block
    finally:
        lease.release()
        audit_rotation()


def renew_lease_two_releases():
    first = acquire_lease()
    second = acquire_lease()
    try:
        rotate(first, second)
    # ruleid: saga.release-shares-cleanup-block
    finally:
        first.release()
        second.release()


def renew_lease_sole_release():
    lease = acquire_lease()
    try:
        rotate(lease)
    # ok: saga.release-shares-cleanup-block
    finally:
        lease.release()


def renew_lease_context_manager():
    # ok: saga.release-shares-cleanup-block
    with acquire_lease() as lease:
        rotate(lease)


def renew_lease_no_release():
    lease = acquire_lease()
    try:
        rotate(lease)
    # ok: saga.release-shares-cleanup-block
    finally:
        audit_rotation()
