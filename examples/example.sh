#!/usr/bin/env bash

readlink_bin="${READLINK_PATH:-readlink}"
if ! "${readlink_bin}" -f test &> /dev/null; then
  __DIR__="$(dirname "$(python3 -c "import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))" "${0}")")"
else
  __DIR__="$(dirname "$("${readlink_bin}" -f "${0}")")"
fi

consolelog() {
  local color
  local ts

  # el-cheapo way to detect if timestamp needed or not
  if [[ ! -z "${JENKINS_HOME}" ]]; then
    ts=""
  else
    ts="[$(date -u +'%Y-%m-%d %H:%M:%S')] "
  fi

  color_reset='\e[0m'

  case "${2}" in
    success )
      color='\e[0;32m'
      ;;
    error )
      color='\e[1;31m'
      ;;
    * )
      color='\e[0;37m'
      ;;
  esac

  if [[ ! -z "${1}" ]]; then
    printf "${color}%s%s: %s${color_reset}\n" "${ts}" "${0##*/}" "${1}" >&2
  fi

  return 0
}

throw_exception() {
  consolelog "Ooops!" error
  echo 'Stack trace:' 1>&2
  while caller $((n++)) 1>&2; do :; done;
  exit 1
}

has_cmd() {
  command -v "$1" >/dev/null
}

duration() {
	local secs="${1}"
  local h=0 m=0 s=0
  h=$((secs/3600))
  m=$((secs%3600/60))
  s=$((secs%60))
  if [[ ${h} -gt 0 ]]; then
	  printf '%dh:%dm:%ds' "${h}" "${m}" "${s}"
  elif [[ ${m} -gt 0 ]]; then
    printf '%dm:%ds' "${m}" "${s}"
  else
    printf '%ds' "${s}"
  fi
}

set -e
trap 'throw_exception' ERR

source "${__DIR__}/.venv/bin/activate"

required_cmds=( \
  aws \
  rds-snap \
)

for required_cmd in "${required_cmds[@]}"; do
  if ! has_cmd "${required_cmd}"; then
    echo "required cmd missing (${required_cmd})" 1>&2
    throw_exception
  fi
done

DEFAULT_AWS_PROFILE="target-aws-profile"
TARGET_AWS_PROFILE="${DEFAULT_AWS_PROFILE:?}"

target_cluster_destroy() {
  local start=$SECONDS
  destroy_snapshot_identifier="${destroy_cluster_identifier:?}-$(date -u +%F-%H%M%S)"
  consolelog "Destroy cluster ${destroy_cluster_identifier:?} after creating snapshot ${destroy_snapshot_identifier}"
  rds-snap cluster delete --profile "${TARGET_AWS_PROFILE:?}" \
    --snapshot-identifier "${destroy_snapshot_identifier:?}" \
    --cluster-identifier "${destroy_cluster_identifier:?}" \
    --wait
  
  consolelog "Destroy cluster ${destroy_cluster_identifier:?} after creating snapshot ${destroy_snapshot_identifier} in duration $(duration $((SECONDS-start)))" success
}

target_snapshot_cycle() {
  local start=$SECONDS
  consolelog "Create snapshot of ${CLUSTER_IDENTIFIER} in ${SOURCE_AWS_PROFILE:?} and copy to ${TARGET_AWS_PROFILE:?}"
  target_aws_acc_number=$(aws --profile "${TARGET_AWS_PROFILE}" sts get-caller-identity --query "Account" --output text)
  if [[ -z ${target_aws_acc_number} ]]; then
    consolelog "Could not obtain target_aws_acc_number" error
    throw_exception
  fi

  rds-snap snapshot create --profile "${SOURCE_AWS_PROFILE:?}" --cluster "${CLUSTER_IDENTIFIER:?}" --snapshot-identifier "${snapshot_identifier:?}" --wait
  rds-snap snapshot share --profile "${SOURCE_AWS_PROFILE:?}" --snapshot-identifier "${snapshot_identifier:?}" --account-number "${target_aws_acc_number:?}"
  rds-snap snapshot copy --source-profile "${SOURCE_AWS_PROFILE:?}" --target-profile "${TARGET_AWS_PROFILE:?}" --snapshot-identifier "${snapshot_identifier:?}" --target-kms-alias "${TARGET_KMS_ALIAS:?}" --wait
  consolelog "Create snapshot of ${CLUSTER_IDENTIFIER} in ${SOURCE_AWS_PROFILE:?} and copy to ${TARGET_AWS_PROFILE:?} in $(duration $((SECONDS-start)))" success
}

target_cluster_create() {
  local start=$SECONDS
  consolelog "Create cluster ${cluster_identifier:?} in ${TARGET_AWS_PROFILE} based on ${create_cluster_source_snapshot_identifier:?}"
  cluster_vpc_sg_id="$(aws --profile "${TARGET_AWS_PROFILE}" ec2 describe-security-groups --query 'SecurityGroups[].[GroupName, GroupId]' --output text | awk '/'"${TARGET_WORKSPACE:?}"'-something/ {print $NF}')"

  rds-snap cluster restore --profile "${TARGET_AWS_PROFILE}" \
    --snapshot-identifier "${create_cluster_source_snapshot_identifier:?}" \
    --cluster-identifier "${cluster_identifier:?}" \
    --db-subnet-group-name "${CLUSTER_SUBNET_GROUP_NAME:?}" \
    --vpc-security-group-id "${cluster_vpc_sg_id:?}" \
    --db-cluster-parameter-group-name "${CLUSTER_PARAMETER_GROUP_NAME:?}" \
    --db-cluster-master-password "${CLUSTER_DB_PASSWORD:?}" \
    --db-instance-class "${CLUSTER_INSTANCE_CLASS:?}"
  
  consolelog "Create cluster ${cluster_identifier:?} in ${TARGET_AWS_PROFILE} based on ${create_cluster_source_snapshot_identifier:?} in duration $(duration $((SECONDS-start)))" success
}

target_example_create(){
  local start=$SECONDS
  SOURCE_AWS_PROFILE="source-aws-profile"
  TARGET_WORKSPACE="my-workspace"

  CLUSTER_IDENTIFIER="${TARGET_WORKSPACE:?}-example"
  CLUSTER_INSTANCE_CLASS="db.r5.large"
  CLUSTER_SUBNET_GROUP_NAME="${TARGET_WORKSPACE:?}-main-vpc"
  CLUSTER_PARAMETER_GROUP_NAME="my-cluster-param-group"
  TARGET_KMS_ALIAS="${TARGET_WORKSPACE:?}/db"

  CLUSTER_DB_PASSWORD="cHaNgE-Me-pLeAsE"

  cluster_identifier="${CLUSTER_IDENTIFIER:?}"
  snapshot_identifier="${cluster_identifier:?}-$(date -u +%F-%H%M%S)"
  create_cluster_source_snapshot_identifier="${snapshot_identifier:?}"

  # snapshot
  target_snapshot_cycle
  # cluster create
  target_cluster_create
  consolelog "example_create duration $(duration $((SECONDS-start)))" success
}

target_example_destroy(){
  local start=$SECONDS
  SOURCE_AWS_PROFILE="source-aws-profile"
  TARGET_WORKSPACE="prod"

  CLUSTER_IDENTIFIER="${TARGET_WORKSPACE:?}-example"

  cluster_identifier="${CLUSTER_IDENTIFIER:?}"
  snapshot_identifier="${cluster_identifier:?}-$(date -u +%F-%H%M%S)"
  create_cluster_source_snapshot_identifier="${snapshot_identifier:?}"
  destroy_cluster_identifier="${cluster_identifier:?}"

  # cluster destroy
  target_cluster_destroy
  consolelog "example_destroy duration $(duration $((SECONDS-start)))" success
}

target_example_refresh() {
  target_example_destroy
  target_example_create
}

if [[ -z "${1}" ]]; then
  target="target_example_refresh"
else
  target="target_${1}"
fi

if [[ "$(type -t "${target}")" != "function" ]]; then
  consolelog "unknown target: ${target#*_}" "error"

  echo -e "\n\nAvailable targets:"
  targets=( $(compgen -A function) )
  for target in "${targets[@]}"; do
    if [[ "${target}" == "target_"* ]]; then
      echo "- ${target#*_}"
    fi
  done

  exit 1
fi

if [[ "${#@}" -gt "0" ]]; then
  shift
fi

"${target}" "${@}"
