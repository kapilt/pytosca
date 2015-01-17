# Copyright 2014-2015 Kapil Thangavelu <kapil.foss@gmail.com>
#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
import inspect
import StringIO
import os

from pytosca import tosca
from unittest import TestCase


TEST_DATA = os.path.join(
    os.path.dirname(inspect.getabsfile(tosca)), 'tests', 'data')


class BaseTest(TestCase):

    def capture_logging(self, name="", level=logging.INFO,
                        log_file=None, formatter=None):
        if log_file is None:
            log_file = StringIO.StringIO()
        log_handler = logging.StreamHandler(log_file)
        if formatter:
            log_handler.setFormatter(formatter)
        logger = logging.getLogger(name)
        logger.addHandler(log_handler)
        old_logger_level = logger.level
        logger.setLevel(level)

        @self.addCleanup
        def reset_logging():
            logger.removeHandler(log_handler)
            logger.setLevel(old_logger_level)
        return log_file


class TestTypeHierarchy(BaseTest):

    def setUp(self):
        self.log_output = self.capture_logging(
            'tosca.model', level=logging.DEBUG)
        self.types = tosca.TypeHierarchy()
        self.types.load_schema(tosca.Tosca.schema_path)

    def test_wordpress_type_inheritance(self):
        wordpress_class = self.types.get('WordPress')
        blog = wordpress_class('blog', {})
        self.assertEqual(
            set([p.name for p in blog.properties]),
            set(("admin_user", "db_host", "admin_password")))
        self.assertEqual(
            ['feature'],
            [c.name for c in blog.capabilities])

    def test_webserver_type_inheritance(self):
        webserver = self.types.get('WebServer')('apache', {})
        self.assertEqual(
            set(('http_endpoint', 'https_endpoint', 'host', 'feature')),
            set([c.name for c in webserver.capabilities]))
        self.assertEqual(
            set((op.name for op in webserver.interfaces)),
            set(('start', 'create', 'configure', 'stop', 'delete')))
        self.assertTrue(isinstance(webserver, tosca.Node))

    def test_interface_property_inheritance(self):
        blog = self.types.get('WordPress')('blog', {})
        ops = [i for i in blog.interfaces if i.name == 'configure']
        ops = ops[0]
        self.assertEqual(
            ops.get_property('db_password').value, None)


class TestComputeOnlyTosca(BaseTest):
    def setUp(self):
        self.log_output = self.capture_logging(
            'tosca.model', level=logging.DEBUG)
        self.topology = tosca.Tosca.load(
            os.path.join(TEST_DATA, 'tosca_compute_only.yaml'))

    def test_input_property_resolution(self):
        self.topology.bind_inputs({'cpus': 4})
        server = self.topology.get_template('my_server')
        p = server.get_property('num_cpus')
        self.assertEqual(p.value, 4)

    def test_output_value_resolution(self):
        instance_ip = self.topology.get_output('instance_ip')
        self.assertEqual(instance_ip.value, None)
        server = self.topology.get_template('my_server')
        # Orchestration engine populates/binds after allocation.
        server.data['properties']['ip_address'] = '192.168.1.10'
        self.assertEqual(instance_ip.value, '192.168.1.10')


class TestWordpressMysqlTosca(BaseTest):

    def setUp(self):
        self.log_output = self.capture_logging(
            'tosca.model', level=logging.DEBUG)
        self.topology = tosca.Tosca.load(
            os.path.join(TEST_DATA, 'tosca_single_instance_wordpress.yaml'))

    def test_inputs(self):
        self.assertEqual(
            ['cpus', 'db_name', 'db_port', 'db_pwd', 'db_root_pwd', 'db_user'],
            sorted([i.name for i in self.topology.inputs]))
        cpus = self.topology.get_input('cpus')
        self.assertEqual(cpus.type, 'number')

    def test_outputs(self):
        self.assertEqual(
            ['website_url'], [i.name for i in self.topology.outputs])
        url = self.topology.get_output('website_url')
        self.assertEqual(url.description, 'URL for Wordpress wiki.')

    def test_node_templates(self):
        self.assertEqual(
            sorted([n.name for n in self.topology.nodetemplates]),
            ['mysql_database',
             'mysql_dbms',
             'server',
             'webserver',
             'wordpress'])
        wordpress = self.topology.get_template('wordpress')
        self.assertEqual(wordpress.validate(), [])
        self.assertEqual(
            set([r.name for r in wordpress.requirements]),
            set(['database_endpoint', 'dependency', 'host']))

    def test_node_requirements_resolution(self):
        wordpress = self.topology.get_template('wordpress')
        req_map = dict([
            (r.name, r) for r in wordpress.requirements if r.target])
        reqs = dict([(k, r.target.name) for k, r in req_map.items()])
        self.assertEqual(reqs,
                         {'host': 'webserver',
                          'database_endpoint': 'mysql_database'})

        self.assertTrue(isinstance(
            req_map['host'],
            self.topology.types.get('HostedOn')))
        self.assertTrue(isinstance(
            req_map['database_endpoint'],
            self.topology.types.get('ConnectsTo')))

    def test_node_operation_input(self):
        self.topology.bind_inputs(
            {'cpus': 2, 'db_name': 'blog', 'db_user': 'wpadmin',
             'db_pwd': 'secret', 'db_root_pwd': 'supersecret',
             'db_port': 3107})
        wordpress = self.topology.get_template('wordpress')
        ops = [i for i in wordpress.interfaces if i.name == 'configure']
        ops = ops[0]
        self.assertEqual(
            ops.get_property('db_password').value, 'secret')

    def test_node_capability_property(self):
        self.topology.bind_inputs(
            {'cpus': 2, 'db_name': 'blog', 'db_user': 'wpadmin',
             'db_pwd': 'secret', 'db_root_pwd': 'supersecret',
             'db_port': 3107})
        db = self.topology.get_template('mysql_database')
        endpoint = db.get_capability('database_endpoint')
        self.assertEqual(
            endpoint.get_property('port').value, 3107)


class TestMongoNode(BaseTest):

    def setUp(self):
        self.log_output = self.capture_logging(
            'tosca.model', level=logging.DEBUG)
        self.topology = tosca.Tosca.load(
            os.path.join(TEST_DATA, 'mongo-node.yaml'))

    def test_template_types(self):
        self.assertEqual(
            sorted([
                nt.name for nt in self.topology.nodetemplates]),
            ['app', 'app_server', 'mongo_db',
             'mongo_dbms', 'mongo_server'])
