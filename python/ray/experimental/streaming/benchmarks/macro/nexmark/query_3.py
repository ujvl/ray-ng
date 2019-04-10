from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import logging
import math
import string
import sys
import time

import ray
import ray.experimental.streaming.benchmarks.utils as utils
import ray.experimental.streaming.benchmarks.macro.nexmark.data_generator as dg
from ray.experimental.streaming.batched_queue import BatchedQueue
from ray.experimental.streaming.benchmarks.macro.nexmark.event import Person
from ray.experimental.streaming.benchmarks.macro.nexmark.event import Auction
from ray.experimental.streaming.benchmarks.macro.nexmark.event import Record
from ray.experimental.streaming.communication import QueueConfig
from ray.experimental.streaming.streaming import Environment

logger = logging.getLogger(__name__)
logger.setLevel("DEBUG")

parser = argparse.ArgumentParser()
parser.add_argument("--pin-processes", default=False,
                    action='store_true',
                    help="whether to pin python processes to cores or not")
parser.add_argument("--nodes", default=1,
                    help="total number of nodes in the cluster")
parser.add_argument("--redis-shards", default=1,
                    help="total number of Redis shards")
parser.add_argument("--redis-max-memory", default=10**9,
                    help="max amount of memory per Redis shard")
parser.add_argument("--plasma-memory", default=10**9,
                    help="amount of memory to start plasma with")
# Dataflow-related parameters
parser.add_argument("--auctions-file", required=True,
                    help="Path to the auctions file")
parser.add_argument("--persons-file", required=True,
                    help="Path to the persons file")
parser.add_argument("--enable-logging", default=False,
                    action='store_true',
                    help="whether to log actor latency and throughput")
parser.add_argument("--queue-based", default=False,
                    action='store_true',
                    help="queue-based execution")
parser.add_argument("--dataflow-parallelism", default=1,
                    help="the number of instances per operator")
parser.add_argument("--latency-file", default="latencies",
                    help="a prefix for the latency log files")
parser.add_argument("--throughput-file", default="throughputs",
                    help="a prefix for the rate log files")
parser.add_argument("--dump-file", default="",
                    help="a prefix for the chrome dump file")
parser.add_argument("--sample-period", default=100,
                    help="every how many input records latency is measured.")
parser.add_argument("--auctions-rate", default=-1,
                    type=lambda x: float(x) or
                                parser.error("Source rate cannot be zero."),
                    help="source output rate (records/s)")
parser.add_argument("--persons-rate", default=-1,
                    type=lambda x: float(x) or
                                parser.error("Source rate cannot be zero."),
                    help="source output rate (records/s)")
# Queue-related parameters
parser.add_argument("--queue-size", default=100,
                    help="the queue size in number of batches")
parser.add_argument("--batch-size", default=1000,
                    help="the batch size in number of elements")
parser.add_argument("--flush-timeout", default=0.1,
                    help="the timeout to flush a batch")
parser.add_argument("--prefetch-depth", default=1,
                    help="the number of batches to prefetch from plasma")
parser.add_argument("--background-flush", default=False,
                    help="whether to flush in the backrgound or not")
parser.add_argument("--max-throughput", default="inf",
                    help="maximum read throughput (records/s)")

# Used to join auctions with persons incrementally. An auction has exactly one
# seller, thus, we can remove the auction entry from local state upon a join
class JoinLogic(object):
    def __init__(self):
        # Local state
        self.auctions = {}  # seller -> auctions
        self.persons = {}   # id -> person

    def process_left(self, auction):
        result = []
        person = self.persons.get(auction.seller)
        if person is None:  # Store auction for future join
            entry = self.auctions.setdefault(auction.seller, [])
            entry.append(auction)
        else:  # Found a join; emit and do not store auction
            # print("Found a join {} - {}".format(auction, person))
            p_time = person.system_time
            a_time = auction.system_time
            # This is just to measure end-to-end latency by considering as
            # start time the time we have seen both input tuples
            s_time = p_time if a_time <=p_time else a_time  # Max
            record = Record(name=person.name, city=person.city,
                            state=person.state, auction=auction.id,
                            system_time=s_time)
            result.append(record)
        return result

    def process_right(self, person):
        result = []
        self.persons.setdefault(person.id,person)
        auctions = self.auctions.pop(person.id, None)
        if auctions is not None:
            for auction in auctions:
                # print("Found a join {} - {}".format(auction, person))
                # Remove entry
                p_time = person.system_time
                a_time = auction.system_time
                # This is just to measure end-to-end latency by considering as
                # start time the time we have seen both input tuples
                s_time = p_time if a_time <=p_time else a_time  # Max
                record = Record(name=person.name, city=person.city,
                                state=person.state, auction=auction.id,
                                system_time=s_time)
                result.append(record)
        return result

if __name__ == "__main__":

    args = parser.parse_args()

    num_nodes = int(args.nodes)
    num_redis_shards = int(args.redis_shards)
    redis_max_memory = int(args.redis_max_memory)
    plasma_memory = int(args.plasma_memory)
    auctions_file = str(args.auctions_file)
    persons_file = str(args.persons_file)
    latency_filename = str(args.latency_file)
    throughput_filename = str(args.throughput_file)
    dump_filename = str(args.dump_file)
    logging = bool(args.enable_logging)
    sample_period = int(args.sample_period)
    task_based = not bool(args.queue_based)
    dataflow_parallelism = int(args.dataflow_parallelism)
    max_queue_size = int(args.queue_size)
    max_batch_size = int(args.batch_size)
    batch_timeout = float(args.flush_timeout)
    prefetch_depth = int(args.prefetch_depth)
    background_flush = bool(args.background_flush)
    auctions_rate = float(args.auctions_rate)
    persons_rate = float(args.persons_rate)
    pin_processes = bool(args.pin_processes)

    logger.info("== Parameters ==")
    logger.info("Number of nodes: {}".format(num_nodes))
    logger.info("Number of Redis shards: {}".format(num_redis_shards))
    logger.info("Max memory per Redis shard: {}".format(redis_max_memory))
    logger.info("Plasma memory: {}".format(plasma_memory))
    logger.info("Logging: {}".format(logging))
    logger.info("Sample period: {}".format(sample_period))
    logger.info("Task-based execution: {}".format(task_based))
    logger.info("Auctions file: {}".format(auctions_file))
    logger.info("Persons file: {}".format(persons_file))
    logger.info("Latency file prefix: {}".format(latency_filename))
    logger.info("Throughput file prefix: {}".format(throughput_filename))
    logger.info("Dump file prefix: {}".format(dump_filename))
    logger.info("Parallelism: {}".format(dataflow_parallelism))
    logger.info("Max queue size: {}".format(max_queue_size))
    logger.info("Max batch size: {}".format(max_batch_size))
    logger.info("Batch timeout: {}".format(batch_timeout))
    logger.info("Prefetch depth: {}".format(prefetch_depth))
    logger.info("Background flush: {}".format(background_flush))
    message = (" (as fast as it gets)") if auctions_rate < 0 else ""
    logger.info("Auctions rate: {}".format(auctions_rate) + message)
    message = (" (as fast as it gets)") if persons_rate < 0 else ""
    logger.info("Persons rate: {}".format(persons_rate) + message)
    logger.info("Pin processes: {}".format(pin_processes))

    # Start Ray with the specified configuration
    utils.start_ray(num_nodes, num_redis_shards, plasma_memory,
                    redis_max_memory, 1, dataflow_parallelism,
                    2, pin_processes)

    # We just have a source stage followed by a (stateful) join
    stages_per_node = math.trunc(math.ceil(2 / num_nodes))

    # Use pickle for BatchedQueue
    ray.register_custom_serializer(BatchedQueue, use_pickle=True)

    # Batched queue configuration
    queue_config = QueueConfig(max_queue_size,
                        max_batch_size, batch_timeout,
                        prefetch_depth, background_flush)

    # Create streaming environment, construct and run dataflow
    env = Environment()
    env.set_queue_config(queue_config)
    env.set_parallelism(dataflow_parallelism)
    if logging:
        env.enable_logging()
    if task_based:
        env.enable_tasks()

    # Add the auctions source
    auctions_source = env.source(dg.NexmarkEventGenerator(auctions_file,
                                "Auction",
                                auctions_rate, sample_period),
                                name="Auctions Source",
                                placement=[utils.CLUSTER_NODE_PREFIX + "0"])
    auctions = auctions_source.partition(lambda auction: auction.seller)
    # Add the persons source
    persons_source = env.source(dg.NexmarkEventGenerator(persons_file,
                                "Person",
                                persons_rate, sample_period),
                                name="Persons Source",
                                placement=[utils.CLUSTER_NODE_PREFIX + "0"])
    persons = persons_source.partition(lambda person: person.id)
    # Add the join
    id = 1 // stages_per_node
    mapping = [utils.CLUSTER_NODE_PREFIX + str(id)] * dataflow_parallelism
    # Add the filter
    output = auctions.join(persons,
                           JoinLogic(),  # The custom join logic (see above)
                           name="Join Auctions with Persons",
                           placement=mapping)
    # Add a final custom sink to measure latency if logging is enabled
    output.sink(dg.LatencySink(), name="sink", placement=mapping)

    start = time.time()
    dataflow = env.execute()
    ray.get(dataflow.termination_status())

    # Write log files
    max_queue_size = queue_config.max_size
    max_batch_size = queue_config.max_batch_size
    batch_timeout = queue_config.max_batch_time
    prefetch_depth = queue_config.prefetch_depth
    background_flush = queue_config.background_flush
    auctions_rate = auctions_rate if auctions_rate > 0 else "inf"
    persons_rate = persons_rate if persons_rate > 0 else "inf"
    all = "-{}-{}-{}-{}-{}-{}-{}-{}-{}-{}-{}-{}-{}-{}-{}".format(
        num_nodes, auctions_rate, persons_rate,
        num_redis_shards, redis_max_memory, plasma_memory,
        sample_period, logging,
        max_queue_size, max_batch_size, batch_timeout, prefetch_depth,
        background_flush, pin_processes,
        task_based, dataflow_parallelism
    )
    utils.write_log_files(all, latency_filename,
                          throughput_filename, dump_filename, dataflow)

    logger.info("Elapsed time: {}".format(time.time() - start))

    utils.shutdown_ray(sleep=2)
