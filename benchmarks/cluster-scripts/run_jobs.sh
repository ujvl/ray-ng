#!/bin/bash

HEAD_IP=$1

NUM_RAYLETS=64
GCS_DELAY_MS=200
NUM_SHARDS=32
NONDETERMINISM=0

for TASK_DURATION in 0 200 100 50 150 25 75 125 175; do
    for USE_GCS_ONLY in 0 1; do
        for NONDETERMINISM in 0 1; do
            bash -x ./cluster-scripts/run_job.sh $NUM_RAYLETS $HEAD_IP $USE_GCS_ONLY $GCS_DELAY_MS $NONDETERMINISM $NUM_SHARDS $TASK_DURATION
        done
    done
done
