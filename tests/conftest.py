import time

import boto3
import pytest
from botocore.stub import Stubber

from rds_snap.commands import waiters

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
