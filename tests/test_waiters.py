"""Behavioural tests for DBClusterWaiter.update_password_and_wait (CPE-2769).

These drive the real botocore waiter machinery through a stubbed RDS client, so
they exercise the acceptor logic exactly as production does, only stubbing the
AWS network boundary.
"""

import pytest

from tests.conftest import CLUSTER_ID, cluster


def test_returns_when_cluster_stays_available_throughout(waiter_and_stubber):
    """Regression for CPE-2769: a steady 'available' status must resolve to
    success, not spin until the waiter exhausts its retries."""
    waiter, stubber, _ = waiter_and_stubber

    stubber.add_response("modify_db_cluster", {"DBCluster": {"Status": "available"}})
    stubber.add_response("describe_db_clusters", cluster("available"))  # waiter poll
    stubber.add_response("describe_db_clusters", cluster("available"))  # return value

    result = waiter.update_password_and_wait(CLUSTER_ID)

    assert result == [{"DBClusterIdentifier": CLUSTER_ID, "Status": "available"}]
    stubber.assert_no_pending_responses()


@pytest.mark.parametrize(
    "terminal_status",
    ["failed", "deleting", "stopped", "inaccessible-encryption-credentials"],
)
def test_terminal_states_still_raise(waiter_and_stubber, terminal_status):
    """Genuine terminal states must still fail loudly rather than be treated as
    success by the more permissive wait-for-available strategy."""
    waiter, stubber, _ = waiter_and_stubber

    stubber.add_response("modify_db_cluster", {"DBCluster": {"Status": "modifying"}})
    stubber.add_response("describe_db_clusters", cluster(terminal_status))

    with pytest.raises(Exception) as excinfo:
        waiter.update_password_and_wait(CLUSTER_ID)

    # the wait itself must fail (not a stub/plumbing error later in the method)
    assert "Waiter DBClusterStatus failed" in str(excinfo.value)
    stubber.assert_no_pending_responses()


def test_settles_past_propagation_window_before_success(waiter_and_stubber):
    """AC: it must not return on the first poll while the modify is still
    propagating (~12s). We assert it blocks at least that long before the wait."""
    waiter, stubber, slept = waiter_and_stubber

    stubber.add_response("modify_db_cluster", {"DBCluster": {"Status": "available"}})
    stubber.add_response("describe_db_clusters", cluster("available"))
    stubber.add_response("describe_db_clusters", cluster("available"))

    waiter.update_password_and_wait(CLUSTER_ID)

    assert sum(slept) >= 12


def test_retries_through_transient_states_then_returns(waiter_and_stubber):
    """Transient statuses during the modify (including the very state the old
    code hung waiting for) must be retried, resolving once 'available'."""
    waiter, stubber, _ = waiter_and_stubber

    stubber.add_response("modify_db_cluster", {"DBCluster": {"Status": "modifying"}})
    stubber.add_response("describe_db_clusters", cluster("modifying"))
    stubber.add_response(
        "describe_db_clusters", cluster("resetting-master-credentials")
    )
    stubber.add_response("describe_db_clusters", cluster("available"))
    stubber.add_response("describe_db_clusters", cluster("available"))  # return value

    result = waiter.update_password_and_wait(CLUSTER_ID)

    assert result == [{"DBClusterIdentifier": CLUSTER_ID, "Status": "available"}]
    stubber.assert_no_pending_responses()
