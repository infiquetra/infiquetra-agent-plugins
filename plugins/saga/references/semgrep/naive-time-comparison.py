"""Fresh rule-test target for saga.naive-time-comparison. Never executed."""

from datetime import datetime, timezone


def is_expired(expires_at):
    # ruleid: saga.naive-time-comparison
    return datetime.utcnow() > expires_at


def started_before(started_at):
    # ruleid: saga.naive-time-comparison
    return datetime.now() < started_at


def deadline_passed(deadline):
    # ruleid: saga.naive-time-comparison
    return deadline <= datetime.utcnow()


def is_expired_aware(expires_at):
    # ok: saga.naive-time-comparison
    return datetime.now(timezone.utc) > expires_at


def both_naive(first, second):
    # ok: saga.naive-time-comparison
    return datetime.utcnow() > datetime.utcnow()


def same_call_twice():
    # ok: saga.naive-time-comparison
    return datetime.now() == datetime.now()


def merely_stamped():
    # ok: saga.naive-time-comparison
    stamped = datetime.now(timezone.utc)
    return stamped
