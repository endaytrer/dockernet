#!/usr/bin/env python3
import sys
import ipaddress

def new_network(network: ipaddress.IPv4Network, subnet: ipaddress.IPv4Network) -> ipaddress.IPv4Network:
    new_network = ipaddress.ip_network((ipaddress.IPv4Address(int(subnet.network_address) + int(subnet.hostmask) + 1), subnet.prefixlen))
    if not subnet.subnet_of(network) or not new_network.subnet_of(network):
        raise Exception("Subnet is not in network!")
    return new_network

if __name__ == "__main__":
    _prog, ip_range, ip_start = sys.argv
    network = ipaddress.ip_network(ip_range)
    subnet = ipaddress.ip_network(ip_start)
    print(new_network(network, subnet))