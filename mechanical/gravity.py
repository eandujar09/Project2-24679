"""Physical gravity vectors in the original CAD/global frame, in m/s².

Mechanical's EarthGravity component fields feed APDL ACEL (inertial
acceleration), whose sign is opposite to physical weight. The Direction enum
already describes physical gravity. Never infer direction from prose or names.
"""
import ast
import math
import re

G = 9.80665
DIRECTIONS = {sign + axis + 'Axis': [(-G if sign == 'Negative' else G) if i == n else 0.0
              for i in range(3)] for n, axis in enumerate('XYZ') for sign in ('Positive', 'Negative')}


def acceleration(value, unit):
    unit = re.sub(r'[\s*^()]', '', str(unit)).replace('²', '2').replace('sec', 's').replace('s-1s-1', 's-2')
    factors = {'ms-2': 1, 'm/s2': 1, 'mms-2': .001, 'mm/s2': .001,
               'cms-2': .01, 'cm/s2': .01, 'ins-2': .0254, 'in/s2': .0254,
               'fts-2': .3048, 'ft/s2': .3048}
    result = float(value) * factors[unit]
    if not math.isfinite(result):
        raise ValueError('Nonfinite gravity component')
    return result


def preview_gravity(code):
    """Read explicit, straight-line gravity definitions without executing code.

    Dynamic/conditional definitions are deliberately unresolved until Mechanical
    reports the actual object. Comments and strings cannot enable gravity.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    variables, loads, handled = {}, [], set()

    def value(node):
        if isinstance(node, ast.Name):
            return variables.get(node.id)
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Quantity':
            args = [value(a) for a in node.args]
            if len(args) == 2:
                return acceleration(*args)
            if len(args) == 1 and isinstance(args[0], str):
                match = re.fullmatch(r'\s*([-+\d.eE]+)\s*\[([^]]+)\]\s*', args[0])
                if match:
                    return acceleration(*match.groups())
            return None
        if isinstance(node, (ast.List, ast.Tuple)):
            return [value(x) for x in node.elts]
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            return None

    def path(node):
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            return [*path(node.value), node.attr]
        return []

    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            expression = statement.value
            if (isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute)
                    and expression.func.attr == 'AddEarthGravity'):
                load = {'id': 'gravity:' + str(statement.lineno), 'vector': None, 'components': {}, 'active': True, 'global': True}
                loads.append(load)
                handled.add(id(expression))
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        variables[target.id] = load
                continue
            try:
                result = value(expression)
            except (ValueError, KeyError, TypeError, OverflowError):
                result = None
            for target in statement.targets:
                names = path(target)
                if len(names) == 1:
                    variables[names[0]] = result
                    continue
                load = variables.get(names[0]) if names else None
                if not isinstance(load, dict) or 'components' not in load:
                    continue
                if names[1:] == ['Direction']:
                    load['vector'] = DIRECTIONS.get(result) if isinstance(result, str) else None
                    load['components'] = {}
                elif names[1:] == ['Suppressed']:
                    load['active'] = result is not True
                    if result is not False and result is not True:
                        load['global'] = False
                elif names[1:] == ['CoordinateSystem']:
                    # Explicit local coordinate transforms need actual Mechanical data.
                    load['global'] = False
                elif len(names) == 4 and names[1] in ('XComponent', 'YComponent', 'ZComponent') and names[2:] == ['Output', 'DiscreteValues']:
                    component = result[0] if isinstance(result, list) and len(result) == 1 else None
                    load['components'][names[1][0]] = component
                    components = [load['components'].get(axis) for axis in 'XYZ']
                    load['vector'] = [-x for x in components] if all(type(x) in (int, float) and math.isfinite(x) for x in components) else None
        elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            names = path(statement.value.func)
            if len(names) == 2 and names[1] == 'Delete' and isinstance(variables.get(names[0]), dict):
                variables[names[0]]['active'] = False
        elif isinstance(statement, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.FunctionDef)):
            # Never show a definite vector after control flow might change it.
            affected = {n.id for n in ast.walk(statement) if isinstance(n, ast.Name)}
            for name in affected:
                if isinstance(variables.get(name), dict):
                    variables[name]['global'] = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'AddEarthGravity' and id(node) not in handled:
            loads.append({'id': 'gravity:' + str(node.lineno), 'vector': None, 'active': True, 'global': False})
    return [{'id': load['id'], 'vector': load['vector'] if load['global'] else None,
             'unit': 'm/s²', 'source': 'code'} for load in loads if load['active']]


def read_gravity(ns):
    """Read real, unsuppressed gravity objects; no solves or model edits."""
    rows = []
    model = ns['Model']
    global_id = model.CoordinateSystems.Children[0].ObjectId
    for analysis in model.Analyses:
        for load in analysis.GetChildren(ns['DataModelObjectCategory'].EarthGravity, True):
            if load.Suppressed:
                continue
            row = {'id': 'gravity:' + str(load.ObjectId), 'vector': None,
                   'unit': 'm/s²', 'source': 'mechanical', 'analysis': str(analysis.Name)}
            try:
                if load.CoordinateSystem.ObjectId != global_id:
                    row['note'] = 'Local gravity coordinates need review.'
                else:
                    components = []
                    for axis in 'XYZ':
                        values = getattr(load, axis + 'Component').Output.DiscreteValues
                        if len(values) != 1:
                            raise ValueError('Gravity components are not constant.')
                        components.append(-acceleration(values[0].Value, values[0].Unit))
                    row['vector'] = components
            except Exception:
                row['note'] = 'Gravity direction could not be read from Mechanical.'
            rows.append(row)
    return rows
