#!/usr/bin/env python3
"""Validate handoff contracts, not an application implementation or clinical behavior.

Run: uv run --no-project --with jsonschema==4.25.1 python scripts/check_contracts.py
No network references are resolved. This script does not rewrite specs or locks.
Every check raises ContractError explicitly, so `python -O` cannot skip it (#301); formats date-time and uri are
checked by spec_utils.format_checker() without extra packages.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
    from referencing import Registry, Resource
except ImportError:
    print('FAIL: install the documented jsonschema==4.25.1 validation dependency.', file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from spec_utils import format_checker, schema_files  # noqa: E402
CONTRACTS = ROOT / 'spec/contracts'
API_PATH = ROOT / 'spec/api/openapi.json'
BASELINE_OPERATIONS = {
    'createSession': ('POST', '/sessions'),
    'deleteSession': ('DELETE', '/sessions/current'),
    'getProfile': ('GET', '/profile'),
    'saveProfile': ('PUT', '/profile'),
    'createCase': ('POST', '/cases'),
    'listCases': ('GET', '/cases'),
    'getCase': ('GET', '/cases/{case_id}'),
    'editCase': ('PATCH', '/cases/{case_id}'),
    'deleteCase': ('DELETE', '/cases/{case_id}'),
    'uploadRecord': ('POST', '/cases/{case_id}/records'),
    'listRecords': ('GET', '/cases/{case_id}/records'),
    'reviewFact': ('PATCH', '/cases/{case_id}/facts/{fact_id}'),
    'nextQuestion': ('POST', '/cases/{case_id}/questions/next'),
    'saveAnswer': ('PUT', '/cases/{case_id}/answers/{question_id}'),
    'confirmReview': ('POST', '/cases/{case_id}/review'),
    'generateGuidance': ('POST', '/cases/{case_id}/guidance'),
    'getGuidance': ('GET', '/cases/{case_id}/guidance'),
    'getCaseSources': ('GET', '/cases/{case_id}/sources'),
    'searchProviders': ('POST', '/cases/{case_id}/provider-search'),
    'getProvider': ('GET', '/cases/{case_id}/providers/{provider_id}'),
    'createExport': ('POST', '/cases/{case_id}/exports'),
    'downloadExport': ('GET', '/exports/{export_id}/download'),
    'getJob': ('GET', '/jobs/{job_id}'),
    'getSettings': ('GET', '/settings'),
    'updateSettings': ('PUT', '/settings'),
    'deleteAllHealthData': ('POST', '/privacy/delete-all'),
    'getRuntime': ('GET', '/presenter/runtime'),
    'getControls': ('GET', '/presenter/controls'),
    'loadScenario': ('POST', '/presenter/scenarios/{scenario_id}/load'),
    'resetDemo': ('POST', '/presenter/reset'),
    'getReadiness': ('GET', '/health/ready'),
    # ADR-017: the W06 telemetry read, the one operation added to the master v2.0 inventory.
    'getTelemetry': ('GET', '/telemetry'),
    # #548: the presenter's debug Logs view on O01.
    'getLogs': ('GET', '/presenter/logs'),
}
HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}


class ContractError(Exception):
    """A failed contract check (not an AssertionError, so it survives python -O)."""


def require(condition, message) -> None:
    if not condition:
        raise ContractError(str(message))


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def pointer(document, fragment):
    if not fragment:
        return document
    if not fragment.startswith('/'):
        raise ContractError(f'Only JSON pointer fragments are allowed: {fragment}')
    current = document
    for token in fragment[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def embedded_copy(value):
    if isinstance(value, dict):
        return {
            key: (
                '#/components/schemas/' + item.removesuffix('.schema.json')
                if key == '$ref' and isinstance(item, str) and item.endswith('.schema.json')
                else embedded_copy(item)
            )
            for key, item in value.items() if key != '$schema'
        }
    if isinstance(value, list):
        return [embedded_copy(item) for item in value]
    return value


def run():
    files = schema_files(ROOT)
    require(files, 'No schemas found')
    schemas = {file.relative_to(CONTRACTS).as_posix().removesuffix('.schema.json'): read_json(file) for file in files}
    registry_doc = read_json(CONTRACTS / 'registry.json')
    registered = {entry['name']: entry['file'] for entry in registry_doc['schemas']}
    require(len(registered) == len(registry_doc['schemas']), 'Duplicate schema registry names')
    require(registered == {name: name + '.schema.json' for name in schemas}, 'Schema registry drift')
    ref_count = 0
    for file in files:
        schema = schemas[file.relative_to(CONTRACTS).as_posix().removesuffix('.schema.json')]
        require(schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema', file)
        Draft202012Validator.check_schema(schema)
        for node in walk(schema):
            if node.get('type') == 'object':
                require(node.get('additionalProperties') is False, f'Open object in {file.name}')
                require(set(node.get('required', [])) <= set(node.get('properties', {})), f'Unknown required field: {file.name}')
            if '$ref' in node:
                target_text, _, fragment = node['$ref'].partition('#')
                require(not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target_text), 'External schema reference rejected')
                target = (file.parent / target_text).resolve() if target_text else file.resolve()
                require(target.is_relative_to(CONTRACTS.resolve()), 'Reference escapes contracts directory')
                require(target.is_file(), f'Missing schema ref {node["$ref"]}')
                pointer(read_json(target), fragment)
                ref_count += 1
    api = read_json(API_PATH)
    require(api['openapi'] == '3.1.0', 'OpenAPI version drift')
    require(api['servers'][0]['url'] == '/api/v1', 'API prefix drift')
    require(set(api['components']['schemas']) == set(schemas), 'Embedded schema inventory drift')
    for name, schema in schemas.items():
        embedded = api['components']['schemas'][name]
        require(embedded == embedded_copy(schema), f'Embedded schema differs: {name}')
        Draft202012Validator.check_schema(embedded)
    for node in walk(api):
        if '$ref' in node:
            reference = node['$ref']
            require(reference.startswith('#/'), f'OpenAPI ref is not self-contained: {reference}')
            pointer(api, reference[1:])
    actual = {}
    for path, path_item in api['paths'].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_id = operation['operationId']
            require(operation_id not in actual, f'Duplicate operationId: {operation_id}')
            actual[operation_id] = (method.upper(), path)
            params = [*path_item.get('parameters', []), *operation.get('parameters', [])]
            pairs = [(p['in'], p['name']) for p in params]
            require(len(pairs) == len(set(pairs)), f'Duplicate parameters: {operation_id}')
            declared = {p['name'] for p in params if p['in'] == 'path'}
            require(declared == set(re.findall(r'{([^}]+)}', path)), f'Path params differ: {operation_id}')
            require(all(p.get('required') is True for p in params if p['in'] == 'path'), operation_id)
            require(re.fullmatch('M(0[1-9]|1[0-2])', operation['x-owner-module']), operation_id)
            require(operation['x-requirement-ids'], operation_id)
            require(all(re.fullmatch('R(0[1-9]|[1-3][0-9]|40)', r) for r in operation['x-requirement-ids']), operation_id)
            if method not in {'get', 'head', 'options'}:
                require(('header', 'Origin') in pairs, f'Origin missing: {operation_id}')
                if operation_id != 'createSession':
                    require(('header', 'X-CSRF-Token') in pairs, f'CSRF missing: {operation_id}')
            if operation_id not in {'createSession', 'getReadiness', 'getTelemetry'}:
                require(operation['security'] == [{'sessionCookie': []}], f'Session security missing: {operation_id}')
    require(actual == BASELINE_OPERATIONS, 'Operation IDs/methods/paths differ from master v2.0 inventory')
    operations_doc = read_json(ROOT / 'spec/api/operations.json')
    require(operations_doc['operation_count'] == len(actual), 'Operation count drift')
    listed = {o['operation_id']: (o['method'], o['path'].removeprefix('/api/v1')) for o in operations_doc['operations']}
    require(len(listed) == len(operations_doc['operations']), 'Duplicate operation registry entry')
    require(listed == actual, 'Operation registry drift')
    # Canonical association includes direct and supporting requirements. Ownership
    # is separate: a cross-cutting requirement does not create another API owner.
    requirements_doc = read_json(ROOT / 'spec/requirements.json')
    requirements = requirements_doc['requirements']
    requirement_ids = [requirement['id'] for requirement in requirements]
    require(len(requirement_ids) == len(set(requirement_ids)), 'Duplicate requirement ID')
    require(set(requirement_ids) == {f'R{i:02d}' for i in range(1, 41)}, 'Requirement inventory drift')
    inverse = {operation_id: set() for operation_id in actual}
    for requirement in requirements:
        associated = requirement['api_operation_ids']
        require(len(associated) == len(set(associated)), f'Duplicate operation association: {requirement["id"]}')
        for operation_id in associated:
            require(operation_id in inverse, f'Unknown requirement operation: {operation_id}')
            inverse[operation_id].add(requirement['id'])
    by_id = {operation['operation_id']: operation for operation in operations_doc['operations']}
    for operation_id, (method, path) in actual.items():
        registry_ids = by_id[operation_id]['requirements']
        api_ids = api['paths'][path][method.lower()]['x-requirement-ids']
        require(len(registry_ids) == len(set(registry_ids)), f'Duplicate operation requirements: {operation_id}')
        require(len(api_ids) == len(set(api_ids)), f'Duplicate OpenAPI requirements: {operation_id}')
        require(set(registry_ids) == inverse[operation_id], f'Requirement association drift in operations.json: {operation_id}')
        require(set(api_ids) == inverse[operation_id], f'Requirement association drift in OpenAPI: {operation_id}')
        require(by_id[operation_id]['owner'] == api['paths'][path][method.lower()]['x-owner-module'], f'Endpoint owner drift: {operation_id}')
    registry = Registry().with_resources([
        (file.as_uri(), Resource.from_contents(read_json(file))) for file in files
    ])
    cases_doc = read_json(ROOT / 'tests/handoff/contract-cases.json')
    case_ids = set()
    positives = negatives = 0
    for case in cases_doc['cases']:
        require(case['id'] not in case_ids, 'Duplicate test case ID')
        case_ids.add(case['id'])
        require(case['schema'] in schemas, case['schema'])
        validator = Draft202012Validator(
            {'$ref': (CONTRACTS / (case['schema'] + '.schema.json')).as_uri()},
            registry=registry, format_checker=format_checker(),
        )
        try:
            validator.validate(case['payload'])
            valid = True
        except ValidationError:
            valid = False
        require(valid == case['valid'], f'Unexpected validation result: {case["id"]}')
        positives += valid
        negatives += not valid
    print(json.dumps({
        'status': 'passed',
        'scope': 'static handoff contract checks only; not application or clinical acceptance',
        'standalone_schemas': len(files),
        'standalone_refs_resolved': ref_count,
        'embedded_schema_parity': 'passed',
        'baseline_operations': len(actual),
        'path_parameters': 'passed',
        'bidirectional_requirement_associations': 'passed',
        'positive_contract_cases': positives,
        'negative_contract_cases': negatives,
    }, indent=2))


if __name__ == '__main__':
    try:
        run()
    except (ContractError, KeyError, ValueError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        raise SystemExit(1)
