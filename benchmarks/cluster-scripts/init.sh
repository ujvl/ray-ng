#!/bin/bash

for host in $(cat ~/workers.txt); do
  ssh-keygen -f "/home/ubuntu/.ssh/known_hosts" -R $host
  ssh -o "StrictHostKeyChecking no" $host 'uptime'
  if ! grep "$host$" ~/.ssh/config >1 /dev/null 2>&1; then
      echo "Host $host" >> ~/.ssh/config
      echo "    ForwardAgent yes" >> ~/.ssh/config
  fi
done

parallel-ssh -t 0 -i -P -h ~/workers.txt -O "StrictHostKeyChecking=no" -I < enable_hugepages.sh

pushd .
git clone git@github.com:stephanie-wang/mpi-bench.git ~/mpi-bench
cd ~/mpi-bench
bash -x ./build.sh
popd

num_workers=$(( `wc -l ~/workers.txt | awk '{ print $1 }'` - 1 ))
for worker in `tail -n $num_workers ~/workers.txt`; do
    echo $worker
    rsync -e "ssh -o StrictHostKeyChecking=no" -az "/home/ubuntu/mpi-bench" $worker:/home/ubuntu & sleep 0.5
done
wait
