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
import operator
import os
import re
import yaml

try:
    from yaml import CSafeLoader as Loader
except ImportError:
    from yaml import SafeLoader as Loader


log = logging.getLogger("tosca.model")

ENTITY_KINDS = ('nodes', 'capabilities', 'relations', 'interfaces')

ENTITY_TYPE_MAP = dict(zip(
    ENTITY_KINDS,
    ('node_types', 'capability_types', 'relation_types', '')))


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


def get_named_slot(req):
    framework = set((
        'interfaces', 'relationship_type', 'derived_from', 'constraints',
        'lower_bound', 'upper_bound', 'type'))
    keys = set(req.keys())
    remainder = keys - framework
    if len(remainder) != 1:
        raise ValueError("Ambigious relation name %s" % (remainder))
    return remainder.pop()


class TypeHierarchy(object):
    """TOSCA MetaModel Type Container.

    TOSCA has an extensible meta model consisting of node types,
    interfaces, relations, and capabilities. The standard defines a
    core set, but any topology author or engine can extend that set
    with additional entity types that can be used in a topology.

    The type hierarchy models all the entities to be utilized in
    a topology.
    """

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

            # Some basic validation of the type info
            for t in type_info.get('capabilities', {}):
                if not 'type' in t:
                    log.warning('Malformed capability type %s %s', n, t)

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


class ValueResolver(object):
    """Resolve get_property/get_input/get_ref_property for values.
    """
    @staticmethod
    def get_input(self, input_name):
        input = self.topology.get_input(input_name)
        if input is None:
            raise ValueError("Unknown input: %s in property %s" % (
                input_name, self))
        return input.value

    @staticmethod
    def get_ref_property(self, slot_name, capability, property_name=None):
        if property_name is None:
            property_name = capability
            capability = None

        assert isinstance(self, Property), "Ref property needs property"
        template = self.parent
        for req in template.requirements:
            if req.name == slot_name:
                if not capability:
                    p = req.target.get_property(property_name)
                    if p is not None:
                        return p.value
                    raise ValueError(
                        ("Unknown property: %s referenced on: %s"
                         " via slot: %s from: %s") % (
                             property_name,
                             req.name,
                             slot_name,
                             "%s.%s" % (template.name, self.name)))

                for c in req.target.capabilities:
                    if c.name == capability:
                        for p in c.properties:
                            if p.name == property_name:
                                return p.value
                raise ValueError(
                    ("Unknown capability property %s referenced on %s"
                     " via slot: %s from %s") % (
                         "%s.%s" % (capability, property_name),
                         req.name,
                         slot_name,
                         "%s.%s" % (template.name, self.name)))
        raise ValueError(
            "Unknown requirement slot: %s from %s" % (
                slot_name, "%s.%s" % (template.name, self.name)))

    @staticmethod
    def get_property(self, entity_name, property_name):
        entity = self.topology.get_template(entity_name)
        if entity is None:
            raise ValueError(
                "Unknown entity: %s in property %s" % (
                    entity_name, self))
        for p in entity.properties:
            if p.name == property_name:
                return p.value
        raise ValueError("Unknown entity property: %s, %s in property %s" % (
            entity_name, property_name, self))

    @staticmethod
    def resolve(property, value):
        if 'get_input' in value:
            return ValueResolver.get_input(
                property, value['get_input'])
        elif 'get_ref_property' in value:
            return ValueResolver.get_ref_property(
                property, *value['get_ref_property'])
        elif 'get_property' in value:
            return ValueResolver.get_property(
                property, *value['get_property'])
        else:
            raise ValueError(
                "Unknown property value %s" % (property, value))


class Property(object):

    def __init__(self, name, type, description="",
                 required=False, constraints=None,
                 default=None, topology=None, value=None):
        self.name = name
        self.required = required
        self.type = type
        self.constraints = constraints
        self.description = description
        self.default = default
        self.topology = topology
        self._value = value or self.default
        self._parent = None

    @property
    def value(self):
        if not isinstance(self._value, dict):
            return self._value
        return ValueResolver.resolve(self, self._value)

    @property
    def parent(self):
        return self._parent

    def set_parent(self, parent):
        self._parent = parent

    def __repr__(self):
        return "<tosca.Property name:%s type:%s rvalue:%s>" % (
            self.name, self.type, self._value)


class Constraint(object):

    operator_map = {
        'equal': operator.eq,
        'greater_than': operator.gt,
        'greater_or_equal': operator.ge,
        'less_than': operator.lt,
        'less_or_equal': operator.le,
        'in_range': lambda x, y: y in range(x[0], x[1]),
        'valid_values': operator.contains,
        'length': lambda x, y: len(y) == x,
        'min_length': lambda x, y: len(y) > x,
        'max_length': lambda x, y: len(y) < x,
        'pattern': lambda x, y: bool(re.match(x, y))}

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
        self._value = None

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

    @property
    def value(self):
        return self.attrs.get('value')

    def set_value(self, value):
        assert 'value' not in self.attrs
        self.attrs['value'] = value


class Input(Value):
    """Topology template input value."""


class Output(Value):
    """Topology template output value."""

    def __init__(self, name, attrs, topology=None):
        self.name = name
        self.attrs = attrs
        self.topology = topology

    @property
    def value(self):
        value = self.attrs['value']
        if isinstance(value, dict):
            return ValueResolver.resolve(self, value)
        return value


class Entity(object):

    def __init__(self, name, data, topology=None):
        self.name = name
        self.data = data
        self.topology = topology

    def __repr__(self):
        return "<%s name: %s>" % (self.__class__.__name__, self.name)


class PropertyContainer(Entity):

    _properties = None
    _property_key = "properties"
    _property_attr = "_properties"
    _parent = None

    @property
    def properties(self):
        properties = []
        template_properties = self.data.get(self._property_key, {})
        for k, schema in getattr(self, self._property_attr).items():
            v = None
            if k in template_properties:
                v = template_properties[k]
            p = Property(k, topology=self.topology, value=v, **schema)
            # Need parent to resolve get_ref_property functions
            p.set_parent(self._parent or self)
            properties.append(p)
        return properties

    def get_property(self, name):
        schema = getattr(self, self._property_attr).get(name)
        if schema is None:
            return None
        if isinstance(schema, basestring):
            schema = {'type': schema}
        v = self.data.get(self._property_key, {}).get(name, None)
        p = Property(name, topology=self.topology, value=v, **schema)
        p.set_parent(self._parent or self)
        return p


class InterfaceType(object):

    def __init__(self, name, data):
        self.name = name
        self.data = data

    @property
    def operations(self):
        return self.data.keys()

    def description(self, op):
        return self.data.get(op, {}).get('description')


class InterfaceOperation(PropertyContainer):

    _property_key = 'input'

    def __init__(self, name, data, topology, properties=None):
        super(InterfaceOperation, self).__init__(
            name, data, topology)
        self._properties = properties

    @property
    def implementation(self):
        if isinstance(self.data, basestring):
            return self.data
        return self.data.get('implementation')

    def validate(self):
        return []
        if not self.implementation:
            return ["Invalid implementation for %s with %s" % (
                self.name, self.data)]
        return []

    def __repr__(self):
        return "<Operation name:%s impl:%s>" % (
            self.name, self.implementation)


class Node(PropertyContainer):

    _requirements = None
    _capabilities = None
    _interfaces = None

    @property
    def capabilities(self):
        capabilities = []
        for name in self._capabilities.keys():
            capabilities.append(self.get_capability(name))
        return capabilities

    def get_capability(self, name):
        template_capabilities = self.data.get('capabilities', {})
        ctype_info = self._capabilities.get(name)
        if ctype_info is None:
            return
        capability_class = self.types.get(ctype_info['type'])
        data = template_capabilities.get(name, {})
        return capability_class(name, data, self.topology)

    @property
    def requirements(self):
        requirements = []
        template_reqs = {}
        for tmpl_req in self.data.get('requirements', []):
            template_reqs[get_named_slot(tmpl_req)] = tmpl_req
        for req in self._requirements:
            req = dict(req)
            name = get_named_slot(req)
            data = template_reqs.get(name, {})
            req.update(data)
            rel_class = self._get_relation_class(name, req, data)
            requirements.append(rel_class(name, req, self.topology))
        return requirements

    def _get_relation_class(self, name, type_req, template_data):
        rel_type = template_data.get('relation_type')
        if rel_type:
            return self.types.get(rel_type)
        if name == 'host':
            return self.types.get('HostedOn')
        elif name == 'dependency':
            return self.types.get('DependsOn')
        else:
            return self.types.get("ConnectsTo")

    @property
    def interfaces(self):
        interfaces = []
        # interface usage by templates typically isn't scoped enough
        # to allow for multiple interfaces. intended usage is a single
        # lifecycle per node or relation.
        if isinstance(self._interfaces, list):
            interface_type = self.types.get(
                self._interfaces[0], types=('interfaces',))
            idata = {}
        else:
            idata = self._interfaces[self._interfaces.keys()[0]]
            interface_type = self.types.get(
                self._interfaces.keys()[0], types=('interfaces',))

        template_data = self.data.get('interfaces', {})
        # TODO: Carry forward interface level properties to operation
        for op in interface_type.operations:
            interfaces.append(
                InterfaceOperation(
                    op, template_data.get(op, {}),
                    self.topology, idata.get('inputs')))
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


class Capability(PropertyContainer):

    def validate(self):
        return []


class Relation(Entity):
    """
    A relation can point to another tmpleate within the graph, or
    be defined as unbound resource for the engine to fill.
    """
    _valid_targets = None
    _interfaces = None

    @property
    def target(self):
        entity_name = self.data[self.name]
        if isinstance(entity_name, basestring):
            if entity_name.startswith('tosca.'):  # also unbound
                log.info("Unbound relation reference %s" % self.data)
                return None
            return self.topology.get_template(entity_name)
        else:
            log.info("Unbound relation reference %s" % self.data)
        # If we have an anonymous requirement specification, it needs
        # to be bound to this resource.
        return None

    def validate(self):
        return []


class Tosca(object):

    schema_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'tosca_schema.yaml')

    def __init__(self, data):
        self.data = data
        self.types = TypeHierarchy()
        self.types.load_schema(self.schema_path)
        self._load_template_schema()

    def _load_template_schema(self):
        for k, v in ENTITY_TYPE_MAP.items():
            if not v or not v in self.data:
                continue
            loader = getattr(self.types, 'load_%s' % k)
            loader(self.data[v].keys(), self.data[v])

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
        for k, v in values.items():
            input = self.get_input(k)
            if input is None:
                raise ValueError("Unknown input %s" % k)
            input.set_value(v)

    @property
    def outputs(self):
        outputs = []
        for k, v in self.data.get('outputs', {}).items():
            outputs.append(Output(k, v, self))
        return outputs

    def get_output(self, name):
        value = self.data.get('outputs', {}).get(name)
        if value is None:
            return value
        return Output(name, value, self)

    @property
    def nodetemplates(self):
        nodes = []
        for k, v in self.data.get('node_templates', {}).items():
            node_type = v.get('type')
            node_cls = self.types.get(node_type)
            if node_cls is None:
                raise TypeError(
                    "Unknown node template type %s for %s" % (
                        node_type, k))
            nodes.append(node_cls(k, v, self))
        return nodes

    def get_template(self, name):
        value = self.data.get('node_templates', {}).get(name)
        if value is None:
            return value
        node_cls = self.types.get(value.get('type'))
        if node_cls is None:
            raise TypeError(
                "Unknown node template type %s for %s" % (
                    value.get('type'), name))
        return node_cls(name, value, self)

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
