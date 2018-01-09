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
import json
from shutil import copyfile
from time import sleep
from subprocess import check_output, check_call, CalledProcessError

import requests
from charmhelpers.core.hookenv import (
    status_set,
    open_port,
    unit_public_ip,
    charm_dir,
    config,
)

from charms.reactive import set_state, when, when_not


CHE_VERSION = "6.0.0-M4"


@when("docker.available")
@when_not("che.available")
def run_che():
    status_set('maintenance', 'Installing Eclipse Che')
    # Start and stop Che so che's config is generated
    start_che()
    add_juju_stack()
    stop_che()
    copyfile("{}/templates/project-template-charms.json".format(charm_dir()),
             "/home/ubuntu/instance/data/templates/project-template-charms.json")
    copyfile("{}/templates/project-template-interface.json".format(charm_dir()),
             "/home/ubuntu/instance/data/templates/project-template-interface.json")
    copyfile("{}/templates/project-template-layer.json".format(charm_dir()),
             "/home/ubuntu/instance/data/templates/project-template-layer.json")
    # Start Che for real
    start_che()
    # opened ports are used by `juju expose` so It's important to open all
    # ports a user connects to.
    open_port('8080', protocol="TCP")           # Port to the UI
    open_port('32768-65535', protocol="TCP")    # Ports to the workspaces
    status_set('active', 'Ready (eclipse/che)')
    set_state('che.available')


@when('editor.available', 'che.available')
def configure_http_relation(editor_relation):
    editor_relation.configure(port=8080)


def start_che():
    # This container isn't Che. This container starts Che. This should be run
    # in interactive mode, but this container waits until it can reach che on
    # its public_ip. On a public cloud, public_ip might only be accessible
    # after running `juju expose`, so this might never exit. Because of this
    # reason, we run the container in daemon mode, check che's status ourselves
    # and kill the container manually after Che is up.
    print('Starting Che...')
    container_id = check_output([
        'docker', 'run',
        '-id',
        '-v', '/var/run/docker.sock:/var/run/docker.sock',
        '-v', '/home/ubuntu/:/data',
        '-e', 'CHE_HOST={}'.format(unit_public_ip()),
        '-e', 'CHE_DOCKER_IP_EXTERNAL={}'.format(unit_public_ip()),
        'eclipse/che:{}'.format(CHE_VERSION),
        'start',
        '--fast'], universal_newlines=True).rstrip()
    wait_until_che_running()
    print('Che Started!')
    print('Stopping Startup Container...')
    try:
        sys.stdout.flush()
        check_call(['docker', 'stop', container_id])
    except CalledProcessError:
        # container has already stopped
        print("Killing startup container failed.")
    print("Removing startup container...")
    sys.stdout.flush()
    check_call(['docker', 'rm', container_id])
    print("Startup container removed!")


def wait_until_che_running():
    print('Waiting for che to come online.. This might take a few minutes.')
    while True:
        try:
            response = requests.get('http://localhost:8080')
            if response.status_code == 200:
                break
        except (requests.exceptions.ConnectionError) as err:
            print(err)
            print("retrying..")
        sleep(1)
    print('Che is online!')


def stop_che():
    print('Stopping Che...')
    sys.stdout.flush()
    check_call([
        'docker', 'run',
        '-i',
        '--rm',
        '-v', '/var/run/docker.sock:/var/run/docker.sock',
        '-v', '/home/ubuntu/:/data',
        '-e', 'CHE_HOST={}'.format(unit_public_ip()),
        '-e', 'CHE_DOCKER_IP_EXTERNAL={}'.format(unit_public_ip()),
        'eclipse/che:{}'.format(CHE_VERSION),
        'stop'])
    print('Che is stopped!')


def add_juju_stack():
    # Add Juju stack
    try:
        url = "http://localhost:8080/api/stack"
        headers = {'Content-Type': 'application/json',
                   'Accept': 'application/json'}
        with open("{}/templates/stack-juju-charm.json".format(charm_dir()), 'r') as stackfile:
            stackdata = json.load(stackfile)
        response = requests.post(url, data=json.dumps(stackdata), headers=headers)
        if response.status_code != 201:
            print("Could not create Juju stack.")
        json_response = json.loads(response.text)
        juju_stack_id = json_response['id']
    except requests.exceptions.ConnectionError as err:
        print(err)
    # Add Juju stack icon
    try:
        url = "http://localhost:8080/api/stack/" + juju_stack_id + '/icon'
        response = requests.post(url, files={'body': open("{}/templates/type-juju.svg".format(charm_dir()), "rb")})
        if response.status_code != 200:
            print("Juju stack icon upload failed.")
    except requests.exceptions.ConnectionError as err:
        print(err)

