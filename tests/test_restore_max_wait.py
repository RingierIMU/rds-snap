"""Tests for `cluster restore --max-wait-minutes` (CPE-2776, docker-downstream-agent#131).

The restore waiters had fixed ceilings (cluster 120 x 30s = 60m, instance
240 x 30s = 120m). An Aurora restore that ran past 60m failed the caller with no
way to widen the budget. These tests pin the helper that sizes the budget, prove
a small budget really stops the real botocore waiter, and prove the CLI option is
wired through to restore_cluster.
"""

import pytest
from click.testing import CliRunner

from rds_snap.commands import cluster as cluster_cmd
from rds_snap.commands import utils, waiters
from tests.conftest import (
    CLUSTER_ID,
    SNAPSHOT_ID,
    MASTER_PASSWORD,
    _snapshot_response,
    cluster,
)


@pytest.mark.parametrize(
    "minutes, default, expected",
    [
        (None, 120, 120),
        (None, 240, 240),
        (85, 120, 170),
        (85, 240, 170),
        (1, 120, 2),
    ],
)
def test_polling_config_for(minutes, default, expected):
    assert utils.polling_config_for(minutes, default) == {
        "delay": 30,
        "maxAttempts": expected,
    }


@pytest.mark.parametrize(
    "remaining, expected", [(35 * 60, 70), (35 * 60 - 1, 70), (1, 1), (0, 1), (-600, 1)]
)
def test_polling_config_for_remaining_seconds(remaining, expected):
    assert utils.polling_config_for(85, 240, remaining_seconds=remaining) == {
        "delay": 30,
        "maxAttempts": expected,
    }


def test_polling_config_for_remaining_ignored_when_unset():
    assert utils.polling_config_for(None, 240, remaining_seconds=0) == {
        "delay": 30,
        "maxAttempts": 240,
    }


def test_polling_config_for_rounds_up_and_never_below_one():
    # 7 minutes at a 60s delay -> 7 attempts; 1 minute at a 90s delay -> ceil(0.67) = 1
    assert utils.polling_config_for(7, 120, delay=60)["maxAttempts"] == 7
    assert utils.polling_config_for(1, 120, delay=90)["maxAttempts"] == 1


def test_cluster_waiter_stops_at_small_max_attempts(rds_client, slept):
    """A DBClusterWaiter built with maxAttempts=3 must give up after exactly 3
    describe calls while the cluster stays 'creating' (not keep going to 120)."""
    from botocore.stub import Stubber

    stubber = Stubber(rds_client)
    stubber.activate()
    stubber.add_response("describe_db_cluster_snapshots", _snapshot_response())
    waiter = waiters.DBClusterWaiter(
        rds_client,
        {
            "snapshotIdentifier": SNAPSHOT_ID,
            "masterPassword": MASTER_PASSWORD,
            "subnetGroupName": "sg",
            "vpcSecurityGroupId": "sg-123",
            "dbClusterParameterGroupName": "pg",
        },
        CLUSTER_ID,
        creation=True,
        polling_config={"delay": 0, "maxAttempts": 3},
    )
    stubber.add_response(
        "restore_db_cluster_from_snapshot",
        {"DBCluster": {"DBClusterIdentifier": CLUSTER_ID, "Status": "creating"}},
    )
    for _ in range(3):
        stubber.add_response("describe_db_clusters", cluster("creating"))

    with pytest.raises(Exception) as excinfo:
        waiter.create_cluster_and_wait(CLUSTER_ID)

    assert "Max attempts exceeded" in str(excinfo.value)
    # all 3 queued polls consumed, and no 4th was attempted (Stubber would
    # raise UnStubbedResponseError on an extra call instead of WaiterError)
    stubber.assert_no_pending_responses()
    stubber.deactivate()


class _Recorder:
    """Stand-in for DBClusterWaiter/DBInstanceWaiter that records polling_config
    and advances a fake clock by the configured minutes during each wait."""

    def __init__(self, sink, clock, cluster_wait_minutes, *args, **kwargs):
        sink.append(kwargs["polling_config"])
        self.clock = clock
        self.cluster_wait_minutes = cluster_wait_minutes

    def create_cluster_and_wait(self, db_cluster_identifier):
        self.clock[0] += self.cluster_wait_minutes * 60
        return [{"DBClusterIdentifier": db_cluster_identifier}]

    def create_instance_and_wait(self, _id):
        return [{"DBInstanceIdentifier": _id}]

    def update_password_and_wait(self, _id):
        return [{"DBClusterIdentifier": _id}]


def _run_restore(monkeypatch, cluster_wait_minutes=0, **kwargs):
    seen = []
    clock = [1000.0]
    monkeypatch.setattr(utils.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(utils, "get_rds_snapshot", lambda *_: [{"Status": "available"}])
    make = lambda *a, **k: _Recorder(seen, clock, cluster_wait_minutes, *a, **k)
    monkeypatch.setattr(utils, "DBClusterWaiter", make)
    monkeypatch.setattr(utils, "DBInstanceWaiter", make)
    utils.restore_cluster(
        SNAPSHOT_ID,
        CLUSTER_ID,
        "sg",
        "sg-123",
        "pg",
        "pw",
        "db.r6g.large",
        None,
        **kwargs,
    )
    return seen


def test_restore_cluster_default_keeps_built_in_ceilings(monkeypatch):
    # even a slow cluster wait must not shrink the default instance ceiling
    assert _run_restore(monkeypatch, cluster_wait_minutes=50) == [
        {"delay": 30, "maxAttempts": 120},
        {"delay": 30, "maxAttempts": 240},
    ]


def test_restore_cluster_max_wait_full_budget_when_no_time_spent(monkeypatch):
    assert _run_restore(monkeypatch, max_wait_minutes=85) == [
        {"delay": 30, "maxAttempts": 170},
        {"delay": 30, "maxAttempts": 170},
    ]


def test_restore_cluster_max_wait_is_shared_deadline(monkeypatch):
    """85m budget, cluster wait takes 50m -> instance waiter gets the 35m left
    (ceil(35*60/30) = 70 attempts), not a fresh 85m."""
    assert _run_restore(monkeypatch, cluster_wait_minutes=50, max_wait_minutes=85) == [
        {"delay": 30, "maxAttempts": 170},
        {"delay": 30, "maxAttempts": 70},
    ]


def test_restore_cluster_spent_budget_still_gets_one_attempt(monkeypatch):
    assert _run_restore(monkeypatch, cluster_wait_minutes=90, max_wait_minutes=85) == [
        {"delay": 30, "maxAttempts": 170},
        {"delay": 30, "maxAttempts": 1},
    ]


REQUIRED_ARGS = [
    "--cluster-identifier",
    CLUSTER_ID,
    "--db-subnet-group-name",
    "sg",
    "--vpc-security-group-id",
    "sg-123",
    "--db-cluster-parameter-group-name",
    "pg",
    "--db-cluster-master-password",
    "pw",
    "--db-instance-class",
    "db.r6g.large",
]


def test_restore_help_lists_max_wait_minutes():
    result = CliRunner().invoke(cluster_cmd.cluster, ["restore", "--help"])
    assert result.exit_code == 0
    assert "--max-wait-minutes" in result.output
    assert "password-reset" in result.output


def test_restore_rejects_zero_max_wait_minutes(monkeypatch):
    monkeypatch.setattr(cluster_cmd, "restore_cluster", lambda *a, **k: None)
    result = CliRunner().invoke(
        cluster_cmd.cluster,
        ["restore", *REQUIRED_ARGS, "--max-wait-minutes", "0"],
    )
    assert result.exit_code == 2
    assert "Invalid value for '--max-wait-minutes'" in result.output
    assert "not in the range" in result.output


@pytest.mark.parametrize(
    "argv, expected", [([], None), (["--max-wait-minutes", "85"], 85)]
)
def test_restore_passes_max_wait_minutes(monkeypatch, argv, expected):
    calls = []
    monkeypatch.setattr(cluster_cmd, "get_rds_client", lambda profile: "rds")
    monkeypatch.setattr(
        cluster_cmd, "restore_cluster", lambda *a, **k: calls.append((a, k))
    )
    result = CliRunner().invoke(cluster_cmd.cluster, ["restore", *REQUIRED_ARGS, *argv])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[-1] == "rds"
    assert kwargs == {"max_wait_minutes": expected}
