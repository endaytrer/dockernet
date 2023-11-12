#!/usr/bin/env python3
import subprocess
import docker
import docker.types
import ipaddress
import traceback
import shutil
import pathlib
import os
from cmd import Cmd
PREFIX = "dn-"
PROMPT = "dn> "
NETNS_DIR = "/var/run/netns"

client = docker.from_env()

def clean_networks():
    print("Cleaning peripheral files")
    if pathlib.Path(NETNS_DIR).exists():
        shutil.rmtree(NETNS_DIR)
    print("Cleaning devices...")
    for container in client.containers.list():
        if container.name.startswith(PREFIX):
            container.kill()
    
    print("Cleaning networks...")
    for network in client.networks.list():
        if network.name.startswith(PREFIX):
            network.remove()

def create_network(name: str, subnet: ipaddress.IPv4Network):
    network_name = PREFIX + name
    client.networks.create(
        network_name,
        driver="bridge",
        ipam=docker.types.IPAMConfig(pool_configs=[
            docker.types.IPAMPool(subnet=str(subnet))
        ]),
        internal=True)

def create_device(name: str, image_name: str, network: str, *args):
    container_name = PREFIX + name
    network_name = "none"  if network == "none" else PREFIX + network
    pathlib.Path(NETNS_DIR).mkdir(parents=True, exist_ok=True)
    subprocess.run(["docker",
                    "run",
                    "-dit",
                    "--rm",
                    "--name",
                    container_name,
                    "--network",
                    network_name,
                    "--privileged",
                    *args,
                    image_name], stdout=subprocess.DEVNULL)
    # create netns file in /var/run/netns so that `ip` command can visit.
    pid = subprocess.run(['docker', 'inspect', '-f', "'{{.State.Pid}}'", container_name], capture_output=True).stdout.decode()[1:-2]
    subprocess.run(["ln", "-sfT", f"/proc/{pid}/ns/net", f"{NETNS_DIR}/{container_name}"])
    print(f"{name} -> {network}")

hosts: dict[str, ipaddress.IPv4Address | None] = {}

def create_host(name: str, image_name: str, network: str, *args):
    create_device(name, image_name, network, *args)
    hosts[name] = None

def pingall():
    max_host_name_len = max([len(i) for i in hosts.keys()])
    for h1 in hosts.keys():
        if hosts[h1] is None:
            continue
        print(f"{h1:>{max_host_name_len + 1}} |", end="", flush=True)
        for h2 in hosts.keys():
            if h1 == h2 or hosts[h2] is None:
                continue
            rt = subprocess.run([
                "docker",
                "exec",
                PREFIX + h1,
                "ping",
                "-c1",
                str(hosts[h2])
            ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT).returncode
            if rt == 0:
                print(f"{h2:>{max_host_name_len + 1}}", end="", flush=True)
            else:
                print(f"{'x':>{max_host_name_len + 1}}", end="", flush=True)
        print("")

def connect_device(container_name: str, network_name: str, *args):
    subprocess.run([
        "docker",
        "network",
        "connect",
        *args,
        PREFIX + network_name,
        PREFIX + container_name
    ])
    print(f"{container_name} -> {network_name}")

def exec_device(container_name: str, program: str, *args):
    subprocess.run([
        "docker",
        "exec",
        PREFIX + container_name,
        program,
        *args,
    ])


def attach_device(container_name: str, program: str, *args):
    subprocess.run([
        "docker",
        "exec",
        "-it",
        PREFIX + container_name,
        program,
        *args
    ])

def link_device(c1: str, if1: str, c2: str, if2: str, ip1: str | None = None, ip2: str | None = None):
    c1_name = PREFIX + c1
    c2_name = PREFIX + c2
    subprocess.run(["ip", "netns", "exec", c1_name, "ip", "link", "add", "dev", if1, "type", "veth", "peer", "name", if2, "netns", c2_name])

    # Bring up device
    exec_device(c1, "ip", "link", "set", "dev", if1, "up")
    exec_device(c2, "ip", "link", "set", "dev", if2, "up")

    # set ip if configured
    if ip1 is not None:
        intf1 = ipaddress.ip_interface(ip1)
        exec_device(c1, "ip", "addr", "add", ip1, "dev", if1)
        if c1 in hosts.keys():
            hosts[c1] = intf1.ip
            if ip2 is not None:
                exec_device(c1, "ip", "route", "add", "default", "via", str(ipaddress.ip_interface(ip2).ip))
    if ip2 is not None:
        intf2 = ipaddress.ip_interface(ip2)
        exec_device(c2, "ip", "addr", "add", ip2, "dev", if2)
        if c2 in hosts.keys():
            hosts[c2] = intf2.ip
            if ip1 is not None:
                exec_device(c2, "ip", "route", "add", "default", "via", str(ipaddress.ip_interface(ip1).ip))
    
    print(f"{c1}.{if1} -> {c2}.{if2}")

class DockerNet(Cmd):
    prompt = PROMPT

    def do_help(self, arg: str) -> bool | None:
        print("""DockerNet: docker container network emulator
              
Subcommands:
    docker [args]   run docker cli
    clean           clean networks.
    create_network NAME SUBNET
                    create a network with name NAME and with subnet SUBNET.
    create_device NAME IMAGE NETWORK [..args]
                    create a container from image IMAGE with name NAME and attach to network NETWORK.
    connect_device NAME NETWORK [..args]
                    connect a container DEVICE to network NETWORK
    exec_device NAME PROGRAM [..args]
                    run command PROGRAM on container DEVICE
    attach_device NAME PROGRAM [..args]
                    run command PROGRAM on container DEVICE and attach to it
""")
        
    def do_docker(self, args):
        subprocess.run(["docker", *args.split()])

    def do_clean(self, argstr):
        args = argstr.split()
        if len(args) != 0:
            print("Usage: clean")
            return
        try:
            clean_networks()
        except:
            traceback.print_exc()

    def do_pingall(self, argstr):
        args = argstr.split()
        if len(args) != 0:
            print("Usage: pingall")
            return
        try:
            pingall()
        except:
            traceback.print_exc()

    def do_create_network(self, argstr: str):
        args = argstr.split()
        if len(args) != 2:
            print("Usage: create_network NAME SUBNET")
            return
        try:
            name = args[0]
            address = ipaddress.ip_network(args[1])
            create_network(name, address)
        except:
            traceback.print_exc()


    def do_create_device(self, argstr: str):
        args = argstr.split()
        if len(args) < 3:
            print("Usage: create_device NAME IMAGE NETWORK [..args]")
            return
        try:
            name = args[0]
            image_name = args[1]
            network = args[2]
            args = args[3:]
            create_device(name, image_name, network, *args)
        except:
            traceback.print_exc()
    
    def do_create_host(self, argstr: str):
        args = argstr.split()
        if len(args) < 3:
            print("Usage: create_host NAME IMAGE NETWORK [..args]")
            return
        try:
            name = args[0]
            image_name = args[1]
            network = args[2]
            args = args[3:]
            create_host(name, image_name, network, *args)
        except:
            traceback.print_exc()

    def do_connect_device(self, argstr: str):
        args = argstr.split()
        if len(args) < 2:
            print("Usage: connect_device NAME NETWORK [..args]")
            return
        try:
            name = args[0]
            network_name = args[1]
            args = args[2:]
            connect_device(name, network_name, *args)
        except:
            traceback.print_exc()

    def do_link_device(self, argstr: str):
        args = argstr.split()
        if len(args) != 4:
            print("Usage: link_device CONTAINER1 IF1 CONTAINER2 IF2")
            return
        try:
            c1 = args[0]
            if1 = args[1]
            c2 = args[2]
            if2 = args[3]
            link_device(c1, if1, c2, if2)
        except:
            traceback.print_exc()

    def do_exec_device(self, argstr: str):
        args = argstr.split()
        if len(args) < 2:
            print("Usage: exec_device NAME PROGRAM [..args]")
            return
        try:
            name = args[0]
            program = args[1]
            args = args[2:]
            exec_device(name, program, *args)
        except:
            traceback.print_exc()

    def do_attach_device(self, argstr: str):
        args = argstr.split()
        if len(args) < 2:
            print("Usage: attach_device NAME PROGRAM [..args]")
            return
        try:
            name = args[0]
            program = args[1]
            args = args[2:]
            attach_device(name, program, *args)
        except:
            traceback.print_exc()
    
    def do_create_topo(self, argstr: str):
        args = argstr.split()
        if len(args) < 0:
            print("Usage: create_topo")
            return
        try:
            clean_networks()

            create_device("r1", "frrouting/frr", "none",
                          "-v", f"{os.getcwd()}/config/r1:/etc/frr")
            create_device("r2", "frrouting/frr", "none",
                          "-v", f"{os.getcwd()}/config/r2:/etc/frr",)
            create_host("h1", "archlinux", "none")
            create_host("h2", "archlinux", "none")

            link_device("r1", "eth0", "r2", "eth0", "10.0.0.10/29", "10.0.0.11/29")
            link_device("r1", "eth1", "h1", "eth0", "10.0.0.1/29", "10.0.0.2/29")
            link_device("r2", "eth1", "h2", "eth0", "10.0.0.17/29", "10.0.0.18/29")
        except:
            traceback.print_exc()

    def do_exit(self, argstr):
        raise SystemExit
def main_loop():
    if os.geteuid() != 0:
        exit("dockernet.py should be run as root")
    try:
        app = DockerNet()
        app.cmdloop("Welcome to the jungle!")
    finally:
        clean_networks()

if __name__ == "__main__":
    main_loop()