import shlex
import os
import sys
import logging
import time
import json
import urllib2
from unittest import TestCase
from subprocess import Popen, PIPE

import paramiko

from devops.helpers import wait, tcp_ping, http

from . import ci
from integration.helpers import HTTPClient, SSHClient

logging.basicConfig(format=':%(lineno)d: %(asctime)s %(message)s', level=logging.DEBUG)

SOLO_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "agent")
DEPLOY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "bin", "deploy")
COOKBOOKS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "cookbooks")
SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "ci")
SAMPLE_REMOTE_PATH = "/home/ubuntu"

class StillPendingException(Exception):
    pass



class TestNode(TestCase):
    def __init__(self, *args, **kwargs):
        super(TestNode, self).__init__(*args, **kwargs)
        self.client = HTTPClient()
        self.remote = SSHClient()

    def test_node(self):
        cookbook_remote_path = os.path.join(SAMPLE_REMOTE_PATH, "sample-cook")
        release_remote_path = os.path.join(SAMPLE_REMOTE_PATH, "sample-release.json")

        logging.info("Starting slave node")
        admin_node = ci.environment.node['admin']
        admin_ip = admin_node.ip_address
        node = ci.environment.node['slave']
        node.start()
        
        slave_id = node.interfaces[0].mac_address.replace(":", "").upper()

        while True:
            logging.info("Waiting for slave agent to run...")
            nodes = json.loads(self.client.get(
                "http://%s:8000/api/nodes" % admin_ip
            ))
            time.sleep(15)
            if len(nodes) > 0:
                logging.info("Node found")
                break

        cluster = json.loads(self.client.post(
            "http://%s:8000/api/clusters" % admin_ip,
            data='{ "name": "MyOwnPrivateCluster", "release": 1 }',
            log=True
        ))

        resp = json.loads(self.client.put(
            "http://%s:8000/api/clusters/1" % admin_ip,
            data='{ "nodes": ["%s"] }' % slave_id
        ))

        cluster = json.loads(self.client.get(
            "http://%s:8000/api/clusters/1" % admin_ip
        ))
        if len(cluster["nodes"]) == 0:
            raise ValueError("Failed to add node into cluster")

        resp = json.loads(self.client.put(
            "http://%s:8000/api/nodes/%s" % (admin_ip, slave_id),
            data='{ "new_roles": [1, 2], "redeployment_needed": true }'
        ))
        if len(resp["new_roles"]) == 0:
            raise ValueError("Failed to assign roles to node")

        """
        self.remote.connect_ssh(host, "ubuntu", "r00tme")

        self.remote.rmdir(cookbook_remote_path)
        self.remote.rmdir(os.path.join(SAMPLE_REMOTE_PATH, "cookbooks"))
        self.remote.rmdir(os.path.join(SAMPLE_REMOTE_PATH, "solo"))

        self.remote.scp(
            os.path.join(SAMPLE_PATH, "sample-release.json"),
            release_remote_path
        )

        self.remote.mkdir(os.path.join(SAMPLE_REMOTE_PATH, "solo"))
        self.remote.mkdir(os.path.join(SAMPLE_REMOTE_PATH, "solo/config"))

        self.remote.scp(
            DEPLOY_PATH,
            os.path.join(SAMPLE_REMOTE_PATH, "deploy")
        )
        self.remote.scp(
            os.path.join(SOLO_PATH, "solo.json"),
            os.path.join(SAMPLE_REMOTE_PATH, "solo", "config", "solo.json")
        )
        self.remote.scp(
            os.path.join(SOLO_PATH, "solo.rb"),
            os.path.join(SAMPLE_REMOTE_PATH, "solo", "config", "solo.rb")
        )

        self.remote.scp_d(
            os.path.join(SAMPLE_PATH, "sample-cook"),
            SAMPLE_REMOTE_PATH
        )
        self.remote.scp_d(
            COOKBOOKS_PATH,
            SAMPLE_REMOTE_PATH
        )

        self.remote.aquire_sudo()

        commands = [
            "rm -rf /opt/nailgun/nailgun.sqlite",
            "source /opt/nailgun-venv/bin/activate",
            "python /opt/nailgun/manage.py syncdb --noinput",
            "deactivate",
            "cat /opt/nailgun/.ssh/id_rsa.pub > /root/.ssh/authorized_keys",
            "chmod 600 /root/.ssh/authorized_keys",
            "chown nailgun:nailgun /opt/nailgun/nailgun.sqlite",
            "/opt/nailgun/bin/install_cookbook %s" % cookbook_remote_path,
            "/opt/nailgun/bin/create_release %s" % release_remote_path,
            "cp %s/deploy /opt/nailgun/bin" % SAMPLE_REMOTE_PATH,
            "chmod 775 /opt/nailgun/bin/deploy",
            "chown nailgun:nailgun /opt/nailgun/bin/deploy",
            "rm /tmp/chef_success",
            "rm -rf %s/nodes/" % SAMPLE_REMOTE_PATH,
            "chef-solo -l debug -c %s -j %s" % (
                os.path.join(SAMPLE_REMOTE_PATH, "solo", "config", "solo.rb"),
                os.path.join(SAMPLE_REMOTE_PATH, "solo", "config", "solo.json")
            ),
        ]

        for cmd in commands:
            self.remote.exec_cmd(cmd)
        """
        logging.info("Provisioning...")
        task = json.loads(self.client.put(
            "http://%s:8000/api/clusters/1/changes/" % admin_ip,
            log=True
        ))
        task_id = task['task_id']
        logging.info("Task created: %s" % task_id)

        time.sleep(2)

        while True:
            try:
                task = json.loads(self.client.get(
                    "http://%s:8000/api/tasks/%s/" % (admin_ip, task_id)
                ))
                self.check_tasks(task)
                break
            except StillPendingException:
                pass

        """
        # check if recipes executed
        ret = self.remote.exec_cmd("test -f /tmp/chef_success && echo 'SUCCESS'")
        if not "SUCCESS" in ret.split("\r\n")[1:]:
            raise Exception("Recipe failed to execute!")
        # check recipes execution order
        ret = self.remote.exec_cmd("cat /tmp/chef_success")
        if not ret.split("\r\n")[1:-1] == ['monitor', 'default', 'compute']:
            raise Exception("Recipes executed in a wrong order: %s!" \
                % str(ret.split("\r\n")[1:-1]))

        # check passwords
        self.remote.exec_cmd("tar -C %s -xvf /root/nodes.tar.gz" % SAMPLE_REMOTE_PATH)
        ret = self.remote.exec_cmd("cat %s/nodes/`ls nodes` && echo" % SAMPLE_REMOTE_PATH)
        solo_json = json.loads(ret.split("\r\n")[1:-1][0])
        gen_pwd = solo_json['service']['password']
        if not gen_pwd or gen_pwd == 'password':
            raise Exception("Password generation failed!")

        self.remote.disconnect()
        """

    def check_tasks(self, task):
        if task['status'] != 'SUCCESS':
            if task['status'] == 'PENDING':
                raise StillPendingException("Task %s is still pending")
            raise Exception(
                "Task %s failed!\n %s" %
                (task['task_id'], str(task)),
            )
        if 'subtasks' in task and task['subtasks']:
            for subtask in task['subtasks']:
                self.check_tasks(subtask)
