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
        scoped_imports = {}
        for name, function in visitor.functions.items():
            local = {}
            for node in body_nodes(function):
                if isinstance(node, ast.ImportFrom) and node.level == 0:
                    for alias in node.names:
                        local[alias.asname or alias.name] = f"{node.module}.{alias.name}"
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        local[alias.asname or alias.name.split(".")[0]] = (
                            alias.name if alias.asname else alias.name.split(".")[0]
                        )
            scoped_imports[name] = local
        modules[module] = dict(
            path=path,
            tree=tree,
            imports=imports,
            digest=hashlib.sha256(raw).hexdigest(),
            functions=visitor.functions,
            scoped_imports=scoped_imports,
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
    module_writes = [
        qualified(n)
        for n in body_nodes(index["modules"][module]["tree"])
        if isinstance(n, (ast.Name, ast.Attribute)) and isinstance(n.ctx, (ast.Store, ast.Del))
    ]
    if any(value == first or value == text for value in module_writes):
        return None
    function = index["modules"][module]["functions"].get(name)
    if function is not None and first != "self":
        parameters = {
            a.arg
            for a in (function.args.posonlyargs + function.args.args + function.args.kwonlyargs)
        }
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
    info = index["modules"][module]
    imported = {**info["imports"], **info["scoped_imports"].get(name, {})}.get(first)
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


def body_nodes(node):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield child
        yield from body_nodes(child)


def call_contexts(function):
    contexts = {}

    def walk(node, context):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(node, ast.Call):
            contexts[(node.lineno, node.col_offset)] = context
        if isinstance(node, ast.If):
            walk(node.test, context)
            for child in node.body:
                walk(child, context + [dict(kind="IF", test=ast.unparse(node.test))])
            for child in node.orelse:
                walk(child, context + [dict(kind="ELSE", test=ast.unparse(node.test))])
            return
        if isinstance(node, ast.ExceptHandler):
            context = context + [
                dict(kind="EXCEPT", exception=ast.unparse(node.type) if node.type else "BARE")
            ]
        for child in ast.iter_child_nodes(node):
            walk(child, context)

    for node in function.body:
        walk(node, [])
    return contexts


def resolve_edges(index):
    edges = []
    for caller, (module, name, function) in index["definitions"].items():
        info = index["modules"][module]
        contexts = call_contexts(function)
        for call in calls_in_function(function):
            symbol = direct_symbol(index, module, name, call.func)
            method = (
                "IMPORT_RESOLVED"
                if (qualified(call.func) or "").split(".")[0] in info["imports"]
                else "DIRECT_STATIC"
            )
            if symbol in index["classes"]:
                symbol += ".__init__"
                method = "CONSTRUCTOR_RESOLVED"
            resolved = symbol in index["definitions"]
            callee_info = index["definitions"].get(symbol)
            edges.append(
                dict(
                    edge_id=f"{index['source_sha']}:{info['path']}:{call.lineno}:{call.col_offset}",
                    caller_file=info["path"],
                    caller_function=name,
                    caller_id=caller,
                    callsite_line=call.lineno,
                    callsite_column=call.col_offset,
                    expression=ast.unparse(call),
                    branch_and_handler_context=contexts.get((call.lineno, call.col_offset), []),
                    callee_id=symbol if resolved else None,
                    callee_file=index["modules"][callee_info[0]]["path"] if callee_info else None,
                    callee_function=callee_info[1] if callee_info else None,
                    resolution_method=method if resolved else "UNRESOLVED",
                    source_sha=index["source_sha"],
                    caller_file_sha256=info["digest"],
                    applicability="STATIC_BINDING_CANDIDATE_ONLY; MANUAL_ROUTE_PROOF_REQUIRED",
                    safety_contract_status="NOT_ESTABLISHED_BY_CALLGRAPH",
                )
            )
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


def constructor_bindings(index):
    """Actual constructor assignments, including explicit injection alternatives."""
    bindings = {}
    writes = {}
    for owner, (module, name, function) in index["definitions"].items():
        for node in body_nodes(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                expression = qualified(target)
                if expression:
                    scope = owner
                    if expression.startswith("self.") and "." in name:
                        scope = owner.rsplit(".", 1)[0]
                    writes.setdefault((scope, expression), []).append(node.lineno)
            value = node.value
            injection = None
            if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
                injection = ast.unparse(value.values[0])
                value = value.values[-1]
            if not isinstance(value, ast.Call):
                continue
            symbol = direct_symbol(index, module, name, value.func)
            if symbol not in index["classes"]:
                continue
            for target in targets:
                expression = qualified(target)
                if not expression:
                    continue
                scope = owner
                if expression.startswith("self.") and "." in name:
                    scope = owner.rsplit(".", 1)[0]
                bindings.setdefault((scope, expression), []).append(
                    dict(
                        constructor=symbol,
                        assignment_line=node.lineno,
                        assignment_file=index["modules"][module]["path"],
                        assignment=ast.unparse(node),
                        condition=f"{injection} is falsy"
                        if injection
                        else "constructor assignment",
                        injection_alternative=injection,
                    )
                )
    return {key: value for key, value in bindings.items() if len(writes[key]) == 1}


def receiver_symbol(index, bindings, module, name, expression):
    """Resolve only source-backed assignments; no inference from receiver names."""
    text = qualified(expression)
    if not text:
        return None, []
    direct = direct_symbol(index, module, name, expression)
    if direct in index["definitions"] or direct in index["classes"]:
        return direct, []
    parts = text.split(".")
    scope = f"{module}.{name}"
    start = 1
    if parts[0] == "self" and "." in name:
        scope = f"{module}.{name.rsplit('.', 1)[0]}"
        start = 2
    evidence = []
    candidate = None
    for end in range(start, len(parts)):
        receiver = ".".join(parts[:end]) if candidate is None else f"self.{parts[end - 1]}"
        entries = bindings.get((scope, receiver), [])
        if len(entries) != 1:
            return None, evidence
        binding = entries[0]
        evidence.append(binding)
        candidate = binding["constructor"]
        scope = candidate
    if candidate:
        return f"{candidate}.{parts[-1]}", evidence
    return None, evidence


def resolved_checkpoint_edges(index, extra_bindings=None):
    """Conditional static graph plus supplied callbacks, never runtime execution."""
    bindings = constructor_bindings(index)
    bindings.update(extra_bindings or {})
    edges = resolve_edges(index)
    locations = {(e["caller_id"], e["callsite_line"], e["callsite_column"]): e for e in edges}
    callbacks = []
    for caller, (module, name, function) in index["definitions"].items():
        for call in calls_in_function(function):
            edge = locations[(caller, call.lineno, call.col_offset)]
            symbol, evidence = receiver_symbol(index, bindings, module, name, call.func)
            if symbol in index["definitions"] and edge["resolution_method"] == "UNRESOLVED":
                callee_module, callee_name, _ = index["definitions"][symbol]
                edge.update(
                    callee_id=symbol,
                    callee_file=index["modules"][callee_module]["path"],
                    callee_function=callee_name,
                    resolution_method="CONSTRUCTOR_RESOLVED",
                    binding_evidence=evidence,
                    applicability="; ".join(b["condition"] for b in evidence),
                )
            supplied = []
            invoker = index["definitions"].get(edge["callee_id"])
            if invoker:
                parameters = invoker[2].args.posonlyargs + invoker[2].args.args
                if parameters and parameters[0].arg in {"self", "cls"}:
                    parameters = parameters[1:]
                called = {
                    n.func.id for n in calls_in_function(invoker[2]) if isinstance(n.func, ast.Name)
                }
                rebound = {
                    n.id
                    for n in body_nodes(invoker[2])
                    if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
                }
                rebound.update(
                    n.name
                    for n in ast.walk(invoker[2])
                    if isinstance(
                        n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler)
                    )
                    and n is not invoker[2]
                    and n.name
                )
                supplied.extend(
                    call.args[position]
                    for position, parameter in enumerate(parameters)
                    if parameter.arg in called
                    and parameter.arg not in rebound
                    and position < len(call.args)
                )
            external = direct_symbol(index, module, name, call.func)
            if external == "threading.Thread":
                supplied.extend(k.value for k in call.keywords if k.arg == "target")
            if isinstance(call.func, ast.Attribute) and call.func.attr == "submit":
                receiver = qualified(call.func.value)
                executors = [
                    item
                    for n in body_nodes(function)
                    if isinstance(n, ast.With)
                    for item in n.items
                    if qualified(item.optional_vars) == receiver
                    and isinstance(item.context_expr, ast.Call)
                    and direct_symbol(index, module, name, item.context_expr.func)
                    == "concurrent.futures.ThreadPoolExecutor"
                ]
                receiver_writes = [
                    n
                    for n in body_nodes(function)
                    if isinstance(n, (ast.Name, ast.Attribute))
                    and isinstance(n.ctx, (ast.Store, ast.Del))
                    and qualified(n) in {receiver, qualified(call.func)}
                ]
                proven_blocks = [
                    n
                    for n in body_nodes(function)
                    if isinstance(n, ast.With)
                    and any(item in executors for item in n.items)
                    and any(child is call for child in body_nodes(n))
                ]
                if (
                    len(executors) == 1
                    and len(receiver_writes) == 1
                    and len(proven_blocks) == 1
                    and call.args
                ):
                    supplied.append(call.args[0])
            for value in supplied:
                destination, proof = receiver_symbol(index, bindings, module, name, value)
                if destination not in index["definitions"]:
                    continue
                callee_module, callee_name, _ = index["definitions"][destination]
                callbacks.append(
                    dict(
                        edge,
                        edge_id=edge["edge_id"] + ":callback:" + ast.unparse(value),
                        callee_id=destination,
                        callee_file=index["modules"][callee_module]["path"],
                        callee_function=callee_name,
                        resolution_method="CALLBACK_RESOLVED",
                        binding_evidence=proof,
                        callback_argument=ast.unparse(value),
                        applicability="SUPPLIED_CALLBACK_ONLY; INVOKER_MUST_BE_SOURCE_REVIEWED",
                    )
                )
    return edges + callbacks, bindings
