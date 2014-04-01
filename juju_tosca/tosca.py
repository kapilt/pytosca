import logging
import operator
import os
import yaml

try:
    from yaml import CSafeLoader as Loader
except ImportError:
    from yaml import SafeLoader as Loader


log = logging.getLogger("tosca.model")


def yaml_load(content):
    return yaml.load(content, Loader=Loader)


def get_subclasses(klass):
    subclasses = []
    for cls in klass.__subclasses__():
        subclasses.append(cls)
        subclasses.extend(get_subclasses(cls))
    return subclasses


def get_baseclasses(klass):
    parents = []
    for cls in klass.__bases__:
        parents.append(cls)
        parents.extend(get_baseclasses(cls))
    return parents


class TypeRoot(object):

    DEBUG = True

    def __init__(self, name, data, topology=None):
        self.name = name
        self.data = data
        self.topology = topology

    @classmethod
    def load_definitions(cls, prefix, resource):
        assert cls.__bases__ == (TypeRoot,), "Load from root of hierarchy"

        with open(resource) as fh:
            data = yaml_load(fh.read())

        # map from tosca name to class
        class_map = {'%s.Root' % prefix: cls}

        for sub in reversed(get_subclasses(cls)):
            key = getattr(sub, 'tosca_name', None)
            if key is None:
                key = '%s.%s' % (prefix, sub.__name__)
                sub.tosca_name = key
            class_map[key] = sub

        cls.type_class_map = class_map
        cls.type_def = data
        if cls.DEBUG:
            missing = set(data.keys()).difference(class_map.keys())
            if missing:
                log.warning("Missing Types %s" % (", ".join(missing)))

    @classmethod
    def load_interfaces(cls, resource):
        with open(resource) as fh:
            data = yaml_load(fh.read())
        cls.type_interfaces = [InterfaceType(k, v) for k, v in data.items()]

    @classmethod
    def load_properties(cls, resource):
        with open(resource) as fh:
            data = yaml_load(fh.read())
        for k in cls.type_def.keys():
            if not data.get(k):
                continue
            properties = data.get(k)
            property_map = {}
            for name, schema in properties.items():
                property_map[name] = Property(name, **schema)
            cls.type_def[k]['properties'] = property_map

    @classmethod
    def get_type_value(cls, key):
        """Get merged inherited value
        """
        candidates = get_baseclasses(cls)
        candidates.insert(0, cls)

        value = None
        for t in candidates:
            if t.__bases__ == (TypeRoot,):
                break
            v = cls.type_def.get(t.tosca_name).get(key)
            if v is None:
                continue
            elif value is None:
                value = v
            elif isinstance(v, dict):
                value.update(v)
            elif isinstance(v, list):
                value.extend(v)
            else:
                raise ValueError(
                    "Invalid type meta key:%s previous:%s next:%s type:%s",
                    key, value, v, t.tosca_name)
        return value


class InterfaceType(object):

    def __init__(self, name, data):
        self.name = name
        self.data = data

    def action_names(self):
        return self.data.keys()

    def description(self, action):
        return self.data.get(action, {}).get('description')


class Interface(object):

    def __init__(self, action, data, topology=None):
        self.action = action
        self.data = data
        self.topology = topology

    @property
    def implementation(self):
        if isinstance(self.data, basestring):
            return self.data
        return self.data.get('implementation')

    def validate(self):
        if not self.implementation:
            return ["Invalid implementattion for %s with %s" % (
                self.action, self.data)]
        return []


class Property(object):

    def __init__(self, name, type,
                 required=False, constraints=None, description="",
                 default=None, topology=None):
        self.name = name
        self.required = required
        self.type = type
        self.constraints = constraints
        self.description = description
        self.default = default


class Constraint(object):

    operator_map = {
        'equal': operator.eq,
        'greater_than': operator.gt,
        'greater_or_equal': operator.ge,
        'less_than': operator.lt,
        'less_or_equal': operator.le,
        'in_range': None,
        'valid_values': operator.contains,
        'length': None,
        'min_length': None,
        'max_length': None,
        'pattern': None}

    @classmethod
    def validate(cls, constraint_type, constraint, value):
        if constraint_type not in cls.operator_map:
            raise ValueError("Unknown constraint type %s" % constraint_type)
        op = cls.operator_map[constraint_type]
        return op(constraint, value)


#########
# Nodes

class Node(TypeRoot):

    # Type access
    @classmethod
    def get_type(cls, type_name):
        return cls.type_class_map.get(type_name)

    @property
    def type_interfaces(self):
        return self.get_type_value('interfaces')

    @property
    def type_operations(self):
        ops = []
        for t in self.type_interfaces:
            ops.extend(t.action_names())
        return ops

    @property
    def type_capabilities(self):
        return self.get_type_value('capabilities')

    @property
    def type_properties(self):
        return self.get_type_value('properties')

    @property
    def type_relations(self):
        return self.get_type_value('requirements')

    # Instance access
    @property
    def capabilities(self):
        capabilities = []
        for c in self.data.get('capabilities', {}).items():
            pass
        return capabilities

    @property
    def properties(self):
        properties = []
        for k, v in self.data.get('properties', {}).items():
            properties.append(Property(k, topology=self.topology, **v))
        return properties

    @property
    def requirements(self):
        requirements = []
        aliases = set(Relation.get_relation_aliases())
        for req in self.data.get('requirements', []):
            rel_type = req.get('relation_type')
            if not rel_type:
                for a in aliases:
                    if a in req:
                        rel_type = a
                        break
                if rel_type is None:
                    raise TypeError("Unknown relation type %s" % rel_type)
                rel_class = Relation.get_relation_type_from_alias(rel_type)
            else:
                rel_class = Relation.get_relation_type(rel_type)
            requirements.append(rel_class(self.name, req, self.topology))
        return requirements

    @property
    def interfaces(self):
        interfaces = []
        allowed_ops = self.type_operations
        for k, v in self.data.get('interfaces', {}).items():
            if not k in allowed_ops:
                raise ValueError(
                    "Invalid interface operation %s valid are %s" % (
                        k, allowed_ops))
            interfaces.append(Interface(k, v, self.topology))
        return interfaces

    def validate(self):
        errors = []
        for r in self.requirements:
            errors.extend(r.validate())
        for p in self.properties:
            errors.extend(r.validate())
        for i in self.interfaces:
            errors.extend(i.validate())
        for c in self.capabilities:
            errors.extend(c.validate())
        return errors


# Actualized classes are just examples for interaction at the moment.

class Compute(Node):
    """
    num_cpus,
    disk_size,
    mem_size,
    os_arch,
    os_type,
    os_distribution
    os_version
    ip_address
    """


class SoftwareComponent(Node):
    pass


class DBMS(SoftwareComponent):
    pass


class Database(DBMS):
    pass


class WebServer(SoftwareComponent):
    pass


class Wordpress(SoftwareComponent):
    tosca_name = "tosca.nodes.WebApplication.WordPress"

#########
# Capabilities


class Capability(TypeRoot):

    @property
    def properties(self):
        pass

    def validate(self):
        return []


# Actualized classes are just examples for interaction at the moment.

class Feature(Capability):
    pass


class Container(Capability):
    pass


class Endpoint(Capability):
    pass


class DatabaseEndpoint(Endpoint):
    pass

#########
# Relations


class Relation(TypeRoot):

    @classmethod
    def get_relation_type_from_alias(cls, alias):
        for rel_type, data in cls.type_def.items():
            if alias in data.get('aliases', ()):
                return cls.type_class_map[rel_type]
        raise TypeError("Unknown relation alias %s" % alias)

    @classmethod
    def get_relation_type(cls, name):
        return cls.type_class_map[name]

    @classmethod
    def get_relation_aliases(cls):
        aliases = []
        for rel_type, data in cls.type_def.items():
            aliases.extend(data.get('aliases', ()))
        return aliases

    def validate(self):
        return []


# Actualized classes are just examples for interaction at the moment.

class DependsOn(Relation):
    pass


class HostedOn(Relation):
    pass


class ConnectsTo(Relation):
    pass


########
# Tosca profile/graph
class Value(object):
    def __init__(self, name, attrs):
        self.name = name
        self.attrs = attrs
        self.value = None

    @property
    def type(self):
        return self.attrs['type']

    @property
    def description(self):
        return self.attrs['description']

    @property
    def default(self):
        return self.attrs.get('default')

    @property
    def constraints(self):
        return self.attrs.get('constraints')

    def set_value(self, value):
        assert self.value is None
        self.value = value


class Input(Value):
    pass


class Output(Value):
    pass


class Tosca(object):

    def __init__(self, data):
        self.data = data

    @property
    def tosca_version(self):
        return self.data['tosca_definitions_version']

    @property
    def template_name(self):
        return self.data.get('template_name')

    @property
    def template_author(self):
        return self.data.get('template_author')

    @property
    def template_version(self):
        return self.data.get('template_version')

    @property
    def description(self):
        return self.data['description']

    @property
    def inputs(self):
        inputs = []
        for k, v in self.data.get('inputs', {}).items():
            inputs.append(Input(k, v))
        return inputs

    def get_input(self, name):
        value = self.data.get('inputs', {}).get(name)
        if value is None:
            return value
        return Input(name, value)

    def bind_inputs(self, values):
        for k, v in values:
            input = self.get_input(k)
            if input is None:
                raise ValueError("Unknown input %s" % k)
            input.set_value(v)

    @property
    def outputs(self):
        outputs = []
        for k, v in self.data.get('outputs', {}).items():
            outputs.append(Output(k, v))
        return outputs

    def get_output(self, name):
        value = self.data.get('outputs', {}).get(name)
        if value is None:
            return value
        return Output(name, value)

    @property
    def nodetemplates(self):
        nodes = []
        for k, v in self.data.get('node_templates', {}).items():
            node_type = v.get('type')
            node_cls = Node.get_type(node_type)
            if node_cls is None:
                raise TypeError(
                    "Unknown node template type %s for %s" % (
                        node_type, k))
            nodes.append(Node(k, v, self))
        return nodes

    def get_template(self, name):
        value = self.data.get('node_templates', {}).get(name)
        if value is None:
            return value
        node_cls = Node.get_type(value.get('type'))
        if node_cls is None:
            raise TypeError(
                "Unknown node template type %s for %s" % (
                    value.get('type'), name))
        return node_cls(name, value)

    # More advanced properties
    @property
    def imports(self):
        return self.data.get('imports', ())

    @property
    def node_types(self):
        return self.data.get('node_types', ())

    @property
    def capability_types(self):
        return self.data.get('capability_types', ())

    @property
    def relationship_types(self):
        return self.data.get('relationship_types', ())

    @property
    def artifact_types(self):
        return self.data.get('artifact_types', ())

    @property
    def groups(self):
        return self.data.get('groups', ())

    @classmethod
    def load(cls, path):
        with open(path) as fh:
            data = yaml_load(fh.read())
        return cls(data)


def init():

    base_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'defs')

    Node.load_definitions(
        'tosca.nodes',
        os.path.join(base_path, 'nodetypesdef.yaml'))
    Node.load_interfaces(
        os.path.join(base_path, 'interfaces_node.yaml'))
    Node.load_properties(
        os.path.join(base_path, 'nodetypeschema.yaml'))

    Capability.load_definitions(
        'tosca.capabilities',
        os.path.join(base_path, 'capabilitytype_def.yaml'))

    Relation.load_definitions(
        'tosca.relationships',
        os.path.join(base_path, 'relationshiptype_def.yaml'))
    Relation.load_interfaces(
        os.path.join(base_path, 'interfaces_relationship.yaml'))

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    init()
