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