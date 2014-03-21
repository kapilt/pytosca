import logging
import operator
import yaml


log = logging.getLogger("tosca.model")


def yaml_load(content):
    return yaml.safe_load(content)


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

    @classmethod
    def load_definitions(cls, prefix, resource):
        assert cls.__bases__ == (TypeRoot,), "Load from root of hierarchy"

        with open(resource) as fh:
            data = yaml_load(fh.read())

        # map from tosca name to class
        class_map = {'%s.Root' % prefix: cls}

        for sub in get_subclasses(cls):
            key = getattr(sub, 'tosca_name', None)
            if key is None:
                key = '%s.%s' % (prefix, sub.__name__)
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
        cls.type_interfaces = [Interface(k, v) for k, v in data.items()]

    @classmethod
    def load_properties(cls, resource):
        with open(resource) as fh:
            data = yaml_load(fh.read())
        cls.type_properties = data

    @classmethod
    def get_type_value(cls, key):
        """Get merged inherited value
        """
        candidates = get_baseclasses(cls)
        candidates.insert(0, cls)
        candidates.pop(-1)

        value = None
        for t in candidates:
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


class Interface(object):

    def __init__(self, name, data):
        self.name = name
        self.data = data

    def action_names(self):
        return self.data.keys()

    def description(self, action):
        return self.data.get(action, {}).get('description')


class Property(object):

    def __init__(self, name, type,
                 required=False, constraints=None, description=""):
        self.name = name
        self.required = required
        self.type = type
        self.constraints = constraints
        self.description = description


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

# schema centric view

class Node(TypeRoot):

    @property
    def type_interfaces(self):
        return self.get_type_value('interfaces')

    @property
    def type_capabilities(self):
        return self.get_type_value('capabilities')

    @property
    def type_properties(self):
        return self.get_type_value('properties')

    @property
    def type_relations(self):
        return self.get_type_value('requirements')

    @property
    def hosted_on(self):
        pass

    @property
    def connects_to(self):
        pass


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


class Capability(TypeRoot):

    @property
    def properties(self):
        pass


class Feature(Capability):
    pass


class Container(Capability):
    pass


class Endpoint(Capability):
    pass


class DatabaseEndpoint(Endpoint):
    pass

#########


class Relation(TypeRoot):
    pass


class DependsOn(Relation):
    pass


class HostedOn(Relation):
    pass


class ConnectsTo(Relation):
    pass


def init():
    Node.load_definitions(
        'tosca.nodes', 'defs/nodetypesdef.yaml')
    Node.load_interfaces(
        'defs/interfaces_node.yaml')
    Capability.load_definitions(
        'tosca.capabilities', 'defs/capabilitytype_def.yaml')
    Relation.load_definitions(
        'tosca.relationships', 'defs/relationshiptype_def.yaml')
    Relation.load_interfaces(
        'defs/interfaces_relationship.yaml')

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    init()
