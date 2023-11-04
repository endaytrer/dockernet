#!/usr/bin/env python
import sys
import ipaddress


if __name__ == "__main__":
    _prog, ip_range, ip_start = sys.argv
    network = ipaddress.ip_network(ip_range)
    subnet = ipaddress.ip_network(ip_start)
    new_network = ipaddress.ip_network((ipaddress.IPv4Address(int(subnet.network_address) + int(subnet.hostmask) + 1), subnet.prefixlen))
    print(new_network)