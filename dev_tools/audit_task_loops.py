"""Build a reproducible static loop inventory; findings are candidates, not proof of a hang."""
import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path


def name(call):
    return call.func.attr if isinstance(call.func, ast.Attribute) else (
        call.func.id if isinstance(call.func, ast.Name) else '?')


def inventory(root: Path) -> dict:
    report = {
        'root': str(root),
        'task_scripts': [],
        'loops': [],
        'success_false_calls': [],
        'parse_errors': [],
    }
    paths = list((root / 'tasks').rglob('*.py')) + list((root / 'module').rglob('*.py'))
    if (root / 'script.py').exists():
        paths.append(root / 'script.py')
    for path in sorted(paths):
        if '__pycache__' in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding='utf-8-sig')
            tree = ast.parse(source)
        except Exception as error:
            report['parse_errors'].append({'path': relative, 'error': str(error)})
            continue
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        if path.name == 'script_task.py':
            report['task_scripts'].append(relative)

        def scope(node):
            parts = []
            parent = parents.get(node)
            while parent is not None:
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    parts.append(parent.name)
                parent = parents.get(parent)
            return '.'.join(reversed(parts))

        for node in ast.walk(tree):
            if isinstance(node, ast.While):
                calls = sorted({name(call) for call in ast.walk(node) if isinstance(call, ast.Call)})
                segment = ast.get_source_segment(source, node) or ''
                guards = []
                test = ast.unparse(node.test)
                if any(marker in test for marker in ('monotonic(', 'reached(', 'time(', 'deadline')):
                    guards.append('loop_condition_time_candidate')
                if '_tick_timeout' in calls or '_check_navigation_budget' in calls:
                    guards.append('configured_battle_or_nav_budget')
                for condition in (child for child in ast.walk(node) if isinstance(child, ast.If)):
                    # Check that a terminal belongs to this loop, rather than a nested loop.
                    terminal = False
                    for child in ast.walk(condition):
                        if isinstance(child, (ast.Return, ast.Raise)):
                            terminal = True
                        if isinstance(child, ast.Break):
                            parent = parents.get(child)
                            while parent is not None and not isinstance(parent, (ast.While, ast.For)):
                                parent = parents.get(parent)
                            terminal |= parent is node
                    condition_test = ast.unparse(condition.test)
                    if terminal and any(marker in condition_test for marker in (
                            '.reached(', 'monotonic(', 'deadline', 'limit_time', 'timeout')):
                        guards.append('conditional_time_candidate')
                    if terminal and any(marker in condition_test for marker in (
                            'count', 'attempt', 'retry', 'max_swipe', 'limit_num', 'swipes')):
                        guards.append('conditional_count_candidate')
                report['loops'].append({
                    'path': relative,
                    'line': node.lineno,
                    'end_line': node.end_lineno,
                    'scope': scope(node),
                    'test': test,
                    'calls': calls,
                    'guard_candidates': sorted(set(guards)),
                    'captures': any(call in calls for call in ('screenshot', 'maybe_screenshot')),
                    'input_calls': [call for call in calls if call in (
                        'click', 'appear_then_click', 'appear_then_click_multi_scale',
                        'ocr_appear_click', 'swipe', 'long_click',
                        'ui_reward_appear_click', 'click_confirm_once',
                        'ui_click', 'ui_clicks', 'ui_click_until_disappear',
                        'ui_click_until_smt_disappear', '_ui_action_once')],
                    'battle_delegation': any('battle' in call for call in calls),
                    'timer_resets': 'reset' in calls,
                    'source': segment,
                })
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('set_next_run', 'next_run')
                    and any(keyword.arg == 'success' and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is False for keyword in node.keywords)):
                lines = source.splitlines()
                report['success_false_calls'].append({
                    'path': relative,
                    'line': node.lineno,
                    'scope': scope(node),
                    'call': ast.unparse(node),
                    'context': '\n'.join(lines[max(0, node.lineno - 5):node.end_lineno + 3]),
                })
    return report


def table(report: dict) -> str:
    grouped = defaultdict(list)
    for loop in report['loops']:
        if loop['path'].startswith('tasks/'):
            grouped[loop['path'].split('/')[1]].append(loop)
    lines = [
        '| Task | while 数 | 无显式终止候选 | 候选位置 |',
        '|---|---:|---:|---|',
    ]
    for path in report['task_scripts']:
        task = path.split('/')[1]
        loops = grouped[task]
        candidates = [loop for loop in loops if not loop['guard_candidates']]
        locations = ', '.join(f"`{loop['scope'].split('.')[-1]}:{loop['line']}`" for loop in candidates)
        lines.append(f'| {task} | {len(loops)} | {len(candidates)} | {locations or "—"} |')
    return '\n'.join(lines) + '\n'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, help='Repository root to scan')
    parser.add_argument('output', nargs='?', type=Path, default=None,
                        help='Optional JSON output path (also writes matching .md table)')
    parser.add_argument('--md-only', type=Path, default=None,
                        help='Optional Markdown table output path without writing large JSON')
    parser.add_argument('--check', action='store_true',
                        help='Fail with non-zero exit code if AST parse errors or shared BaseTask unbounded loops exist')
    args = parser.parse_args(argv)
    result = inventory(args.root)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        args.output.with_suffix('.md').write_text(table(result), encoding='utf-8')
    if args.md_only is not None:
        args.md_only.parent.mkdir(parents=True, exist_ok=True)
        args.md_only.write_text(table(result), encoding='utf-8')
    task_loops = sum(loop['path'].startswith('tasks/') for loop in result['loops'])
    base_task_unbounded = [
        loop for loop in result['loops']
        if loop['path'] == 'tasks/base_task.py' and not loop['guard_candidates']
    ]
    print(f"{len(result['task_scripts'])} task scripts; {task_loops} task while loops; "
          f"{len(result['loops']) - task_loops} shared/scheduler while loops; "
          f"{len(result['success_false_calls'])} success=False calls; "
          f"{len(result['parse_errors'])} parse errors")
    if args.check and (result['parse_errors'] or base_task_unbounded):
        if result['parse_errors']:
            print(f"ERROR: {len(result['parse_errors'])} AST parse errors detected")
        if base_task_unbounded:
            print(f"ERROR: unbounded while loops in tasks/base_task.py: "
                  f"{[(l['scope'], l['line']) for l in base_task_unbounded]}")
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
