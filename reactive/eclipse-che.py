#!/usr/bin/env python3
# Copyright (C) 2016  Ghent University
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import sys
from subprocess import check_output, check_call, CalledProcessError, call
from time import sleep

import requests
from charmhelpers.core.hookenv import (
    status_set,
    open_port,
    unit_public_ip,
    log)
from charms import layer
from charms.reactive import set_flag, when, when_not

CHE_VERSION = "6.9.0"
HOME = "/home/ubuntu"
DATA_DIRECTORY = HOME + "/data"
ASSEMBLY_DIRECTORY = HOME + "/assembly"

options = layer.options('eclipse-che')


@when("docker.available")
@when_not("che.available")
def run_che():
    status_set('maintenance', 'Installing Eclipse Che')
    # Build custom assembly
    build_assembly()
    # Start and stop Che so che's config is generated
    start_che()
    # opened ports are used by `juju expose` so It's important to open all
    # ports a user connects to.
    open_port('8080', protocol="TCP")  # Port to the UI
    open_port('32768-65535', protocol="TCP")  # Ports to the workspaces
    open_port('5050', protocol="TCP")
    status_set('active', 'Ready (eclipse/che)')
    set_flag('che.available')


@when('editor.available', 'che.available')
def configure_http_relation(editor_relation):
    editor_relation.configure(port=8080)


def build_assembly():
    assembly_image = options.get('assembly', '')
    if assembly_image:
        call(['docker', 'run', '-v', HOME + '/.m2:/root/.m2', '-v', ASSEMBLY_DIRECTORY + ':/assembly',
              assembly_image])


def start_che():
    # This container isn't Che. This container starts Che. This should be run
    # in interactive mode, but this container waits until it can reach che on
    # its public_ip. On a public cloud, public_ip might only be accessible
    # after running `juju expose`, so this might never exit. Because of this
    # reason, we run the container in daemon mode, check che's status ourselves
    # and kill the container manually after Che is up.
    log('Starting Che...')
    container_id = check_output([
        'docker', 'run',
        '-id',
        '-v', '/var/run/docker.sock:/var/run/docker.sock',
        '-v', DATA_DIRECTORY + ':/data',
        '-v', ASSEMBLY_DIRECTORY + ':/assembly',
        '-e', 'CHE_HOST={}'.format(unit_public_ip()),
        '-e', 'CHE_DOCKER_IP_EXTERNAL={}'.format(unit_public_ip()),
        '-e', 'CHE_MULTIUSER=true',
        'eclipse/che:{}'.format(CHE_VERSION),
        'start',
        '--fast'], universal_newlines=True).rstrip()
    wait_until_che_running()
    log('Che Started!')
    log('Stopping Startup Container...')
    try:
        sys.stdout.flush()
        check_call(['docker', 'stop', container_id])
    except CalledProcessError:
        # container has already stopped
        log("Killing startup container failed.")
    log("Removing startup container...")
    sys.stdout.flush()
    check_call(['docker', 'rm', container_id])
    log("Startup container removed!")


def wait_until_che_running():
    log('Waiting for che to come online.. This might take a few minutes.')
    while True:
        try:
            response = requests.get('http://localhost:8080')
            if response.status_code == 200:
                break
        except requests.exceptions.ConnectionError as err:
            log(err)
            log("retrying..")
        sleep(100)
    log('Che is online!')
