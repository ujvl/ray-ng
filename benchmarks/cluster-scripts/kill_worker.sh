#!/bin/bash

HEAD_IP=$1
WORKER_IP=$2
USE_GCS_ONLY=$3
GCS_DELAY_MS=$4
NONDETERMINISM=$5
MAX_FAILURES=$6
OBJECT_STORE_MEMORY_GB=$7
OBJECT_STORE_EVICTION=$8
PEG=$9
OBJECT_MANAGER_THREADS=${10}
NODE_RESOURCE=${11}


ssh -o "StrictHostKeyChecking=no"  -i /home/ubuntu/ray_bootstrap_key.pem $WORKER_IP ray stop

ssh -o "StrictHostKeyChecking=no"  -i /home/ubuntu/ray_bootstrap_key.pem $WORKER_IP 'bash -s - '$HEAD_IP $USE_GCS_ONLY $GCS_DELAY_MS $NONDETERMINISM $MAX_FAILURES $OBJECT_STORE_MEMORY_GB $OBJECT_STORE_EVICTION $PEG $OBJECT_MANAGER_THREADS $NODE_RESOURCE' 0'< /home/ubuntu/ray/benchmarks/cluster-scripts/start_worker.sh
