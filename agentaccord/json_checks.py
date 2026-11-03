"""Strict JSON syntax and duplicate-key checks, without executing configuration."""
import json


def analyze(source, path, rules):
    duplicates = []
    def pairs(items):
        seen = set()
        for key, _ in items:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(items)
    def invalid_constant(value):
        raise ValueError('Non-standard JSON constant: ' + value)
    json.loads(source, object_pairs_hook=pairs, parse_constant=invalid_constant)
    rule = 'json.no-duplicate-keys'
    if rule not in rules:
        return []
    # The decoder identifies keys but not their positions. Use a document location
    # rather than inventing a line number for nested or escaped key spellings.
    return [dict(rule=rule, severity=rules[rule], path=path, line=1, column=1,
                 kind='code', confidence='syntax', evidence=key[:200],
                 message='Duplicate JSON object key: ' + repr(key[:200]) + ' (document-level location)',
                 remediation='Keep one value for this key in its object. Location is the document start.')
            for key in duplicates]
