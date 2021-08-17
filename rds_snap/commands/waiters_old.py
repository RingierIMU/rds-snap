from botocore import waiter, exceptions


def wait_volume_attachment(
    volume_id: str, instance_id: str, device: str, waiter_id: str, ec2
):
    """Wait for volume attachment"""
    waiter_delay = 15
    waiter_max_attempts = 40
    # VOLUME_ID = ... # e.g. 'vol-049df61146c4d7901'
    # INSTANCE_ID = ...  # e.g. 'i-1234567890abcdef0'
    # DEVICE = ... # e.g. '/dev/xvdba'
    # WAITER_ID = ... # e.g. 'MyWaiter'
    # Acceptor structure:
    # - Matcher: Path, PathAll, PathAny, Status, and Error (Last two check http status and return failures then short circuit)
    # - Expected: the expected response
    # - Argument: used to determine if the result is expected
    # - State: what the acceptor will return based on the matcher function
    model = waiter.WaiterModel(
        {
            "version": 2,
            "waiters": {
                waiter_id: {
                    "delay": waiter_delay,
                    "operation": "DescribeVolumes",
                    "maxAttempts": waiter_max_attempts,
                    "acceptors": [
                        {
                            "expected": True,
                            "matcher": "path",
                            "state": "success",
                            "argument": "length(Volumes[?State == 'in-use'].Attachments[] | [?"
                            f"InstanceId == '{instance_id}' &&"
                            f"Device == '{device}' &&"
                            "State == 'attached'"
                            "]) == `1`",
                        },
                        {
                            "expected": True,
                            "matcher": "path",
                            "state": "failure",
                            "argument": "length(Volumes[?State == 'in-use'].Attachments[] | [?"
                            f"InstanceId != '{instance_id}' ||"
                            f"Device != '{device}'"
                            "]) > `0`",
                        },
                        {
                            "expected": "deleted",
                            "matcher": "pathAny",
                            "state": "failure",
                            "argument": "Volumes[].State",
                        },
                        {
                            "expected": "error",
                            "matcher": "pathAny",
                            "state": "failure",
                            "argument": "Volumes[].State",
                        },
                    ],
                }
            },
        }
    )
    this_waiter = waiter.create_waiter_with_client(waiter_id, model, ec2)
    try:
        this_waiter.wait(VolumeIds=[volume_id])
    except exceptions.WaiterError as e:
        if "Max attempts exceeded" in e.message:
            print(
                f"Attachment did not complete in {waiter_delay * waiter_max_attempts}s"
            )
        else:
            print(e.message)
    else:
        print(
            f"Volume {volume_id} attached successfully to instance {instance_id} at {device}"
        )
