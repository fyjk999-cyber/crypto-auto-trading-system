"""Static Git-object inventory only; never imports the producer or opens its state."""
import ast
import hashlib
import json
import subprocess

VERSIONS = ('25505ff15dd6acd623140d70c0a8eb216c59ea48',
            'b1a3f97b213d062ed70375ac7aedbd0d67745a0b')
FIELDS = ('completed dataset forward_bridge_start_ms forward_cursor forward_in_progress '
          'forward_latest last_error last_success_at newest_fetched next_cursor oldest_fetched '
          'retry_count source status symbol timeframe updated_at pause_reason '
          'restored_completed_at '
          'restored_reason').split()


def inspect_text(text):
    tree = ast.parse(text)
    rows = []
    calls = []

    def walk(node, scope='<module>'):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope += '.' + node.name
        if isinstance(node, ast.Constant) and type(node.value) is str and node.value in FIELDS:
            rows.append({'field': node.value, 'line': node.lineno, 'function': scope,
                         'classification': 'LITERAL_REFERENCE_REQUIRES_ALIAS_AND_SEMANTIC_REVIEW'})
        if isinstance(node, ast.Call):
            calls.append({'line': node.lineno, 'function': scope,
                          'callee': ast.unparse(node.func),
                          'dispatch': 'UNRESOLVED_STATIC_CANDIDATE'})
        for child in ast.iter_child_nodes(node):
            walk(child, scope)
    walk(tree)
    return rows, calls


def audit(repo):
    result = {'scope': 'TRACKED_SRC_AND_SCRIPTS_GIT_OBJECTS_ONLY',
              'metadata_exclusion_allowlist': [], 'formal_acceptance': 'BLOCKED', 'versions': {}}
    for version in VERSIONS:
        names = subprocess.check_output(
            ['git', '-C', repo, 'ls-tree', '-r', '--name-only', version], text=True).splitlines()
        files = {}
        for name in names:
            if not name.endswith('.py') or not name.startswith(('src/', 'scripts/')):
                continue
            raw = subprocess.check_output(['git', '-C', repo, 'show', version + ':' + name])
            rows, calls = inspect_text(raw.decode('utf-8'))
            text = raw.decode('utf-8')
            if any(token in text.lower() for token in ('checkpoint', 'lease', 'writer_lock')):
                files[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'fields': rows,
                               'calls': [c for c in calls if any(t in c['callee'].lower() for t in
                                         ('checkpoint', 'atomic', 'replace', 'fsync',
                                          'lease', 'lock'))],
                               'lines': len(text.splitlines())}
        result['versions'][version] = {'files': files, 'field_matrix': {
            field: {'references': [{'file': name, **row} for name, f in files.items()
                                   for row in f['fields'] if row['field'] == field],
                    'verdict': ('ORPHANED_BUT_PROTECTED' if field.startswith('restored_')
                                else 'UNKNOWN_CONTROL_UNTIL_ALL_CONSUMERS_REVIEWED')}
            for field in FIELDS},
            'unknown_dynamic_paths': [
                'Object aliases, callbacks, reflection and imported consumers unresolved.',
                'External/manual/untracked historical tools not proven exhaustive.']}
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    print(json.dumps(audit(parser.parse_args().repo), sort_keys=True, separators=(',', ':')))
