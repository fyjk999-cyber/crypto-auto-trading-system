"""Conservative static edges; an unresolved receiver is never a safety proof.

shortcut: this resolves direct imports and single constructor bindings only;
injection, inheritance, reassignment and callbacks require explicit review.
"""

import ast
import hashlib


def module_name(path):
    name = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def qualified(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = qualified(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


class Definitions(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.functions = {}
        self.classes = set()

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.classes.add(".".join(self.scope))
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self.functions[".".join(self.scope)] = node
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef


def index_sources(sources, source_sha):
    modules = {}
    definitions = {}
    classes = set()
    for path, raw in sources.items():
        if not path.endswith(".py"):
            continue
        module = module_name(path)
        tree = ast.parse(raw.decode(), filename=path)
        visitor = Definitions()
        visitor.visit(tree)
        imports = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                for alias in node.names:
                    imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
        modules[module] = dict(
            path=path, tree=tree, imports=imports,
            digest=hashlib.sha256(raw).hexdigest(), functions=visitor.functions,
        )
        for name, node in visitor.functions.items():
            definitions[f"{module}.{name}"] = (module, name, node)
        classes.update(f"{module}.{name}" for name in visitor.classes)
    return dict(modules=modules, definitions=definitions, classes=classes, source_sha=source_sha)


def direct_symbol(index, module, name, expression):
    text = qualified(expression)
    if not text:
        return None
    first, *tail = text.split(".")
    function = index["modules"][module]["functions"].get(name)
    if function is not None and first != "self":
        parameters = {a.arg for a in (
            function.args.posonlyargs + function.args.args + function.args.kwonlyargs
        )}
        if function.args.vararg:
            parameters.add(function.args.vararg.arg)
        if function.args.kwarg:
            parameters.add(function.args.kwarg.arg)
        rebound = any(
            isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id == first
            for n in ast.walk(function)
        )
        if first in parameters or rebound:
            return None
    imported = index["modules"][module]["imports"].get(first)
    if imported:
        return ".".join([imported, *tail])
    scopes = name.split(".")[:-1]
    if first == "self" and scopes:
        return ".".join([module, *scopes, *tail])
    for length in range(len(scopes), -1, -1):
        candidate = ".".join([module, *scopes[:length], text])
        if candidate in index["definitions"] or candidate in index["classes"]:
            return candidate
    return None


def calls_in_function(node):
    """Do not attribute nested functions' calls to their outer function."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.Call):
            yield child
        yield from calls_in_function(child)


def resolve_edges(index):
    edges = []
    for caller, (module, name, function) in index["definitions"].items():
        info = index["modules"][module]
        for call in calls_in_function(function):
            symbol = direct_symbol(index, module, name, call.func)
            method = "IMPORT_RESOLVED" if (
                qualified(call.func) or ""
            ).split(".")[0] in info["imports"] else "DIRECT_STATIC"
            if symbol in index["classes"]:
                symbol += ".__init__"
                method = "CONSTRUCTOR_RESOLVED"
            resolved = symbol in index["definitions"]
            callee_info = index["definitions"].get(symbol)
            edges.append(dict(
                edge_id=f"{index['source_sha']}:{info['path']}:{call.lineno}:{call.col_offset}",
                caller_file=info["path"], caller_function=name, caller_id=caller,
                callsite_line=call.lineno, callsite_column=call.col_offset,
                expression=ast.unparse(call),
                callee_id=symbol if resolved else None,
                callee_file=index["modules"][callee_info[0]]["path"] if callee_info else None,
                callee_function=callee_info[1] if callee_info else None,
                resolution_method=method if resolved else "UNRESOLVED",
                source_sha=index["source_sha"], caller_file_sha256=info["digest"],
                applicability="STATIC_BINDING_CANDIDATE_ONLY; MANUAL_ROUTE_PROOF_REQUIRED",
                safety_contract_status="NOT_ESTABLISHED_BY_CALLGRAPH",
            ))
    return edges


def reachable(edges, starting, reverse=False):
    visited = set(starting)
    changed = True
    while changed:
        changed = False
        for edge in edges:
            if edge["resolution_method"] == "UNRESOLVED":
                continue
            source, destination = edge["caller_id"], edge["callee_id"]
            if reverse:
                source, destination = destination, source
            if source in visited and destination not in visited:
                visited.add(destination)
                changed = True
    return visited


def path_crosscheck(edges, entry, sink):
    forward = sink in reachable(edges, {entry})
    backward = entry in reachable(edges, {sink}, reverse=True)
    assert forward == backward
    return dict(forward=forward, reverse=backward, safety="NOT_PROVEN")
