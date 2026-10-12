from scripts.p42r_callgraph import (
    index_sources,
    path_crosscheck,
    resolve_edges,
    resolved_checkpoint_edges,
)


def graph():
    return resolve_edges(
        index_sources(
            {
                "src/example/store.py": b"class Store:\n"
                b" def __init__(self): pass\n def save(self): pass\n",
                "src/example/entry.py": b"from example.store import Store as S\n"
                b"def sink(): pass\ndef wrapper(): sink()\ndef entry(): wrapper(); S()\n"
                b"def dynamic(store, callback): store.save(); callback()\n"
                b"class Worker:\n def write(self): self.run()\n def run(self): sink()\n",
            },
            "fixture-v1",
        )
    )


def test_direct_calls_import_alias_and_constructor():
    edges = graph()
    constructor = next(e for e in edges if e["expression"] == "S()")
    assert constructor["callee_id"] == "example.store.Store.__init__"
    assert constructor["resolution_method"] == "CONSTRUCTOR_RESOLVED"
    assert path_crosscheck(edges, "example.entry.entry", "example.entry.sink") == {
        "forward": True,
        "reverse": True,
        "safety": "NOT_PROVEN",
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
    edges = resolve_edges(
        index_sources(
            {"src/n.py": b"def sink(): pass\ndef outer():\n def inner(): sink()\n inner()\n"}, "v"
        )
    )
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


def receiver_fixture(reassign=False):
    extra = "self.cp = replacement" if reassign else "pass"
    return index_sources(
        {
            "src/demo/store.py": b"class Store:\n"
            b" def __init__(self): pass\n def save(self): pass\n",
            "src/demo/engine.py": (
                "from demo.store import Store as S\n"
                "class Engine:\n"
                " def __init__(self, injected=None): self.cp = injected or S()\n"
                " def timing(self, callback): callback()\n"
                " def run(self): self.cp.save(); self._timed_ckpt(self.cp.save)\n"
                " def _timed_ckpt(self, func): func()\n"
                f" def change(self, replacement): {extra}\n"
                "def entry():\n from demo.engine import Engine as E\n e = E()\n e.run()\n"
            ).encode(),
        },
        "receiver-fixture",
    )


def test_constructor_injection_preserves_condition_not_safety():
    edges, bindings = resolved_checkpoint_edges(receiver_fixture())
    edge = next(e for e in edges if e["expression"] == "self.cp.save()")
    assert edge["callee_id"] == "demo.store.Store.save"
    assert edge["applicability"] == "injected is falsy"
    assert edge["safety_contract_status"] == "NOT_ESTABLISHED_BY_CALLGRAPH"
    assert bindings[("demo.engine.Engine", "self.cp")][0]["injection_alternative"] == "injected"


def test_local_import_alias_and_local_constructor():
    edges, _ = resolved_checkpoint_edges(receiver_fixture())
    edge = next(e for e in edges if e["expression"] == "e.run()")
    assert edge["callee_id"] == "demo.engine.Engine.run"


def test_timing_wrapper_supplied_callback_path():
    edges, _ = resolved_checkpoint_edges(receiver_fixture())
    callback = next(e for e in edges if e.get("callback_argument") == "self.cp.save")
    assert callback["resolution_method"] == "CALLBACK_RESOLVED"
    assert callback["callee_id"] == "demo.store.Store.save"
    assert "INVOKER_MUST_BE_SOURCE_REVIEWED" in callback["applicability"]


def test_receiver_reassignment_is_unresolved_not_fake_safe():
    edges, bindings = resolved_checkpoint_edges(receiver_fixture(reassign=True))
    edge = next(e for e in edges if e["expression"] == "self.cp.save()")
    assert edge["resolution_method"] == "UNRESOLVED"
    assert ("demo.engine.Engine", "self.cp") not in bindings


def test_module_rebinding_and_deletion_do_not_resolve_old_import():
    for rewrite in ("sink = lambda: None", "del sink"):
        edges = resolve_edges(
            index_sources(
                {
                    "src/a.py": b"def sink(): pass\n",
                    "src/b.py": (
                        "from a import sink\n" + rewrite + "\ndef run(): sink()\n"
                    ).encode(),
                },
                "v",
            )
        )
        assert edges[-1]["resolution_method"] == "UNRESOLVED"


def test_noop_submit_cannot_manufacture_callback_reachability():
    index = index_sources(
        {
            "src/demo.py": b"def sink(): pass\n"
            b"class Noop:\n def __init__(self): pass\n def submit(self, f): pass\n"
            b"def entry():\n n = Noop()\n n.submit(sink)\n",
        },
        "v",
    )
    edges, _ = resolved_checkpoint_edges(index)
    assert not any(e.get("callback_argument") for e in edges)
    assert not path_crosscheck(edges, "demo.entry", "demo.sink")["forward"]


def test_branch_and_exception_context_is_recorded():
    edges = resolve_edges(
        index_sources(
            {
                "src/a.py": b"def sink(): pass\n"
                b"def run(flag):\n"
                b" if flag:\n  sink()\n else:\n  sink()\n"
                b" try:\n  sink()\n except OSError:\n  sink()\n",
            },
            "v",
        )
    )
    contexts = [e["branch_and_handler_context"] for e in edges]
    assert contexts[0] == [{"kind": "IF", "test": "flag"}]
    assert contexts[1] == [{"kind": "ELSE", "test": "flag"}]
    assert contexts[-1] == [{"kind": "EXCEPT", "exception": "OSError"}]


def test_config_selected_store_remains_unknown():
    edges, _ = resolved_checkpoint_edges(index_sources({
        "src/a.py": b"def build(config):\n store = config['factory']()\n store.save()\n",
    }, "v"))
    save = next(e for e in edges if e["expression"] == "store.save()")
    assert save["resolution_method"] == "UNRESOLVED"
    assert save["safety_contract_status"] == "NOT_ESTABLISHED_BY_CALLGRAPH"
