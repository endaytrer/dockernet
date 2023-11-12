#!/usr/bin/env python3
import os
import sys
import dockernet
import traceback
import ipaddress
import pathlib
import shutil
import subprocess

from next_network import new_network

ROUTER_IMAGE = "frrouting/frr"
DEFAULT_CONFIG = "default_config"

config_dir = pathlib.Path(".config").absolute()

neighbor_config = "  neighbor {neighbor} remote-as {remote_as}"
network_config = "  network {network}"

router_config = """!
frr defaults datacenter
!
router bgp {asn}
  bgp router-id {router_ip}
  bgp bestpath as-path multipath-relax
  no bgp network import check
{neighbors}
!
{networks}"""

router_confed_config = """!
frr defaults datacenter
!
router bgp {private_asn}
  bgp router-id {router_ip}
  bgp bestpath as-path multipath-relax
  no bgp network import check
  bgp confederation identifier {public_asn}
  bgp confederation peers {confed_peers}
{neighbors}
!
{networks}"""
AS_START = 65000

def fattree(num_pods: int, num_leafs_per_pod: int):
    dockernet.clean_networks()
    if config_dir.exists():
        shutil.rmtree(str(config_dir))
    # links logical expression
    links: list[list[str]] = []
    ip_addresses: dict[str, list[ipaddress.IPv4Interface]] = {}


    # create logical links: spine - leaf

    network_spine_leaf = ipaddress.ip_network("10.0.0.0/10")
    subnet_iter = network_spine_leaf.subnets(new_prefix=30)
    
    for cluster in range(num_leafs_per_pod):
        for pod in range(num_pods):
            leaf_device = f"rl{pod * num_leafs_per_pod + cluster}"
            ip_addresses[leaf_device] = []
            for i in range(num_pods):
                spine_device = f"rs{cluster * num_pods + i}"
                if pod == 0:
                    ip_addresses[spine_device] = []

                subnet = next(subnet_iter)
                iter = subnet.hosts()

                ip_spine = ipaddress.ip_interface((next(iter), subnet.prefixlen))
                ip_leaf = ipaddress.ip_interface((next(iter), subnet.prefixlen))
                ip_addresses[spine_device].append(ip_spine)
                ip_addresses[leaf_device].append(ip_leaf)
                links.append([spine_device, f"eth{pod}", leaf_device, f"eth{i}", str(ip_spine), str(ip_leaf)])


    # create logical links: leaf - rack

    network_leaf_rack = ipaddress.ip_network("10.64.0.0/10")
    subnet_iter = network_leaf_rack.subnets(new_prefix=30)

    for pod in range(num_pods):
        for leaf in range(num_leafs_per_pod):
            leaf_device = f"rl{pod * num_leafs_per_pod + leaf}"
            for rack in range(num_leafs_per_pod):
                rack_device = f"rr{pod * num_leafs_per_pod + rack}"
                if leaf == 0:
                    ip_addresses[rack_device] = []

                subnet = next(subnet_iter)
                iter = subnet.hosts()
                ip_leaf = ipaddress.ip_interface((next(iter), subnet.prefixlen))
                ip_rack = ipaddress.ip_interface((next(iter), subnet.prefixlen))
                ip_addresses[leaf_device].append(ip_leaf)
                ip_addresses[rack_device].append(ip_rack)

                links.append([leaf_device, f"eth{num_pods + rack}", rack_device, f"eth{leaf}", str(ip_leaf), str(ip_rack)])

    # create spine devices and their configs
    config_dir.mkdir(parents=True, exist_ok=True)
    for cluster in range(num_leafs_per_pod):
        for pod in range(num_pods):
            device = f"rs{cluster * num_pods + pod}"
            device_config = str(os.path.join(str(config_dir), device))
            subprocess.run(["cp", "-r", DEFAULT_CONFIG, device_config])
            # create bgp config
            neighbors: list[str] = []
            networks: list[str] = []
            for i in range(num_pods):
                leaf_device = f"rl{i * num_leafs_per_pod + cluster}"
                neighbors.append(neighbor_config.format(neighbor=str(ip_addresses[leaf_device][pod].ip), remote_as=str(AS_START + num_leafs_per_pod + i)))

            for ip in ip_addresses[device]:
                networks.append(network_config.format(network=str(ip.network)))
            
            config = router_config.format(
                asn=AS_START + cluster,
                router_ip=str(ip_addresses[device][0].ip),
                neighbors='\n'.join(neighbors),
                networks='\n'.join(networks))

            with open(os.path.join(device_config, "bgpd.conf"), "w") as f:
                f.write(config)
            dockernet.create_device(device, ROUTER_IMAGE, "none", "-v", f"{device_config}:/etc/frr") # spine

    # create leaf devices and their configs
    private_as_start = AS_START + num_leafs_per_pod + num_pods
    private_as_start_rack = private_as_start + num_leafs_per_pod * num_pods

    for pod in range(num_pods):
        for leaf in range(num_leafs_per_pod):
            device = f"rl{pod * num_leafs_per_pod + leaf}"
            device_config = str(os.path.join(str(config_dir), device))
            subprocess.run(["cp", "-r", DEFAULT_CONFIG, device_config])
            # create bgp config with confederation
            neighbors: list[str] = []
            networks: list[str] = []
            confed_peers: list[str] = []
            # north bound
            for i in range(num_pods):
                spine_device = f"rs{leaf * num_pods + i}"
                neighbors.append(neighbor_config.format(neighbor=str(ip_addresses[spine_device][pod].ip), remote_as=str(AS_START + leaf)))


            # south bound
            for i in range(num_leafs_per_pod):
                rack_device = f"rr{pod * num_leafs_per_pod + i}"
                remote_as = str(private_as_start_rack + pod * num_leafs_per_pod + i)
                neighbors.append(neighbor_config.format(neighbor=str(ip_addresses[rack_device][leaf].ip), remote_as=remote_as))
                confed_peers.append(remote_as)

            for ip in ip_addresses[device]:
                networks.append(network_config.format(network=str(ip.network)))
            
            config = router_confed_config.format(
                private_asn=str(private_as_start + pod * num_leafs_per_pod + leaf),
                router_ip=str(ip_addresses[device][0].ip),
                public_asn=AS_START + num_leafs_per_pod + pod,
                confed_peers=" ".join(confed_peers),
                neighbors="\n".join(neighbors),
                networks="\n".join(networks))

            with open(os.path.join(device_config, "bgpd.conf"), "w") as f:
                f.write(config)

            dockernet.create_device(device, ROUTER_IMAGE, "none", "-v", f"{device_config}:/etc/frr") # spine

    # create rack devices and their configs
    for pod in range(num_pods):
        for leaf in range(num_leafs_per_pod):
            device = f"rr{pod * num_leafs_per_pod + leaf}"
            device_config = str(os.path.join(str(config_dir), device))
            subprocess.run(["cp", "-r", DEFAULT_CONFIG, device_config])

            # create bgp config with confederation
            neighbors: list[str] = []
            networks: list[str] = []
            confed_peers: list[str] = []
            # north bound
            for i in range(num_leafs_per_pod):
                leaf_device = f"rl{pod * num_leafs_per_pod + i}"
                remote_as = str(private_as_start + pod * num_leafs_per_pod + i)
                neighbors.append(neighbor_config.format(neighbor=str(ip_addresses[leaf_device][num_pods + leaf].ip), remote_as=remote_as))
                confed_peers.append(remote_as)

            for ip in ip_addresses[device]:
                networks.append(network_config.format(network=str(ip.network)))
            
            config = router_confed_config.format(
                private_asn=str(private_as_start_rack + pod * num_leafs_per_pod + leaf),
                router_ip=str(ip_addresses[device][0].ip),
                public_asn=AS_START + num_leafs_per_pod + pod,
                confed_peers=" ".join(confed_peers),
                neighbors="\n".join(neighbors),
                networks="\n".join(networks))

            with open(os.path.join(device_config, "bgpd.conf"), "w") as f:
                f.write(config)

            dockernet.create_device(device, ROUTER_IMAGE, "none", "-v", f"{device_config}:/etc/frr") # spine

    for link in links:
        dockernet.link_device(*link)


if __name__ == "__main__":
    num_pods = 2
    num_leafs_per_pod = 2

    if len(sys.argv) == 3:
        num_pods = int(sys.argv[1])
        num_leafs_per_pod = int(sys.argv[2])
    try:
        fattree(num_pods, num_leafs_per_pod)
    except:
        traceback.print_exc()
    finally:
        dockernet.main_loop()
    if config_dir.exists():
        shutil.rmtree(str(config_dir))