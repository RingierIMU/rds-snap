from rds_snap.commands.waiters import (
    DBClusterWaiter,
    DBInstanceWaiter,
    get_rds_cluster,
    get_rds_snapshot,
)
import boto3, logging


def get_session(profile: str) -> boto3.Session:
    """Returns a boto3 session"""
    if profile:
        return boto3.Session(profile_name=profile)
    else:
        return boto3.Session()


def get_ec2_client(profile: str):
    """Returns the ec2 client"""
    return get_session(profile).resource("ec2")


def get_rds_client(profile: str):
    """Returns the rds client"""
    return get_session(profile).client("rds")


def get_kms_client(profile: str):
    """Returns the kms client"""
    return get_session(profile).client("kms")


def get_ec2_instances(project: str, ec2):
    """Return ec2 instances for project"""
    if project:
        filters = [{"Name": "tag:PROJECT", "Values": [project]}]
        return ec2.instances.filter(Filters=filters)
    else:
        return ec2.instances.all()


def has_pending_snapshot(volume) -> bool:
    """Returns if the volume has pending snapshots"""
    xs = list(volume.snapshots.all())
    return bool(xs and xs[0].state == "pending")


# kms
def get_kms_arn(kms_alias: str, kms):
    """Return kms_arn for associated kms_alias"""
    return kms.describe_key(KeyId="alias/{}".format(kms_alias))["KeyMetadata"]["Arn"]


# snapshots
def get_rds_snapshots(rds):
    """Return the rds cluster snapshots"""
    return rds.describe_db_cluster_snapshots()["DBClusterSnapshots"]


def create_rds_snapshot(
    cluster_identifier: str, snapshot_identifier: str, wait: bool, rds
):
    """Create rds snapshot"""
    logger = logging.getLogger("create_rds_snapshot")
    xs = rds.create_db_cluster_snapshot(
        DBClusterSnapshotIdentifier=snapshot_identifier,
        DBClusterIdentifier=cluster_identifier,
    )["DBClusterSnapshot"]
    if not wait:
        return xs
    else:
        waiter = rds.get_waiter("db_cluster_snapshot_available")
        logger.warning(
            "Waiting for snapshot {} to be created...".format(
                xs["DBClusterSnapshotIdentifier"]
            )
        )
        try:
            waiter.wait(
                DBClusterSnapshotIdentifier=xs["DBClusterSnapshotIdentifier"],
                SnapshotType="manual",
                Filters=[
                    {
                        "Name": "db-cluster-id",
                        "Values": [
                            xs["DBClusterIdentifier"],
                        ],
                    },
                ],
                WaiterConfig={"Delay": 10, "MaxAttempts": 100},
            )
        except:
            logger.exception(
                "Unable to wait for snapshot {} to be created for cluster {}".format(
                    xs["DBClusterSnapshotIdentifier"], xs["DBClusterIdentifier"]
                )
            )
        else:
            return xs


def delete_rds_snapshot(snapshot_identifier: str, rds):
    """Delete rds snapshot identified by snapshot_identifier"""
    return rds.delete_db_cluster_snapshot(
        DBClusterSnapshotIdentifier=snapshot_identifier
    )["DBClusterSnapshot"]


def share_rds_snapshot(snapshot_identifier: str, acc_number: str, rds):
    """Share rds snapshot with this aws account"""
    return rds.modify_db_cluster_snapshot_attribute(
        DBClusterSnapshotIdentifier=snapshot_identifier,
        AttributeName="restore",
        ValuesToAdd=[
            acc_number,
        ],
    )["DBClusterSnapshotAttributesResult"]


def copy_rds_snapshot(
    target_snapshot_identifier: str,
    source_snapshot_identifier: str,
    target_kms: str,
    wait: bool,
    rds,
):
    """Copy snapshot from source_snapshot_identifier to target_snapshot_identifier and encrypt using target_kms"""
    logger = logging.getLogger("copy_rds_snapshot")
    xs = rds.copy_db_cluster_snapshot(
        SourceDBClusterSnapshotIdentifier=source_snapshot_identifier,
        TargetDBClusterSnapshotIdentifier=target_snapshot_identifier,
        KmsKeyId=target_kms,
    )["DBClusterSnapshot"]
    if not wait:
        return xs
    else:
        waiter = rds.get_waiter("db_cluster_snapshot_available")
        logger.warning(
            "Waiting for snapshot {} to be created...".format(
                xs["DBClusterSnapshotIdentifier"]
            )
        )
        try:
            waiter.wait(
                DBClusterSnapshotIdentifier=xs["DBClusterSnapshotIdentifier"],
                SnapshotType="manual",
                Filters=[
                    {
                        "Name": "db-cluster-id",
                        "Values": [
                            xs["DBClusterIdentifier"],
                        ],
                    },
                ],
                WaiterConfig={"Delay": 10, "MaxAttempts": 100},
            )
        except:
            logger.exception(
                "Unable to wait for snapshot {} to be created for cluster {}".format(
                    xs["DBClusterSnapshotIdentifier"], xs["DBClusterIdentifier"]
                )
            )
        else:
            return xs


# clusters
def get_rds_clusters(cluster_identifier: str, rds):
    """Return rds clusters"""
    if cluster_identifier:
        return rds.describe_db_clusters(
            DBClusterIdentifier=cluster_identifier,
        )["DBClusters"]
    else:
        return rds.describe_db_clusters()["DBClusters"]


def restore_cluster(
    snapshot_identifier: str,
    cluster_identifier: str,
    db_subnet_group_name: str,
    vpc_security_group_id: str,
    db_cluster_parameter_group_name: str,
    db_cluster_master_password: str,
    db_instance_class: str,
    rds,
):
    """Restore cluster from snapshot:
    Default is to create a cluster with one instance and wait for all operations to complete before continuing
    """
    logger = logging.getLogger("restore_cluster")
    if not snapshot_identifier:
        raise Exception(
            "snapshot identifier required to specify from which snapshot cluster should be created"
        )
    snapshot_info = get_rds_snapshot(snapshot_identifier, rds)[0]
    if not cluster_identifier:
        logger.warning(
            f"Will use the cluster name from which the snapshot was created by default"
        )
        cluster_identifier = snapshot_info["DBClusterIdentifier"]
    # create cluster
    db_cluster = DBClusterWaiter(
        rds,
        cluster_config={
            "snapshotIdentifier": snapshot_identifier,
            "dbClusterInstanceIdentifier": cluster_identifier + "-instance-0",
            "subnetGroupName": db_subnet_group_name,
            "vpcSecurityGroupId": vpc_security_group_id,
            "dbClusterParameterGroupName": db_cluster_parameter_group_name,
            "masterPassword": db_cluster_master_password,
        },
        cluster_identifier=cluster_identifier,
    )
    db_cluster_info = db_cluster.create_cluster_and_wait(
        db_cluster_identifier=cluster_identifier
    )[0]

    # create db cluster instance
    db_cluster_instance_identifier = (
        db_cluster_info["DBClusterIdentifier"] + "-instance-0"
    )
    db_instance = DBInstanceWaiter(
        rds,
        instance_config={
            "dbClusterIdentifier": db_cluster_info["DBClusterIdentifier"],
            "dbClusterInstanceIdentifier": db_cluster_instance_identifier,
            "dbInstanceClass": db_instance_class,
        },
    )
    db_instance_info = db_instance.create_instance_and_wait(
        db_cluster_instance_identifier
    )
    if not db_instance_info:
        raise Exception(
            f"Failed to create db instance {db_cluster_instance_identifier} for cluster {cluster_identifier}"
        )

    # update the master user password
    db_cluster_updated_info = db_cluster.update_password_and_wait(
        db_cluster_info["DBClusterIdentifier"]
    )
    if not db_cluster_updated_info:
        raise Exception(f"Failed to reset password for cluster {cluster_identifier}")


def destroy_cluster(cluster_identifier, snapshot_identifier, wait, rds):
    """Destroy db cluster
    Default is to destroy without creating a snapshot. If snapshot identifier is supplied, we create a snapshot before cluster termination
    """
    logger = logging.getLogger("destroy_cluster")
    if not cluster_identifier:
        raise Exception("cluster identifier required")
    db_cluster_info = get_rds_cluster(cluster_identifier, rds)[0]
    snapshot_response = create_rds_snapshot(
        cluster_identifier, snapshot_identifier, True, rds
    )
    if not snapshot_response:
        raise Exception(
            f"Failed to create snapshot of {cluster_identifier} with identifier {snapshot_identifier}"
        )
    # delete db instances
    db_cluster_instances = db_cluster_info["DBClusterMembers"]
    for instance in db_cluster_instances:
        db_instance = DBInstanceWaiter(
            rds_client=rds,
            polling_config={"delay": 30, "maxAttempts": 60},
            instance_config={
                "dbClusterIdentifier": db_cluster_info["DBClusterIdentifier"],
                "dbClusterInstanceIdentifier": instance["DBInstanceIdentifier"],
            },
        )
        db_instance.delete_instance_and_wait(
            db_instance_identifier=instance["DBInstanceIdentifier"],
            skip_snapshot=True,
            wait=False,
        )

    db_cluster = DBClusterWaiter(
        rds_client=rds,
        creation=False,
        cluster_config={},
        cluster_identifier=cluster_identifier,
        polling_config={"delay": 30, "maxAttempts": 60},
    )
    db_cluster.delete_cluster_and_wait(
        db_cluster_identifier=cluster_identifier, skip_snapshot=True, wait=wait
    )
