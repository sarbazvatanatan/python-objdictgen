"""Nosis - XML Pickling."""
# This a stripped down version of legacy tool "gnosis", which is
# central to the "OD" format. This is basically a XML pickler for
# python objects. # The original tool was written for very old
# python and this is an updated extract of the original to be able
# to use it with python 3
#
# Copyright (C) 2022-2024  Svein Seldal, Laerdal Medical AS
# Copyright (C): <Unknown Author(s)>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301
# USA

import ast
import logging
import re
import sys
import io
from xml.dom import minidom

log = logging.getLogger('objdictgen.nosis')


class _EmptyClass:
    """ Do-nohting empty class """


TYPE_IN_BODY = {
    int: 0,
    float: 0,
    complex: 0,
    str: 0,
}

# Regexp patterns
PAT_FL = r'[-+]?(((((\d+)?[.]\d+|\d+[.])|\d+)[eE][+-]?\d+)|((\d+)?[.]\d+|\d+[.]))'
PAT_INT = r'[-+]?[1-9]\d*'
PAT_FLINT = f'({PAT_FL}|{PAT_INT})'    # float or int
PAT_COMPLEX = f'({PAT_FLINT})?[-+]{PAT_FLINT}[jJ]'
PAT_COMPLEX2 = f'({PAT_FLINT}):({PAT_FLINT})'

# Regexps for parsing numbers
RE_FLOAT = re.compile(PAT_FL + r'$')
RE_ZERO = re.compile(r'[+-]?0$')
RE_INT = re.compile(PAT_INT + r'$')
RE_LONG = re.compile(r'[-+]?\d+[lL]$')
RE_HEX = re.compile(r'([-+]?)(0[xX])([0-9a-fA-F]+)$')
RE_OCT = re.compile(r'([-+]?)(0)([0-7]+)$')
RE_COMPLEX = re.compile(PAT_COMPLEX + r'$')
RE_COMPLEX2 = re.compile(PAT_COMPLEX2 + r'$')


def aton(s):
    # -- massage the string slightly
    s = s.strip()
    while s[0] == '(' and s[-1] == ')':  # remove optional parens
        s = s[1:-1]

    # -- test for cases
    if RE_ZERO.match(s):
        return 0

    if RE_FLOAT.match(s):
        return float(s)

    if RE_LONG.match(s):
        return int(s.rstrip('lL'))

    if RE_INT.match(s):
        return int(s)

    m = RE_HEX.match(s)
    if m:
        n = int(m.group(3), 16)
        if n < sys.maxsize:
            n = int(n)
        if m.group(1) == '-':
            n = n * (-1)
        return n

    m = RE_OCT.match(s)
    if m:
        n = int(m.group(3), 8)
        if n < sys.maxsize:
            n = int(n)
        if m.group(1) == '-':
            n = n * (-1)
        return n

    if RE_COMPLEX.match(s):
        return complex(s)

    if RE_COMPLEX2.match(s):
        r, i = s.split(':')
        return complex(float(r), float(i))

    raise ValueError(f"Invalid string '{s}'")


# we use ntoa() instead of repr() to ensure we have a known output format
def ntoa(num: int|float|complex) -> str:
    """Convert a number to a string without calling repr()"""
    if isinstance(num, int):
        return str(num)

    if isinstance(num, float):
        s = f"{num:.17g}"
        # ensure a '.', adding if needed (unless in scientific notation)
        if '.' not in s and 'e' not in s:
            s = s + '.'
        return s

    if isinstance(num, complex):
        # these are always used as doubles, so it doesn't
        # matter if the '.' shows up
        return f"{num.real:.17g}+{num.imag:.17g}j"

    raise ValueError(f"Unknown numeric type: {repr(num)}")


XML_QUOTES = (
    ('&', '&amp;'),
    ('<', '&lt;'),
    ('>', '&gt;'),
    ('"', '&quot;'),
    ("'", '&apos;'),
)


def safe_string(s):
    """Quote XML entries"""
    for repl in XML_QUOTES:
        s = s.replace(repl[0], repl[1])
    # for others, use Python style escapes
    return repr(s)[1:-1]  # without the extra single-quotes


def unsafe_string(s):
    """Recreate the original string from the string returned by safe_string()"""
    # Unqoute XML entries
    for repl in XML_QUOTES:
        s = s.replace(repl[1], repl[0])

    s = s.replace("'", "\\x27")  # Need this to not interfere with ast

    tree = ast.parse("'" + s + "'", mode='eval')
    if isinstance(tree.body, ast.Constant):
        return tree.body.s
    raise ValueError(f"Invalid string '{s}' passed to unsafe_string()")


def safe_content(s):
    """Markup XML entities and strings so they're XML & unicode-safe"""
    # Quote XML entries
    for repl in XML_QUOTES:
        s = s.replace(repl[0], repl[1])
    return s


def unsafe_content(s):
    """Take the string returned by safe_content() and recreate the
    original string."""
    # Unqoute XML entries
    for repl in XML_QUOTES:
        s = s.replace(repl[1], repl[0])
    return s


# Maintain list of object identities for multiple and cyclical references
# (also to keep temporary objects alive)
VISITED = {}


# entry point expected by XML_Pickle
def thing_from_dom(filehandle):
    global VISITED  # pylint: disable=global-statement
    VISITED = {}  # Reset the visited collection
    return _thing_from_dom(minidom.parse(filehandle), None)


def _save_obj_with_id(node, obj):
    objid = node.getAttribute('id')
    if len(objid):  # might be None, or empty - shouldn't use as key
        VISITED[objid] = obj


# Store the objects that can be pickled
CLASS_STORE = {}


def add_class_to_store(classname='', klass=None):
    """Put the class in the store (as 'classname')"""
    if classname and klass:
        CLASS_STORE[classname] = klass


def obj_from_node(node):
    """Given a <PyObject> node, return an object of that type.
    __init__ is NOT called on the new object, since the caller may want
    to do some additional work first.
    """
    classname = node.getAttribute('class')
    # allow <PyObject> nodes w/out module name
    # (possibly handwritten XML, XML containing "from-air" classes,
    # or classes placed in the CLASS_STORE)
    klass = CLASS_STORE.get(classname)
    if klass is None:
        raise ValueError(f"Cannot create class '{classname}'")
    return klass.__new__(klass)


def get_node_valuetext(node):
    """Get text from node, whether in value=, or in element body."""

    # we know where the text is, based on whether there is
    # a value= attribute. ie. pickler can place it in either
    # place (based on user preference) and unpickler doesn't care

    if 'value' in node._attrs:  # pylint: disable=protected-access
        # text in tag
        ttext = node.getAttribute('value')
        return unsafe_string(ttext)

    # text in body
    node.normalize()
    if node.childNodes:
        return unsafe_content(node.childNodes[0].nodeValue)
    return ''


def xmldump(filehandle=None, obj=None, omit=None):
    """Create the XML representation as a string."""

    stream = filehandle
    if filehandle is None:
        stream = io.StringIO()

    _pickle_toplevel_obj(stream, obj, omit)

    if filehandle is None:
        stream.flush()
        return stream.getvalue()


def xmlload(filehandle):
    """Load pickled object from file fh."""

    if isinstance(filehandle, str):
        filehandle = io.StringIO(filehandle)
    elif isinstance(filehandle, bytes):
        filehandle = io.BytesIO(filehandle)

    return thing_from_dom(filehandle)


def _pickle_toplevel_obj(fh, py_obj, omit=None):
    """handle the top object -- add XML header, etc."""

    # Store the ref id to the pickling object (if not deepcopying)
    global VISITED  # pylint: disable=global-statement
    id_ = id(py_obj)
    VISITED = {
        id_: py_obj
    }

    # note -- setting family="obj" lets us know that a mutator was used on
    # the object. Otherwise, it's tricky to unpickle both <PyObject ...>
    # and <.. type="PyObject" ..> with the same code. Having family="obj" makes
    # it clear that we should slurp in a 'typeless' object and unmutate it.

    # note 2 -- need to add type= to <PyObject> when using mutators.
    # this is b/c a mutated object can still have a class= and
    # module= that we need to read before unmutating (i.e. the mutator
    # mutated into a PyObject)

    famtype = ''  # unless we have to, don't add family= and type=

    klass = py_obj.__class__
    klass_tag = klass.__name__

    # Generate the XML string
    # if klass not in CLASS_STORE.values():
    module = klass.__module__.replace('objdictgen.', '')  # Workaround to be backwards compatible
    extra = f'{famtype}module="{module}" class="{klass_tag}"'
    # else:
    #     extra = f'{famtype} class="{klass_tag}"'

    fh.write('<?xml version="1.0"?>\n'
                '<!DOCTYPE PyObject SYSTEM "PyObjects.dtd">\n')

    if id_ is not None:
        fh.write(f'<PyObject {extra} id="{id_}">\n')
    else:
        fh.write(f'<PyObject {extra}>\n')

    pickle_instance(py_obj, fh, level=0, omit=omit)
    fh.write('</PyObject>\n')


def pickle_instance(obj, fh, level=0, omit=None):
    """Pickle the given object into a <PyObject>

    Add XML tags to list. Level is indentation (for aesthetic reasons)
    """
    # concept: to pickle an object:
    #
    #   1. the object attributes (the "stuff")
    #
    # There is a twist to this -- instead of always putting the "stuff"
    # into a container, we can make the elements of "stuff" first-level
    # attributes, which gives a more natural-looking XML representation of the
    # object.

    stuff = obj.__dict__

    # decide how to save the "stuff", depending on whether we need
    # to later grab it back as a single object
    if isinstance(stuff, dict):
        # don't need it as a single object - save keys/vals as
        # first-level attributes
        for key, val in stuff.items():
            if omit and key in omit:
                continue
            fh.write(_attr_tag(key, val, level))
    else:
        raise ValueError(f"'{obj}.__dict__' is not a dict")


def unpickle_instance(node):
    """Take a <PyObject> or <.. type="PyObject"> DOM node and unpickle
    the object."""

    # we must first create an empty obj of the correct	type and place
    # it in VISITED{} (so we can handle self-refs within the object)
    pyobj = obj_from_node(node)
    _save_obj_with_id(node, pyobj)

    # slurp raw thing into a an empty object
    raw = _thing_from_dom(node, _EmptyClass())
    stuff = raw.__dict__

    # finally, decide how to get the stuff into pyobj
    if isinstance(stuff, dict):
        for k, v in stuff.items():
            setattr(pyobj, k, v)

    else:
        # subtle -- this can happen either because the class really
        # does violate the pickle protocol
        raise ValueError("Non-dict violates pickle protocol")

    return pyobj


# --- Functions to create XML output tags ---
def _attr_tag(name, thing, level=0):
    start_tag = '  ' * level + f'<attr name="{name}" '
    close_tag = '  ' * level + '</attr>\n'
    return _tag_completer(start_tag, thing, close_tag, level)


def _item_tag(thing, level=0):
    start_tag = '  ' * level + '<item '
    close_tag = '  ' * level + '</item>\n'
    return _tag_completer(start_tag, thing, close_tag, level)


def _entry_tag(key, val, level=0):
    start_tag = '  ' * level + '<entry>\n'
    close_tag = '  ' * level + '</entry>\n'
    start_key = '  ' * level + '  <key '
    close_key = '  ' * level + '  </key>\n'
    key_block = _tag_completer(start_key, key, close_key, level + 1)
    start_val = '  ' * level + '  <val '
    close_val = '  ' * level + '  </val>\n'
    val_block = _tag_completer(start_val, val, close_val, level + 1)
    return start_tag + key_block + val_block + close_tag


def _tag_compound(start_tag, family_type, thing, extra=''):
    """Make a start tag for a compound object, handling refs.
    Returns (start_tag,do_copy), with do_copy indicating whether a
    copy of the data is needed.
    """
    idt = id(thing)
    if VISITED.get(idt):
        start_tag = f'{start_tag}{family_type} refid="{idt}" />\n'
        return (start_tag, 0)

    start_tag = f'{start_tag}{family_type} id="{idt}" {extra}>\n'
    return (start_tag, 1)


#
# This doesn't fit in any one place particularly well, but
# it needs to be documented somewhere. The following are the family
# types currently defined:
#
#   obj - thing with attributes and possibly coredata
#
#   uniq - unique thing, its type gives its value, and vice versa
#
#   map - thing that maps objects to other objects
#
#   seq - thing that holds a series of objects
#
#         Note - Py2.3 maybe the new 'Set' type should go here?
#
#   atom - non-unique thing without attributes (e.g. only coredata)
#
#   lang - thing that likely has meaning only in the
#          host language (functions, classes).
#
#          [Note that in Gnosis-1.0.6 and earlier, these were
#           mistakenly placed under 'uniq'. Those encodings are
#           still accepted by the parsers for compatibility.]
#

def _family_type(family, typename, mtype, mextra):
    """Create a type= string for an object, including family= if necessary.
    typename is the builtin type, mtype is the mutated type (or None for
    non-mutants). mextra is mutant-specific data, or None."""
    if mtype is None:
        # family tags are technically only necessary for mutated types.
        # we can intuit family for builtin types.
        return f'type="{typename}"'

    if mtype and len(mtype):
        if mextra:
            mextra = f'extra="{mextra}"'
        else:
            mextra = ''
        return f'family="{family}" type="{mtype}" {mextra}'
    return f'family="{family}" type="{typename}"'


# Encodings for builtin types.
TYPENAMES = {
    'None': 'none',
    'dict': 'map',
    'list': 'seq',
    'tuple': 'seq',
    'numeric': 'atom',
    'string': 'atom',
    'bytes': 'atom',
    'PyObject': 'obj',
    'function': 'lang',
    'class': 'lang',
    'True': 'uniq',
    'False': 'uniq',
}


def _fix_family(family, typename):
    """
    If family is None or empty, guess family based on typename.
    (We can only guess for builtins, of course.)
    """
    if family and len(family):
        return family  # sometimes it's None, sometimes it's empty ...

    typename = TYPENAMES.get(typename)
    if typename is not None:
        return typename
    raise ValueError(f"family= must be given for unknown type '{typename}'")


def _tag_completer(start_tag, orig_thing, close_tag, level):
    tag_body = []

    mtag = None
    thing = orig_thing
    in_body = TYPE_IN_BODY.get(type(orig_thing), 0)
    mextra = None

    if thing is None:
        ft = _family_type('none', 'None', None, None)
        start_tag = f"{start_tag}{ft} />\n"
        close_tag = ''

    # bool cannot be used as a base class (see sanity check above) so if thing
    # is a bool it will always be BooleanType, and either True or False
    elif isinstance(thing, bool):
        if thing is True:
            typestr = 'True'
        else:  # must be False
            typestr = 'False'

        ft = _family_type('uniq', typestr, mtag, mextra)
        if in_body:
            start_tag = f"{start_tag}{ft}>"
            close_tag = close_tag.lstrip()
        else:
            start_tag = f'{start_tag}{ft} value="" />\n'
            close_tag = ''

    elif isinstance(thing, (int, float, complex)):
        # thing_str = repr(thing)
        thing_str = ntoa(thing)

        ft = _family_type("atom", "numeric", mtag, mextra)
        if in_body:
            # we don't call safe_content() here since numerics won't
            # contain special XML chars.
            # the unpickler can either call unsafe_content() or not,
            # it won't matter
            start_tag = f'{start_tag}{ft}>{thing_str}'
            close_tag = close_tag.lstrip()
        else:
            start_tag = f'{start_tag}{ft} value="{thing_str}" />\n'
            close_tag = ''

    elif isinstance(thing, str):
        ft = _family_type("atom", "string", mtag, mextra)
        if in_body:
            start_tag = f'{start_tag}{ft}>{safe_content(thing)}'
            close_tag = close_tag.lstrip()
        else:
            start_tag = f'{start_tag}{ft} value="{safe_string(thing)}" />\n'
            close_tag = ''

    # General notes:
    #   1. When we make references, set type to referenced object
    #      type -- we don't need type when unpickling, but it may be useful
    #      to someone reading the XML file
    #   2. For containers, we have to stick the container into visited{}
    #      before pickling subitems, in case it contains self-references
    #      (we CANNOT just move the visited{} update to the top of this
    #      function, since that would screw up every _family_type() call)
    elif isinstance(thing, tuple):
        start_tag, do_copy = _tag_compound(
            start_tag, _family_type('seq', 'tuple', mtag, mextra),
            orig_thing)
        if do_copy:
            for item in thing:
                tag_body.append(_item_tag(item, level + 1))
        else:
            close_tag = ''

    elif isinstance(thing, list):
        start_tag, do_copy = _tag_compound(
            start_tag, _family_type('seq', 'list', mtag, mextra),
            orig_thing)
        # need to remember we've seen container before pickling subitems
        VISITED[id(orig_thing)] = orig_thing
        if do_copy:
            for item in thing:
                tag_body.append(_item_tag(item, level + 1))
        else:
            close_tag = ''

    elif isinstance(thing, dict):
        start_tag, do_copy = _tag_compound(
            start_tag, _family_type('map', 'dict', mtag, mextra),
            orig_thing)
        # need to remember we've seen container before pickling subitems
        VISITED[id(orig_thing)] = orig_thing
        if do_copy:
            for key, val in thing.items():
                tag_body.append(_entry_tag(key, val, level + 1))
        else:
            close_tag = ''

    else:
        raise ValueError(f"Non-handled type {type(thing)}")

    # need to keep a ref to the object for two reasons -
    #  1. we can ref it later instead of copying it into the XML stream
    #  2. need to keep temporary objects around so their ids don't get reused
    VISITED[id(orig_thing)] = orig_thing

    return start_tag + ''.join(tag_body) + close_tag


def _thing_from_dom(dom_node, container=None):
    """Converts an [xml_pickle] DOM tree to a 'native' Python object"""
    for node in dom_node.childNodes:
        if not hasattr(node, '_attrs') or not node.nodeName != '#text':
            continue

        if node.nodeName == "PyObject":
            container = unpickle_instance(node)
            try:
                id_ = node.getAttribute('id')
                VISITED[id_] = container
            except KeyError:
                pass  # Accepable, not having id only affects caching

        elif node.nodeName in ['attr', 'item', 'key', 'val']:
            node_family = node.getAttribute('family')
            node_type = node.getAttribute('type')
            node_name = node.getAttribute('name')

            # check refid first (if present, type is type of referenced object)
            ref_id = node.getAttribute('refid')

            if len(ref_id):	 # might be empty or None
                if node.nodeName == 'attr':
                    setattr(container, node_name, VISITED[ref_id])
                else:
                    container.append(VISITED[ref_id])

                # done, skip rest of block
                continue

            # if we didn't find a family tag, guess (do after refid check --
            # old pickles will set type="ref" which _fix_family can't handle)
            node_family = _fix_family(node_family, node_type)

            node_valuetext = get_node_valuetext(node)

            # step 1 - set node_val to basic thing
            if node_family == 'none':
                node_val = None
            elif node_family == 'atom':
                node_val = node_valuetext
            elif node_family == 'seq':
                # seq must exist in VISITED{} before we unpickle subitems,
                # in order to handle self-references
                seq = []
                _save_obj_with_id(node, seq)
                node_val = _thing_from_dom(node, seq)
            elif node_family == 'map':
                # map must exist in VISITED{} before we unpickle subitems,
                # in order to handle self-references
                mapping = {}
                _save_obj_with_id(node, mapping)
                node_val = _thing_from_dom(node, mapping)
            elif node_family == 'uniq':
                # uniq is another special type that is handled here instead
                # of below.
                if node_type == 'True':
                    node_val = True
                elif node_type == 'False':
                    node_val = False
                else:
                    raise ValueError(f"Unknown uniq type {node_type}")
            else:
                raise ValueError(f"Unknown family {node_family},{node_type},{node_name}")

            # step 2 - take basic thing and make exact thing
            # Note there are several NOPs here since node_val has been decided
            # above for certain types. However, I left them in since I think it's
            # clearer to show all cases being handled (easier to see the pattern
            # when doing later maintenance).

            # pylint: disable=self-assigning-variable
            if node_type == 'None':
                node_val = None
            elif node_type == 'numeric':
                node_val = aton(node_val)
            elif node_type == 'string':
                node_val = node_val
            elif node_type == 'list':
                node_val = node_val
            elif node_type == 'tuple':
                # subtlety - if tuples could self-reference, this would be wrong
                # since the self ref points to a list, yet we're making it into
                # a tuple. it appears however that self-referencing tuples aren't
                # really all that legal (regular pickle can't handle them), so
                # this shouldn't be a practical problem.
                node_val = tuple(node_val)
            elif node_type == 'dict':
                node_val = node_val
            elif node_type == 'True':
                node_val = node_val
            elif node_type == 'False':
                node_val = node_val
            else:
                raise ValueError(f"Unknown type {node},{node_type}")

            if node.nodeName == 'attr':
                setattr(container, node_name, node_val)
            else:
                container.append(node_val)

            _save_obj_with_id(node, node_val)

        elif node.nodeName == 'entry':
            keyval = _thing_from_dom(node, [])
            key, val = keyval[0], keyval[1]
            container[key] = val
            # <entry> has no id for refchecking

        else:
            raise ValueError(f"Element {node.nodeName} is not in PyObjects.dtd")

    return container
