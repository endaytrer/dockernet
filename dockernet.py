#!/usr/bin/env python3
import subprocess
import docker
import docker.types
import ipaddress
import traceback
import os
from cmd import Cmd
PREFIX = "dn-"
PROMPT = "dn> "
client = docker.from_env()

def clean_networks():
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

def create_device(name: str, image_name: str, network: str, **kwargs):
    client.containers.run(
        image_name,
        name=PREFIX + name,
        tty=True,
        detach=True,
        privileged=True,
        remove=True,
        network=PREFIX + network,
        **kwargs)

def connect_device(container_name: str, network_name: str, **kwargs):
    network = client.networks.list(names=[PREFIX + network_name])[0]
    network.connect(PREFIX + container_name, **kwargs)

def attach_device(container_name: str, program: str, **kwargs):
    container = client.containers.list(filters={
        "name": PREFIX + container_name
    })[0]
    container.exec_run(program, stdin=True, tty=True, **kwargs)

def argv_to_kwargs(*argv: str) -> dict[str, str]:
    return {i.split("=")[0]: i.split("=")[1] for i in argv}

class DockerNet(Cmd):
    prompt = PROMPT

    def do_help(self, arg: str) -> bool | None:
        print("""DockerNet: docker container network emulator
              
Subcommands:
    docker [args]   run docker cli
    clean           clean networks.
    create-network NAME SUBNET
                    create a network with name NAME and with subnet SUBNET.
    create-device NAME IMAGE NETWORK [kwargs]
                    create a container from image IMAGE with name NAME and attach to network NETWORK.
                    kwargs are also available in format `arg1=val1 arg2=val2`
    connect-device NAME NETWORK [kwargs]
                    connect a container DEVICE to network NETWORK
    attach-device NAME PROGRAM [kwargs]
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


    def do_create_network(self, argstr: str):
        args = argstr.split()
        if len(args) != 2:
            print("Usage: create-network NAME SUBNET")
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
            print("Usage: create-device NAME IMAGE NETWORK [kwargs]")
            return
        try:
            name = args[0]
            image_name = args[1]
            network = args[2]
            kwargs = argv_to_kwargs(*args[3:])
            create_device(name, image_name, network, **kwargs)
        except:
            traceback.print_exc()
    
    def do_connect_device(self, argstr: str):
        args = argstr.split()
        if len(args) < 2:
            print("Usage: connect-device NAME NETWORK [kwargs]")
            return
        try:
            name = args[0]
            network_name = args[1]
            kwargs = argv_to_kwargs(*args[2:])
            connect_device(name, network_name, **kwargs)
        except:
            traceback.print_exc()

    def do_attach_device(self, argstr: str):
        args = argstr.split()
        if len(args) < 2:
            print("Usage: attach-device NAME PROGRAM [kwargs]")
            return
        try:
            name = args[0]
            program = args[1]
            kwargs = argv_to_kwargs(*args[2:])
            attach_device(name, program, **kwargs)
        except:
            traceback.print_exc()
    
    def do_create_topo(self, argstr: str):
        args = argstr.split()
        if len(args) < 0:
            print("Usage: create_topo")
            return
        try:
            clean_networks()
            create_network("net0", ipaddress.ip_network("10.0.0.0/29"))
            create_network("net1", ipaddress.ip_network("10.0.0.8/29"))
            create_network("net2", ipaddress.ip_network("10.0.0.16/29"))

            # create_device("r1", "frrouting/frr", "net0", mounts=[
            #     docker.types.Mount("/etc/frr", f"{os.getcwd()}/config/r1"),
            #     docker.types.Mount("/var/log", f"{os.getcwd()}/log/r1")
            # ])
            create_device("r1", "frrouting/frr", "net0")
            connect_device("r1", "net1")
            create_device("h1", "archlinux", "net0")


            # create_device("r2", "frrouting/frr", "net2", mounts=[
            #     docker.types.Mount("/etc/frr", f"{os.getcwd()}/config/r2"),
            #     docker.types.Mount("/var/log", f"{os.getcwd()}/log/r2")
            # ])
            create_device("r2", "frrouting/frr", "net0")
            connect_device("r2", "net1")
            create_device("h2", "archlinux", "net2")
        except:
            traceback.print_exc()

    def do_exit(self, argstr):
        raise SystemExit

if __name__ == "__main__":
    try:
        app = DockerNet()
        app.cmdloop("Welcome to the jungle!")
    finally:
        clean_networks()
