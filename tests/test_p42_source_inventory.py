import ast

from scripts.p42_source_inventory import Calls


def test_index_includes_arbitrary_receiver_and_dynamic_call():
    visitor = Calls()
    visitor.visit(ast.parse("def run(x):\n x.save({})\n getattr(x, 'write')()\n"))
    assert visitor.functions == [{"name": "run", "line": 1}]
    assert [r["target"] for r in visitor.calls] == ["x.save", "getattr(x, 'write')", "getattr"]
    assert all(r["semantic_resolution"] == "UNCLASSIFIED_LEXICAL_CALL" for r in visitor.calls)


def test_async_and_nested_scope_not_omitted():
    visitor = Calls()
    visitor.visit(ast.parse("class X:\n async def run(self):\n  self.load()\n"))
    assert visitor.functions[0]["name"] == "X.run"
    assert visitor.calls[0]["function"] == "X.run"
