from time import perf_counter
from botocore.exceptions import WaiterError
from botocore.waiter import WaiterModel
from botocore.waiter import create_waiter_with_client
import logging


def get_rds_cluster(cluster_identifier: str, rds):
    """Return single rds cluster"""
    return rds.describe_db_clusters(
        DBClusterIdentifier=cluster_identifier,
    )["DBClusters"]


def get_rds_snapshot(snapshot_identifier: str, rds):
    """Return single rds cluster snapshot"""
    return rds.describe_db_cluster_snapshots(
        DBClusterSnapshotIdentifier=snapshot_identifier,
    )["DBClusterSnapshots"]


def seconds_to_duration(seconds):
    """Return a string representation of the duration in seconds"""
    h = seconds // 3600
    m = seconds % 3600 // 60
    s = seconds % 3600 % 60
    return (
        f"{h:.0f}h:{m:02.0f}m:{s:02.0f}s"
        if h > 0
        else (f"{m:.0f}m:{s:02.0f}s" if m > 0 else f"{s:.0f}s")
    )


class DBClusterWaiter:
    def __init__(
        self,
        rds_client,
        cluster_config,
        cluster_identifier,
        creation=True,  # if True we require cluster_config, if False we do not
        polling_config={"delay": 30, "maxAttempts": 60},
    ) -> None:
        self.logger = logging.getLogger("db_cluster")

        self.rds_client = rds_client
        self.cluster_config = (
            cluster_config if creation else {"dbClusterInstanceIdentifier": ""}
        )
        self.cluster_identifier = cluster_identifier
        self.snapshot_info = (
            get_rds_snapshot(cluster_config["snapshotIdentifier"], rds_client)[0]
            if creation
            else None
        )

        self.cluster_running_waiter_model = WaiterModel(
            {
                "version": 2,
                "waiters": {
                    "DBClusterStatus": {
                        "operation": "DescribeDBClusters",
                        "delay": polling_config["delay"],
                        "maxAttempts": polling_config["maxAttempts"],
                        "acceptors": [
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "success",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'available'",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'modifying'",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'creating'",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'resetting-master-credentials'",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'backing-up'",
                            },
                            {
                                "expected": "deleted",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "deleting",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "failed",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "inaccessible-encryption-credentials",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "stopped",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                        ],
                    }
                },
            }
        )

        self.cluster_update_start_waiter_model = WaiterModel(
            {
                "version": 2,
                "waiters": {
                    "DBClusterStatus": {
                        "operation": "DescribeDBClusters",
                        "delay": 3,
                        "maxAttempts": 120,
                        "acceptors": [
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'available'",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "success",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'resetting-master-credentials'",
                            },
                            {
                                "expected": "deleted",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "deleting",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "failed",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "inaccessible-encryption-credentials",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "stopped",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                        ],
                    }
                },
            }
        )

        self.cluster_stopped_waiter_model = WaiterModel(
            {
                "version": 2,
                "waiters": {
                    "DBClusterStatus": {
                        "operation": "DescribeDBClusters",
                        "delay": polling_config["delay"],
                        "maxAttempts": polling_config["maxAttempts"],
                        "acceptors": [
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "success",
                                "argument": f"length(DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}']) == `0`",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBClusters[?DBClusterIdentifier=='{self.cluster_identifier}'].Status | [0] == 'deleting'",
                            },
                            {
                                "expected": "DBClusterNotFound",
                                "matcher": "error",
                                "state": "success",
                            },
                            {
                                "expected": "deleting",
                                "matcher": "pathAny",
                                "state": "retry",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "creating",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "modifying",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "rebooting",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                            {
                                "expected": "resetting-master-credentials",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBClusters[].Status",
                            },
                        ],
                    }
                },
            }
        )

        self.running = create_waiter_with_client(
            "DBClusterStatus", self.cluster_running_waiter_model, rds_client
        )
        self.modifying_start = create_waiter_with_client(
            "DBClusterStatus", self.cluster_update_start_waiter_model, rds_client
        )
        self.modifying_stop = create_waiter_with_client(
            "DBClusterStatus", self.cluster_running_waiter_model, rds_client
        )
        self.stopped = create_waiter_with_client(
            "DBClusterStatus", self.cluster_stopped_waiter_model, rds_client
        )

    def create_cluster_and_wait(self, db_cluster_identifier):
        if not db_cluster_identifier:
            db_cluster_identifier = self.snapshot_info["DBClusterIdentifier"]
        self.logger.warning(f"Creating cluster {db_cluster_identifier}")
        restore_db_cluster_response = self.rds_client.restore_db_cluster_from_snapshot(
            DBClusterIdentifier=db_cluster_identifier,
            SnapshotIdentifier=self.snapshot_info["DBClusterSnapshotIdentifier"],
            Engine=self.snapshot_info["Engine"],
            EngineVersion=self.snapshot_info["EngineVersion"],
            DBSubnetGroupName=self.cluster_config["subnetGroupName"],
            VpcSecurityGroupIds=[
                self.cluster_config["vpcSecurityGroupId"],
            ],
            KmsKeyId=self.snapshot_info["KmsKeyId"],
            DBClusterParameterGroupName=self.cluster_config[
                "dbClusterParameterGroupName"
            ],
        )["DBCluster"]

        if not restore_db_cluster_response:
            raise Exception(
                f"Something went wrong while restoring db cluster {db_cluster_identifier} from snapshot {self.snapshot_info['DBClusterSnapshotIdentifier']}"
            )
        try:
            self.logger.warning(
                f"Waiting for cluster {db_cluster_identifier} to become available"
            )
            tic = perf_counter()
            self.running.wait()
        except WaiterError as e:
            raise Exception(e)
        else:
            toc = perf_counter()
            self.logger.warning(
                f"Cluster {db_cluster_identifier} ready in {seconds_to_duration(toc - tic)}"
            )
            return self.rds_client.describe_db_clusters(
                DBClusterIdentifier=db_cluster_identifier,
            )["DBClusters"]

    def update_password_and_wait(self, db_cluster_identifier):
        if not db_cluster_identifier:
            db_cluster_identifier = self.snapshot_info["DBClusterIdentifier"]
        self.logger.warning(f"Updating password for cluster {db_cluster_identifier}")
        modify_db_cluster_response = self.rds_client.modify_db_cluster(
            DBClusterIdentifier=db_cluster_identifier,
            ApplyImmediately=True,
            MasterUserPassword=self.cluster_config["masterPassword"],
        )["DBCluster"]

        if not modify_db_cluster_response:
            raise Exception(
                f"Something went wrong while resetting password for db cluster {db_cluster_identifier}"
            )
        try:
            # If we do not add the intermediate wait we would have to sleep for at least 12 seconds waiting for
            # the command to propagate through AWS :sadparrot:
            # Using the extra wait stage here we avoid magic variables :pray:
            tic = perf_counter()
            self.modifying_start.wait()
            toc = perf_counter()
            self.logger.warning(
                f"Waited for update command to propagate to cluster {db_cluster_identifier} in {seconds_to_duration(toc - tic)}"
            )
            tic = perf_counter()
            self.logger.warning(
                f"Waiting for cluster {db_cluster_identifier} to become available"
            )
            self.modifying_stop.wait()
        except WaiterError as e:
            raise Exception(e)
        else:
            toc = perf_counter()
            self.logger.warning(
                f"Cluster {db_cluster_identifier} ready in {seconds_to_duration(toc - tic)}"
            )
            return self.rds_client.describe_db_clusters(
                DBClusterIdentifier=db_cluster_identifier,
            )["DBClusters"]

    def delete_cluster_and_wait(
        self,
        db_cluster_identifier: str,
        db_snapshot_identifier: str = "",
        skip_snapshot: bool = False,
        wait: bool = True,
    ):
        if not db_cluster_identifier:
            raise Exception("db cluster identifier required to delete cluster")
        self.logger.warning(f"Deleting cluster {db_cluster_identifier}")
        if skip_snapshot and len(db_snapshot_identifier) == 0:
            db_cluster_response = self.rds_client.delete_db_cluster(
                DBClusterIdentifier=db_cluster_identifier,
                SkipFinalSnapshot=skip_snapshot,
            )["DBCluster"]
        elif not skip_snapshot and len(db_snapshot_identifier) > 0:
            db_cluster_response = self.rds_client.delete_db_cluster(
                DBClusterIdentifier=db_cluster_identifier,
                SkipFinalSnapshot=skip_snapshot,
                FinalDBSnapshotIdentifier=db_snapshot_identifier,
            )["DBCluster"]
        else:
            self.logger.error(
                f"Deleting cluster {db_cluster_identifier}; skip_snapshot: {skip_snapshot}; db_snapshot_identifier: {db_snapshot_identifier}"
            )
            raise Exception(
                f"Something went wrong trying to delete cluster {db_cluster_identifier}"
            )

        if not db_cluster_response:
            raise Exception(
                f"Something went wrong while deleting db cluster {db_cluster_identifier}"
            )

        if wait:
            try:
                self.logger.warning(
                    f"Waiting for cluster {db_cluster_identifier} to be deleted"
                )
                tic = perf_counter()
                self.stopped.wait()
            except WaiterError as e:
                raise Exception(e)
            else:
                toc = perf_counter()
                self.logger.warning(
                    f"Cluster {db_cluster_identifier} deleted in {seconds_to_duration(toc - tic)}"
                )
        else:
            self.logger.warning(
                f"Delete command executed for cluster {db_cluster_identifier}"
            )


class DBInstanceWaiter:
    def __init__(
        self,
        rds_client,
        instance_config,
        polling_config={"delay": 30, "maxAttempts": 60},
    ) -> None:
        self.logger = logging.getLogger("db_instance")

        self.rds_client = rds_client
        self.instance_config = instance_config
        self.cluster_info = get_rds_cluster(
            self.instance_config["dbClusterIdentifier"], rds_client
        )[0]

        self.instance_running_waiter_model = WaiterModel(
            {
                "version": 2,
                "waiters": {
                    "DBInstanceStatus": {
                        "operation": "DescribeDBInstances",
                        "delay": polling_config["delay"],
                        "maxAttempts": polling_config["maxAttempts"],
                        "acceptors": [
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "success",
                                "argument": f"DBInstances[?DBInstanceIdentifier=='{self.instance_config['dbClusterInstanceIdentifier']}'].DBInstanceStatus | [0] == 'available'",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBInstances[?DBInstanceIdentifier=='{self.instance_config['dbClusterInstanceIdentifier']}'].DBInstanceStatus | [0] == 'modifying'",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBInstances[?DBInstanceIdentifier=='{self.instance_config['dbClusterInstanceIdentifier']}'].DBInstanceStatus | [0] == 'creating'",
                            },
                            {
                                "expected": "deleted",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                            {
                                "expected": "deleting",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                            {
                                "expected": "failed",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                            {
                                "expected": "inaccessible-encryption-credentials",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                            {
                                "expected": "stopped",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                        ],
                    }
                },
            }
        )

        self.instance_stopped_waiter_model = WaiterModel(
            {
                "version": 2,
                "waiters": {
                    "DBInstanceStatus": {
                        "operation": "DescribeDBInstances",
                        "delay": polling_config["delay"],
                        "maxAttempts": polling_config["maxAttempts"],
                        "acceptors": [
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "success",
                                "argument": f"length(DBInstances[?DBInstanceIdentifier=='{self.instance_config['dbClusterInstanceIdentifier']}']) == `0`",
                            },
                            {
                                "expected": True,
                                "matcher": "path",
                                "state": "retry",
                                "argument": f"DBInstances[?DBInstanceIdentifier=='{self.instance_config['dbClusterInstanceIdentifier']}'].DBInstanceStatus | [0] == 'deleting'",
                            },
                            {
                                "expected": "DBInstanceNotFound",
                                "matcher": "error",
                                "state": "success",
                            },
                            {
                                "expected": "creating",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                            {
                                "expected": "modifying",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                            {
                                "expected": "rebooting",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                            {
                                "expected": "resetting-master-credentials",
                                "matcher": "pathAny",
                                "state": "failure",
                                "argument": "DBInstances[][DBInstanceStatus]",
                            },
                        ],
                    }
                },
            }
        )

        self.running = create_waiter_with_client(
            "DBInstanceStatus", self.instance_running_waiter_model, rds_client
        )
        self.stopped = create_waiter_with_client(
            "DBInstanceStatus", self.instance_stopped_waiter_model, rds_client
        )

    def create_instance_and_wait(self, db_instance_identifier):
        if not db_instance_identifier:
            db_instance_identifier = (
                self.cluster_info["DBClusterIdentifier"] + "-instance-0"
            )
        self.logger.warning(f"Creating cluster instance {db_instance_identifier}")
        db_cluster_instance_response = self.rds_client.create_db_instance(
            DBInstanceIdentifier=db_instance_identifier,
            DBInstanceClass=self.instance_config["dbInstanceClass"],
            Engine=self.cluster_info["Engine"],
            DBClusterIdentifier=self.cluster_info["DBClusterIdentifier"],
        )["DBInstance"]

        if not db_cluster_instance_response:
            raise Exception(
                f"Something went wrong while creating db cluster instance {db_instance_identifier} for cluster {self.cluster_info['DBClusterIdentifier']}"
            )
        try:
            self.logger.warning(
                f"Waiting for cluster instance {db_instance_identifier} to become available"
            )
            tic = perf_counter()
            self.running.wait()
        except WaiterError as e:
            raise Exception(e)
        else:
            toc = perf_counter()
            self.logger.warning(
                f"Cluster instance {db_instance_identifier} ready in {seconds_to_duration(toc - tic)}"
            )
            return self.rds_client.describe_db_instances(
                DBInstanceIdentifier=db_instance_identifier,
            )["DBInstances"]

    def delete_instance_and_wait(
        self,
        db_instance_identifier: str,
        db_snapshot_identifier: str = "",
        skip_snapshot: bool = False,
        wait: bool = True,
    ):
        if not db_instance_identifier:
            raise Exception("db instance identifier required to delete instance")
        self.logger.warning(f"Deleting cluster instance {db_instance_identifier}")
        if skip_snapshot and len(db_snapshot_identifier) == 0:
            db_cluster_instance_response = self.rds_client.delete_db_instance(
                DBInstanceIdentifier=db_instance_identifier,
                SkipFinalSnapshot=skip_snapshot,
            )["DBInstance"]
        elif not skip_snapshot and len(db_snapshot_identifier) > 0:
            db_cluster_instance_response = self.rds_client.delete_db_instance(
                DBInstanceIdentifier=db_instance_identifier,
                SkipFinalSnapshot=skip_snapshot,
                FinalDBSnapshotIdentifier=db_snapshot_identifier,
            )["DBInstance"]
        else:
            raise Exception(
                f"Something went wrong trying to delete instance {db_instance_identifier}"
            )

        if not db_cluster_instance_response:
            raise Exception(
                f"Something went wrong while deleting db cluster instance {db_instance_identifier} for cluster {self.cluster_info['DBClusterIdentifier']}"
            )
        if wait:
            try:
                self.logger.warning(
                    f"Waiting for cluster instance {db_instance_identifier} to be deleted"
                )
                tic = perf_counter()
                self.stopped.wait()
            except WaiterError as e:
                raise Exception(e)
            else:
                toc = perf_counter()
                self.logger.warning(
                    f"Cluster instance {db_instance_identifier} deleted in {seconds_to_duration(toc - tic)}"
                )
        else:
            self.logger.warning(
                f"Delete command executed for cluster instance {db_instance_identifier}"
            )
