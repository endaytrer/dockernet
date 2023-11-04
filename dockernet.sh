#!/bin/sh
PREFIX="dn-"
IP_RANGE="10.0.0.0/8"
SUBNET_RANGE=29

ZEROTH_SUBNET="$(echo ${IP_RANGE} | sed -nE "s/^(\S+)\/\S+$/\1/p")/${SUBNET_RANGE}"
CURRENT_SUBNET=$ZEROTH_SUBNET

# clean networks
clean_networks() {
    echo "Cleaning devices..."
    docker ps | \
    sed -nE "s/^.+(${PREFIX}[A-Za-z0-9]+)$/\1/p" | \
    xargs -r -L1 docker kill 

    echo "Cleaning networks..."
    docker network ls | \
    sed -nE "s/^[a-f0-9]{12}\s+(${PREFIX}[A-Za-z0-9]+)\s+bridge\s+local$/\1/p" | \
    while read -r line; do
        docker network rm $line
    done
    CURRENT_SUBNET=$ZEROTH_SUBNET
}


create_network() {
    if [ $# -ne 2 ]; then
        echo "Usage: $0 NAME SUBNET"
        return 1
    fi
    local network_name=$1
    local subnet=$2
    if docker network create -d bridge --subnet ${subnet} --internal ${PREFIX}${network_name} >> /dev/null; then
        echo ${network_name}
    else
        return 1
    fi
}

increment_subnet() {
    CURRENT_SUBNET=$(${PWD}/next_network.py ${IP_RANGE} ${CURRENT_SUBNET})
}

create_device() {
    if [ $# -lt 3 ]; then
        echo "Usage: $0 CONTAINER_NAME IMAGE_NAME [params]"
        return 1
    fi
    local name=${PREFIX}$1
    local image_name=$2
    local network=${PREFIX}$3

    if docker run -d --rm --name ${name} --network ${network} --privileged   ${@:4} ${image_name} >> /dev/null; then
        echo "$1 -> $3"
    fi
}

connect_device() {
    if [ $# -lt 2 ]; then
        echo "Usage: $0 CONTAINER_NAME NETWORK_NAME [params]"
        return 1
    fi
    local container_name=${PREFIX}$1
    local network_name=${PREFIX}$2
    echo "$1 -> $2"
    docker network connect ${@:3} ${network_name} ${container_name}
}

attach_device() {
    if [ $# -lt 2 ]; then
        echo "Usage: $0 CONTAINER_NAME PROGRAM [params]"
        return 1
    fi
    local container_name=${PREFIX}$1
    local program=$2
    docker exec -it ${@:3} ${container_name} ${program}
}

create_topo() {
    clean_networks

    create_network net0 ${CURRENT_SUBNET} # 10.0.0.0/29
    increment_subnet
    create_network net1 ${CURRENT_SUBNET}
    increment_subnet
    create_network net2 ${CURRENT_SUBNET}
    increment_subnet

    create_device r1 frrouting/frr net0 -v ${PWD}/config/r1:/etc/frr -v ${PWD}/log/r1
    connect_device r1 net1
    create_device h1 archlinux net0

    create_device r2 frrouting/frr net2 -v ${PWD}/config/r2:/etc/frr
    connect_device r2 net1
    create_device h2 archlinux net2
}