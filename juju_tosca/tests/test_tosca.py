import inspect
import os

from juju_tosca import tosca
from unittest import TestCase

tosca.init()

TEST_DATA = os.path.join(
    os.path.dirname(inspect.getabsfile(tosca)), 'tests', 'data')


class TestMetaModel(TestCase):

    def test_meta_model(self):
        wordpress = tosca.Wordpress('blog', {})
        self.assertEqual(
            wordpress.tosca_name, "tosca.nodes.WebApplication.WordPress")
        self.assertEqual(
            wordpress.type_capabilities,
            {'containee': {'type': "Containee",
                           'container_types': ['tosca.nodes.Compute']}})
        self.assertEqual(
            sorted(wordpress.type_properties.keys()),
            ['admin_password', 'admin_user', 'db_host', 'version'])

        self.assertEqual(
            wordpress.type_relations,
            [{'database_endpoint': 'tosca.nodes.MySQL'},
             {'host': 'tosca.nodes.Compute'}])


class TestWordpressMysqlTosca(TestCase):

    def setUp(self):
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
            sorted(wordpress.type_operations),
            ['configure', 'create', 'delete', 'start', 'stop'])

        self.assertEqual(
            [r.__class__.__name__ for r in wordpress.requirements],
            ['HostedOn', 'ConnectsTo'])
