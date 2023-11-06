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

def create_device(name: str, image_name: str, network: str, *args):
    subprocess.run(["docker",
                    "run",
                    "-dit",
                    "--rm",
                    "--name",
                    PREFIX + name,
                    "--network",
                    PREFIX + network,
                    "--privileged",
                    *args,
                    image_name])
    subprocess.run(["docker", "exec", PREFIX + name, "ip", "route", "flush", "0/0"])
    print(f"{name} -> {network}")

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
            create_network("net0", ipaddress.ip_network("10.0.0.0/29"))
            create_network("net1", ipaddress.ip_network("10.0.0.8/29"))
            create_network("net2", ipaddress.ip_network("10.0.0.16/29"))

            create_device("r1", "frrouting/frr", "net0",
                          "-v", f"{os.getcwd()}/config/r1:/etc/frr",
                          "--ip", "10.0.0.2"),
            connect_device("r1", "net1",
                           "--ip", "10.0.0.10")
            create_device("h1", "archlinux", "net0",
                          "--ip", "10.0.0.3")
            exec_device("h1",
                        "ip", "route", "add", "default", "via", "10.0.0.2")


            create_device("r2", "frrouting/frr", "net2",
                          "-v", f"{os.getcwd()}/config/r2:/etc/frr",
                          "--ip", "10.0.0.18"),
            connect_device("r2", "net1",
                           "--ip", "10.0.0.11")
            create_device("h2", "archlinux", "net2",
                          "--ip", "10.0.0.19")
            exec_device("h2",
                        "ip", "route", "add", "default", "via", "10.0.0.18")
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
