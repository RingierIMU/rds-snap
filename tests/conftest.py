import time

import boto3
import pytest
from botocore.stub import Stubber

from rds_snap.commands import utils, waiters

CLUSTER_ID = "prod-horizon"
SNAPSHOT_ID = "prod-horizon-snap"
MASTER_PASSWORD = "s3cr3t-pw"


def _snapshot_response(snapshot_id=SNAPSHOT_ID, cluster_id=CLUSTER_ID):
    """Minimal describe_db_cluster_snapshots payload for DBClusterWaiter.__init__."""
    return {
        "DBClusterSnapshots": [
            {
                "DBClusterSnapshotIdentifier": snapshot_id,
                "DBClusterIdentifier": cluster_id,
                "Engine": "aurora-mysql",
                "EngineVersion": "8.0.mysql_aurora.3.04.0",
                "KmsKeyId": "arn:aws:kms:eu-west-1:111122223333:key/abcd",
            }
        ]
    }


def cluster(status, cluster_id=CLUSTER_ID):
    """A single-cluster describe_db_clusters payload with the given status."""
    return {"DBClusters": [{"DBClusterIdentifier": cluster_id, "Status": status}]}


def snapshot(status, snapshot_id=SNAPSHOT_ID, cluster_id=CLUSTER_ID):
    """A single-snapshot describe_db_cluster_snapshots payload with the given status.

    This is what the built-in db_cluster_snapshot_available waiter polls; 'copying'
    /'creating' are (implicit) retry states, 'available' is success.
    """
    return {
        "DBClusterSnapshots": [
            {
                "DBClusterSnapshotIdentifier": snapshot_id,
                "DBClusterIdentifier": cluster_id,
                "Status": status,
            }
        ]
    }


@pytest.fixture
def rds_client():
    return boto3.client(
        "rds",
        region_name="eu-west-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def slept(monkeypatch):
    """Neutralise real waiting.

    - Record the function-body settle sleeps (waiters.sleep) so tests can assert
      the method blocks for the propagation window.
    - Silence botocore's internal per-poll waiter delay (time.sleep) so the real
      waiter machinery runs instantly.
    """
    recorded = []
    monkeypatch.setattr(waiters, "sleep", lambda seconds: recorded.append(seconds))
    monkeypatch.setattr(time, "sleep", lambda *args, **kwargs: None)
    return recorded


@pytest.fixture
def utils_no_sleep(monkeypatch):
    """Neutralise real waiting on the utils snapshot paths so the real
    db_cluster_snapshot_available waiter runs instantly:

    - the settle sleep(5) imported into rds_snap.commands.utils -> no-op, and
    - botocore's internal per-poll waiter delay (time.sleep) -> recorded, not slept.

    Returns the list of per-poll delays (seconds) botocore requested, so a test
    can assert the waiter budget's Delay, not only its MaxAttempts.
    """
    poll_delays = []
    monkeypatch.setattr(utils, "sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        time, "sleep", lambda seconds=0, *args, **kwargs: poll_delays.append(seconds)
    )
    return poll_delays


@pytest.fixture
def stubbed_rds(rds_client):
    """A botocore Stubber over a real rds client, yielded as (rds_client, stubber).

    The test queues each API response its scenario needs, in call order; the real
    boto3 waiter machinery consumes them exactly as production does.
    """
    stubber = Stubber(rds_client)
    stubber.activate()
    yield rds_client, stubber
    stubber.deactivate()


@pytest.fixture
def waiter_and_stubber(rds_client, slept):
    """A DBClusterWaiter wired to a botocore Stubber.

    Yields (waiter, stubber, slept). The snapshot lookup DBClusterWaiter.__init__
    performs is pre-queued; the test queues the modify_db_cluster and
    describe_db_clusters responses its scenario needs, in call order.
    """
    stubber = Stubber(rds_client)
    stubber.activate()
    stubber.add_response("describe_db_cluster_snapshots", _snapshot_response())
    waiter = waiters.DBClusterWaiter(
        rds_client,
        {"snapshotIdentifier": SNAPSHOT_ID, "masterPassword": MASTER_PASSWORD},
        CLUSTER_ID,
        creation=True,
        polling_config={"delay": 0, "maxAttempts": 5},
    )
    yield waiter, stubber, slept
    stubber.deactivate()
