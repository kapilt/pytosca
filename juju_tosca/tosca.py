import operator
import yaml


def yaml_load(content):
    return yaml.load(content, loader=yaml.CSafeLoader)


class TypeRoot(object):

    @classmethod
    def load_definitions(cls, prefix, resource):
        with open(resource) as fh:
            data = yaml_load(fh.read())

        class_map = {'%s.Root' % prefix: cls}

        for sub in cls.__subclasses__():
            class_map['%s.%s' % prefix: sub]

        cls.type_class_map = class_map
        cls.type_data = data
        #set(data.keys()).inter

    def get_inherited_meta(cls, key):
        pass

    def get_parents(cls):
        pass


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
    def interfaces(self):
        pass

    @property
    def capabiltiies(self):
        pass

    @property
    def properties(self):
        pass

    @property
    def depends_on(self):
        pass

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


class Software(Node):
    pass


class DBMS(Software):
    pass


class Database(DBMS):
    pass

#########


class Capability(TypeRoot):

    @property
    def properties(self):
        pass


class Container(Capability):
    pass


class Endpoint(Capability):
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
