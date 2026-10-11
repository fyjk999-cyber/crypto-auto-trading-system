from scripts.p42r_callgraph import index_sources, path_crosscheck, resolve_edges


def graph():
    return resolve_edges(index_sources({
        "src/example/store.py": b"class Store:\n def __init__(self): pass\n def save(self): pass\n",
        "src/example/entry.py": b"from example.store import Store as S\n"
        b"def sink(): pass\ndef wrapper(): sink()\ndef entry(): wrapper(); S()\n"
        b"def dynamic(store, callback): store.save(); callback()\n"
        b"class Worker:\n def write(self): self.run()\n def run(self): sink()\n",
    }, "fixture-v1"))


def test_direct_calls_import_alias_and_constructor():
    edges = graph()
    constructor = next(e for e in edges if e["expression"] == "S()")
    assert constructor["callee_id"] == "example.store.Store.__init__"
    assert constructor["resolution_method"] == "CONSTRUCTOR_RESOLVED"
    assert path_crosscheck(edges, "example.entry.entry", "example.entry.sink") == {
        "forward": True, "reverse": True, "safety": "NOT_PROVEN",
    }


def test_self_method_known_but_not_authorized_by_name():
    edge = next(e for e in graph() if e["expression"] == "self.run()")
    assert edge["callee_id"] == "example.entry.Worker.run"
    assert edge["safety_contract_status"] == "NOT_ESTABLISHED_BY_CALLGRAPH"


def test_injection_and_callback_unknown_cannot_make_full_path():
    edges = graph()
    dynamic = [e for e in edges if e["caller_function"] == "dynamic"]
    assert len(dynamic) == 2
    assert all(e["resolution_method"] == "UNRESOLVED" for e in dynamic)
    result = path_crosscheck(edges, "example.entry.dynamic", "example.store.Store.save")
    assert not result["forward"]


def test_nested_calls_not_assigned_to_outer_scope():
    edges = resolve_edges(index_sources({"src/n.py": b"def sink(): pass\n"
        b"def outer():\n def inner(): sink()\n inner()\n"}, "v"))
    sink_edge = next(e for e in edges if e["expression"] == "sink()")
    assert sink_edge["caller_function"] == "outer.inner"


def test_different_versions_keep_file_line_and_identity_separate():
    a = resolve_edges(index_sources({"src/a.py": b"def sink(): pass\ndef run(): sink()\n"}, "a"))
    b = resolve_edges(index_sources({"src/a.py": b"\ndef sink(): pass\ndef run(): sink()\n"}, "b"))
    assert a[0]["edge_id"] != b[0]["edge_id"]
    assert a[0]["callsite_line"] == 2 and b[0]["callsite_line"] == 3
    assert a[0]["caller_file_sha256"] != b[0]["caller_file_sha256"]


def test_shadowed_import_is_not_resolved():
    sources = {
        "src/a.py": b"def sink(): pass\n",
        "src/b.py": b"from a import sink\ndef run(sink): sink()\n",
    }
    edge = resolve_edges(index_sources(sources, "v"))[0]
    assert edge["resolution_method"] == "UNRESOLVED"
