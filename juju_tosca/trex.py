import logging
import operator
import os
import yaml

try:
    from yaml import CSafeLoader as Loader
except ImportError:
    from yaml import SafeLoader as Loader


log = logging.getLogger("tosca.model")

ENTITY_KINDS = ('nodes', 'capabilities', 'relations', 'interfaces')


def yaml_load(content):
    return yaml.load(content, Loader=Loader)


def topological_sort(graph_unsorted):
    """Return sorted nodes. http://bit.ly/1kewbsu
    """
    graph_sorted = []
    graph_unsorted = dict(graph_unsorted)
    while graph_unsorted:
        acyclic = False
        for node, edges in graph_unsorted.items():
            for edge in edges:
                if edge in graph_unsorted:
                    break
            else:
                acyclic = True
                del graph_unsorted[node]
                graph_sorted.append((node, edges))
        if not acyclic:
            raise RuntimeError("A cyclic dependency occurred")
    return graph_sorted


def merge(x, y):
    """merge container types x and y, with y having precendence and return.

    Only y is modified.
    """

    if x is None:
        return y
    elif y is None:
        if isinstance(x, list):
            return list(y)
        elif isinstance(x, dict):
            return dict(x)
    elif type(x) != type(y):
        log.warning("Can't merge type values %s and %s" % (x, y))
        return y
    elif isinstance(y, dict):
        y.update(x)
        return y
    else:
        y.extend(x)
        return y


class TypeHierarchy(object):

    def __init__(self):
        self.nodes = {}
        self.interfaces = {}
        self.relations = {}
        self.capabilities = {}

    def get(self, name, qualified=False, types=None):
        if types is None:
            types = ENTITY_KINDS
        elif isinstance(types, basestring):
            types = [types]
        for t in types:
            assert t in ENTITY_KINDS
            tmap = getattr(self, t)
            cls = tmap.get(name)
            if cls is not None:
                return cls
            if not qualified:
                cls = tmap.get(name)
                if cls is not None:
                    return cls

    def load_schema(self, resource):
        with open(resource) as fh:
            data = yaml_load(fh.read())
        # Process by group
        entity_keys = data.keys()
        for c in ENTITY_KINDS:
            group = [k for k in entity_keys if k.startswith('tosca.%s' % c)]
            getattr(self, 'load_%s' % c)(group, data)

    def load_nodes(self, names, data):
        for n in self._derived_sort(names, data):
            type_info = data[n]
            base = self.nodes.get(type_info.get('derived_from'), Node)
            print n, "base", base
            # TODO Can collapse class hierarchy lookup here.
            cls = type(n.split(".")[-1], (base,), {
                'types': self,
                'tosca_name': n,
                '_requirements': merge(
                    base._requirements, type_info.get('requirements', [])),
                '_interfaces': merge(
                    base._interfaces, type_info.get('interfaces', [])),
                '_properties': merge(
                    base._properties, type_info.get('properties', {})),
                '_capabilities': merge(
                    base._capabilities, type_info.get('capabilities', {}))})
            self.nodes[n] = cls
            self.nodes[cls.__name__] = cls

    def load_relations(self, names, data):
        for n in self._derived_sort(names, data):
            type_info = data[n]
            base = self.relations.get(
                type_info.get('derived_from'), Relation)
            cls = type(n.split(".")[-1], (base,), {
                'types': self,
                'tosca_name': n,
                '_valid_targets': merge(
                    base._valid_targets, type_info.get('valid_targets', [])),
                '_interfaces': merge(
                    base._interfaces, type_info.get('interfaces', {}))})
            self.relations[n] = cls
            self.relations[cls.__name__] = cls

        cls.type_interfaces = [InterfaceType(k, v) for k, v in data.items()]

    def load_capabilities(self, names, data):
        for n in self._derived_sort(names, data):
            type_info = data[n]
            base = self.capabilities.get(
                type_info.get('derived_from'), Capability)
            cls = type(n.split(".")[-1], (base,), {
                'types': self,
                'tosca_name': n,
                '_properties': merge(
                    base._properties, type_info.get('properties', {}))})
            self.capabilities[n] = cls
            self.capabilities[cls.__name__] = cls

    def load_interfaces(self, names, data):
        for n in names:
            self.interfaces[n] = interface = InterfaceType(n, data[n])
            self.interfaces[n.split('.')[-1]] = interface
            interface.tosca_name = n

    def _derived_sort(self, names, data):
        graph = {}
        for n in names:
            base = data.get(n, {}).get('derived_from')
            graph[n] = base and [base] or []
        return [n for n, _ in topological_sort(graph)]


class InterfaceType(object):

    def __init__(self, name, data):
        self.name = name
        self.data = data

    @property
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
            return ["Invalid implementation for %s with %s" % (
                self.action, self.data)]
        return []


class Property(object):

    def __init__(self, name, type, description="",
                 required=False, constraints=None,
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
    """Topology template input value."""


class Output(Value):
    """Topology template output value."""


class Entity(object):

    def __init__(self, name, data, topology=None):
        self.name = name
        self.data = data
        self.topology = topology


class Node(Entity):

    _requirements = None
    _capabilities = None
    _interfaces = None
    _properties = None

    @property
    def capabilities(self):
        capabilities = []
        for k, v in self._capability.items():
            pass
        return capabilities

    @property
    def properties(self):
        properties = []
        for k, v in self.data.get('properties', {}).items():
            if not k in self._properties:
                raise TypeError(
                    "Unknown property:%s defined on type:%s valid:%s" % (
                        k, self.tosca_name, self._properties.keys()))
            properties.append(Property(k, topology=self.topology, **v))
        return properties

    @property
    def requirements(self):
        requirements = []
        for req in self.data.get('requirements', []):
            rel_type = req.get('relation_type')
            if rel_type is None:
                for n in self._requirements:
                    if req.keys() == n.keys():
                        pass
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


class Capability(Entity):

    _properties = None

    @property
    def properties(self):
        pass

    def validate(self):
        return []


class Relation(Entity):

    _valid_targets = None
    _interfaces = None

    def validate(self):
        return []


class Tosca(object):

    schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'defs', 'TOSCA_definition.yaml')

    def __init__(self, data):
        self.data = data
        self.types = TypeHierarchy()
        self.types.load_schema(self.schema_path)

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


def main():
    import pprint
    logging.basicConfig(level=logging.DEBUG)
    types = TypeHierarchy()
    types.load_schema(Tosca.schema_path)
    print "Nodes"

    pprint.pprint(types.nodes)
    print "\nCapabilities"
    pprint.pprint(types.capabilities)
    print "\nRelations"
    pprint.pprint(types.relations)
    print "\nInterfaces"
    pprint.pprint(types.interfaces)

if __name__ == '__main__':
    try:
        main()
    except:
        import pdb, traceback, sys
        traceback.print_exc()
        pdb.post_mortem(sys.exc_info()[-1])

