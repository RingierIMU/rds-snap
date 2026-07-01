"""Behavioural tests for the snapshot wait paths in rds_snap.commands.utils (CPE-2769, #26).

These drive the real botocore ``db_cluster_snapshot_available`` waiter through a
stubbed RDS client, exercising the same acceptor logic production does, only
stubbing the AWS network boundary. See tests/conftest.py for the shared fixtures.
"""

from botocore.exceptions import ClientError, WaiterError
from click.testing import CliRunner

from rds_snap.commands import snapshot as snapshot_cli
from rds_snap.commands import utils
from tests.conftest import CLUSTER_ID, SNAPSHOT_ID, cluster, snapshot

# The waiter budget both copy_rds_snapshot and create_rds_snapshot must use on the
# wait=True path: delay 30s x 120 attempts = 3600s (1h), matching restore_cluster.
EXPECTED_SNAPSHOT_WAITER_MAX_ATTEMPTS = 120

SOURCE_ARN = "arn:aws:rds:eu-west-1:111122223333:cluster-snapshot:src"
TARGET_KMS = "arn:aws:kms:eu-west-1:111122223333:key/abcd"


def _copying_snapshot():
    """A copy_db_cluster_snapshot response (freshly-initiated copy)."""
    return {
        "DBClusterSnapshot": {
            "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
            "DBClusterIdentifier": CLUSTER_ID,
            "Status": "copying",
        }
    }


def test_copy_returns_snapshot_when_copy_completes(stubbed_rds, utils_no_sleep):
    """A copy that settles to 'available' returns the snapshot dict, as before."""
    rds, stubber = stubbed_rds

    stubber.add_response("copy_db_cluster_snapshot", _copying_snapshot())
    stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))
    stubber.add_response("describe_db_cluster_snapshots", snapshot("available"))

    result = utils.copy_rds_snapshot(SNAPSHOT_ID, SOURCE_ARN, TARGET_KMS, True, rds)

    assert result["DBClusterSnapshotIdentifier"] == SNAPSHOT_ID
    stubber.assert_no_pending_responses()


def test_copy_raises_and_uses_full_hour_budget_when_stuck_copying(
    stubbed_rds, utils_no_sleep
):
    """CPE-2769 regression: a copy that never leaves 'copying' must propagate the
    waiter timeout (not swallow it and return None), and must poll for the full
    1h budget (delay 30 x 120) before giving up — not the old 1000s ceiling."""
    rds, stubber = stubbed_rds

    stubber.add_response("copy_db_cluster_snapshot", _copying_snapshot())
    for _ in range(EXPECTED_SNAPSHOT_WAITER_MAX_ATTEMPTS):
        stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))

    try:
        utils.copy_rds_snapshot(SNAPSHOT_ID, SOURCE_ARN, TARGET_KMS, True, rds)
        raised = None
    except Exception as e:  # noqa: BLE001 - the test asserts on the propagated error
        raised = e

    assert isinstance(raised, WaiterError), "timeout must propagate, not return None"
    assert "Max attempts exceeded" in str(raised)
    # exactly 120 polls consumed pins the budget: a 100-attempt cap leaves 20 pending
    stubber.assert_no_pending_responses()


def test_copy_polls_at_the_30s_budget_delay(stubbed_rds, utils_no_sleep):
    """AC1 pins Delay as well as MaxAttempts: the waiter must poll at 30s intervals.
    utils_no_sleep records botocore's per-poll delay, so a shrink-Delay regression
    (a too-short budget in a different guise — the CPE-2769 bug class) is caught,
    not just a change to the attempt count."""
    rds, stubber = stubbed_rds
    poll_delays = utils_no_sleep

    stubber.add_response("copy_db_cluster_snapshot", _copying_snapshot())
    stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))
    stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))
    stubber.add_response("describe_db_cluster_snapshots", snapshot("available"))

    utils.copy_rds_snapshot(SNAPSHOT_ID, SOURCE_ARN, TARGET_KMS, True, rds)

    assert poll_delays, "the waiter must sleep between polls"
    assert all(
        d == 30 for d in poll_delays
    ), f"expected the 30s per-poll budget, got {poll_delays}"


def test_create_raises_and_uses_full_hour_budget_when_stuck_copying(
    stubbed_rds, utils_no_sleep
):
    """create_rds_snapshot has the identical defect (latent today because source
    creation is fast). A snapshot that never becomes 'available' must propagate
    the waiter timeout over the full 1h budget, not swallow it and return None."""
    rds, stubber = stubbed_rds

    stubber.add_response(
        "describe_db_clusters", cluster("available")
    )  # cluster precheck
    stubber.add_response(
        "create_db_cluster_snapshot",
        {
            "DBClusterSnapshot": {
                "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
                "DBClusterIdentifier": CLUSTER_ID,
                "Status": "creating",
            }
        },
    )
    for _ in range(EXPECTED_SNAPSHOT_WAITER_MAX_ATTEMPTS):
        stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))

    try:
        utils.create_rds_snapshot(CLUSTER_ID, SNAPSHOT_ID, True, rds)
        raised = None
    except Exception as e:  # noqa: BLE001
        raised = e

    assert isinstance(raised, WaiterError), "timeout must propagate, not return None"
    assert "Max attempts exceeded" in str(raised)
    stubber.assert_no_pending_responses()


def test_create_returns_snapshot_when_creation_completes(stubbed_rds, utils_no_sleep):
    """A create that settles to 'available' still returns the snapshot dict; the
    success return must survive removing the timeout-skippable else: branch."""
    rds, stubber = stubbed_rds

    stubber.add_response("describe_db_clusters", cluster("available"))
    stubber.add_response(
        "create_db_cluster_snapshot",
        {
            "DBClusterSnapshot": {
                "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
                "DBClusterIdentifier": CLUSTER_ID,
                "Status": "creating",
            }
        },
    )
    stubber.add_response("describe_db_cluster_snapshots", snapshot("creating"))
    stubber.add_response("describe_db_cluster_snapshots", snapshot("available"))

    result = utils.create_rds_snapshot(CLUSTER_ID, SNAPSHOT_ID, True, rds)

    assert result["DBClusterSnapshotIdentifier"] == SNAPSHOT_ID
    stubber.assert_no_pending_responses()


def test_restore_cluster_refuses_when_source_snapshot_not_available(
    stubbed_rds, utils_no_sleep
):
    """Belt-and-braces (AC4): if the source snapshot is still 'copying' (or any
    non-'available' state), restore_cluster must fail early with a clear error
    rather than letting botocore raise InvalidDBClusterSnapshotStateFault deep in
    the restore call."""
    rds, stubber = stubbed_rds

    stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))

    try:
        utils.restore_cluster(
            SNAPSHOT_ID,
            CLUSTER_ID,
            "subnet-grp",
            "sg-123",
            "param-grp",
            "master-pw",
            "db.r6g.large",
            rds,
        )
        raised = None
    except Exception as e:  # noqa: BLE001
        raised = e

    assert raised is not None, "restore must refuse a non-available snapshot"
    assert not isinstance(
        raised, ClientError
    ), "should fail early with a clear error, not a deep botocore fault"
    msg = str(raised)
    assert "available" in msg and "copying" in msg
    # only the precondition lookup ran; we never reached the restore machinery
    stubber.assert_no_pending_responses()


def test_copy_command_exits_nonzero_when_snapshot_stuck_copying(
    stubbed_rds, utils_no_sleep, monkeypatch
):
    """AC3: `snapshot copy --wait` must exit non-zero (so a `set -e` orchestrator
    halts before restore) when the copy never becomes 'available' — the CLI must
    not swallow the propagated waiter error and exit 0."""
    rds, stubber = stubbed_rds

    monkeypatch.setattr(snapshot_cli, "get_kms_client", lambda profile: object())
    monkeypatch.setattr(snapshot_cli, "get_kms_arn", lambda alias, kms: TARGET_KMS)
    monkeypatch.setattr(snapshot_cli, "get_rds_client", lambda profile: rds)
    monkeypatch.setattr(
        snapshot_cli,
        "get_rds_snapshot",
        lambda sid, r: [{"DBClusterSnapshotArn": SOURCE_ARN}],
    )

    stubber.add_response("copy_db_cluster_snapshot", _copying_snapshot())
    for _ in range(EXPECTED_SNAPSHOT_WAITER_MAX_ATTEMPTS):
        stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))

    result = CliRunner().invoke(
        snapshot_cli.copy,
        [
            "--source-profile",
            "src",
            "--target-profile",
            "tgt",
            "--snapshot-identifier",
            SNAPSHOT_ID,
            "--target-kms-alias",
            "my-kms",
            "--wait",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, WaiterError)


def test_create_command_exits_nonzero_when_snapshot_stuck_copying(
    stubbed_rds, utils_no_sleep, monkeypatch
):
    """AC3, create side: `snapshot create --wait` must likewise exit non-zero when
    the snapshot never becomes 'available'."""
    rds, stubber = stubbed_rds

    monkeypatch.setattr(snapshot_cli, "get_rds_client", lambda profile: rds)

    stubber.add_response("describe_db_clusters", cluster("available"))
    stubber.add_response(
        "create_db_cluster_snapshot",
        {
            "DBClusterSnapshot": {
                "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
                "DBClusterIdentifier": CLUSTER_ID,
                "Status": "creating",
            }
        },
    )
    for _ in range(EXPECTED_SNAPSHOT_WAITER_MAX_ATTEMPTS):
        stubber.add_response("describe_db_cluster_snapshots", snapshot("copying"))

    result = CliRunner().invoke(
        snapshot_cli.create,
        [
            "--cluster",
            CLUSTER_ID,
            "--snapshot-identifier",
            SNAPSHOT_ID,
            "--wait",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, WaiterError)
