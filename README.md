# rds-snap
pip installable tool to allow user to manage AWS RDS Aurora snapshots/clusters.

# Motivation
This opinionated tool is used for the following:
- create snapshots of AWS RDS Clusters
- share/copy snapshots between AWS accounts
- restore AWS RDS Clusters from snapshots
- destroy AWS RDS Clusters

# TODO
- refine logging
- add tests

# Installation
## Using Pip
```bash
$ pip install rds-snap
```
## Manual
```bash
$ git clone https://github.com/RingierIMU/rds-snap
$ cd rds-snap
$ python setup.py install/make install
```
This will install the tool.
## Development
```bash
$ git clone https://github.com/RingierIMU/rds-snap
$ cd rds-snap
$ make dev
```
This will create an environment, format and build the tool.

# Usage
The [example shell script](https://github.com/RingierIMU/rds-snap/blob/main/examples/example.sh) outlines some common uses.

## Verify

Verify that an Aurora cluster is available, has exactly the expected members and one writer, and all member instances are available.

```bash
rds-snap cluster verify --profile my-profile --cluster-identifier my-cluster --instance-identifier my-cluster-instance-0 --instance-identifier my-cluster-instance-1
```

Options:

- `--profile`: optional AWS profile.
- `--cluster-identifier`: required cluster identifier.
- `--instance-identifier`: required expected instance identifier; repeat for each member.

This command is read-only: only describe calls, no waiting. Exit code 0 means all checks pass; exit code 1 means any check fails. Checks short-circuit in the following order, reporting these messages (prefixed by `Error:`):

1. Cluster lookup: `Cluster {id} not found` for `DBClusterNotFoundFault` or an empty cluster list. Other lookup errors: `describe_db_clusters failed for cluster {id}: {code}: {error message}`.
2. Cluster status: `Cluster {id} status is '{status}', expected 'available'`.
3. Member mismatch: `Cluster {id} member mismatch: expected {sorted(expected)}, actual {sorted(actual)}`.
4. Writer count: `Cluster {id} has {n} writer(s), expected exactly 1: {sorted(writer_ids)}`.
5. Instance status: `Instances not available: {id} ({status}), {id} ({status})`, listing only unavailable instances sorted by identifier; absent instances have status `missing`.

Sorted collections use Python list representation, for example `['a-0', 'a-1']`. On success, output shows `{cluster_id}: {status}`, followed by sorted member lines in the format `  {member_id}: writer={True|False} status={instance_status}` (two leading spaces).

# Exit codes
Commands exit `0` on success and `1` on a clean, intentional failure (a `click` error message is printed to stderr prefixed with `Error:`). Unexpected exceptions, including a `WaiterError` when a snapshot never becomes `available`, still propagate as a non-zero exit.

| Command | Exit `0` | Exit `1` |
| --- | --- | --- |
| `snapshot tag` | All matching snapshots tagged. Also when no snapshot matches `--snapshot` (a warning is printed to stderr and nothing is tagged). | AWS rejects the tag call (for example access denied or throttling). |
| `cluster tag` | The cluster ARN and every instance ARN are tagged. | AWS rejects any describe or tag call; the failing ARN is named. |
| `snapshot create` | Snapshot created (or, with `--wait`, created and `available`). | Cluster not found, cluster in a state other than `available`/`backing-up`, or the cluster stays `backing-up` for longer than the poll budget. No snapshot is requested in these cases. A `--wait` timeout still raises `WaiterError` (non-zero). |
| `snapshot delete` | Snapshot deleted. Also when the snapshot does not exist (`snapshot <id> not found, nothing to delete` is printed to stderr), so delete is idempotent. | Snapshot in an invalid state, or AWS rejects the delete call for any other reason. The message names the snapshot and the AWS error. |
| `snapshot share` | Snapshot attribute updated for the target account (`Successfully shared ...`). | Any error from AWS. The message names the snapshot, the target account and the AWS error. |
| `cluster verify` | Cluster `available`, member set equals the `--instance-identifier` set, exactly one writer, every member `available`. | Any check fails: cluster not found or lookup error, cluster not `available`, member mismatch, writer count other than one, or a member not `available`. Read-only; no snapshot or cluster is touched. |

# Output
Sample output while recreating a cluster from and snapshot:
```bash
[2021-08-13 09:57:58,983] rds-snap [INFO] create_cluster_and_wait 268: Creating cluster my-workspace-example
[2021-08-13 09:58:00,073] rds-snap [INFO] create_cluster_and_wait 289: Waiting for cluster my-workspace-example to become available
[2021-08-13 10:17:38,209] rds-snap [INFO] create_cluster_and_wait 298: Cluster my-workspace-example ready in 19m:38s
[2021-08-13 10:17:38,710] rds-snap [INFO] create_instance_and_wait 546: Creating cluster instance my-workspace-example-instance-0
[2021-08-13 10:17:39,698] rds-snap [INFO] create_instance_and_wait 559: Waiting for cluster instance my-workspace-example-instance-0 to become available
[2021-08-13 10:23:57,238] rds-snap [INFO] create_instance_and_wait 568: Cluster instance my-workspace-example-instance-0 ready in 6m:18s
[2021-08-13 10:23:57,509] rds-snap [INFO] update_password_and_wait 308: Updating password for cluster my-workspace-example
[2021-08-13 10:24:01,644] rds-snap [INFO] update_password_and_wait 326: Waited for update command to propagate to cluster my-workspace-example in 4s
[2021-08-13 10:24:01,644] rds-snap [INFO] update_password_and_wait 330: Waiting for cluster my-workspace-example to become available
[2021-08-13 10:25:03,921] rds-snap [INFO] update_password_and_wait 338: Cluster my-workspace-example ready in 1m:02s
```
