"""Write docs/pipelines.md: every registered pipeline, generated from the registry itself.

    python scripts/pipeline_catalog.py [--json catalog.json]

The document is regenerated, never edited by hand, so it always matches the code.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from image_studio import pipelines  # noqa: E402
from image_studio.integrations import photocraft_intents as lang  # noqa: E402

STAGE_WORDS = {'layer': 'layer housekeeping', 'retouch': 'pixel retouching', 'develop': 'raw development',
               'ai': 'AI layers', 'adjust': 'adjustment layers', 'effect': 'effects', 'cutout': 'cut-outs',
               'geometry': 'geometry', 'graphics': 'text and graphics', 'output': 'output', 'expert': 'last resort',
               'workflow': 'expands into procedures'}


def steps_of(pipeline):
    """The engine commands a procedure sends for a typical request, from a dry build."""
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_pipelines import built

    try:
        (steps, *_), _ = built(pipeline.id)
    except Exception:  # noqa: BLE001 - the catalog lists what it can
        return []
    seen = []
    for step in steps:
        if step['command'] not in seen:
            seen.append(step['command'])
    return seen


def markdown():
    catalog = pipelines.catalog()
    procedures = sum(item['kind'] == 'procedure' for item in catalog)
    lines = [
        '# Pipeline catalog',
        '',
        f'Generated from the registry by `scripts/pipeline_catalog.py`: {len(catalog)} pipelines, '
        f'{len(catalog) - procedures} professional workflows and {procedures} procedures. See '
        '`docs/pipeline-engine.md` for how they are chosen, built and checked.',
        '',
        'A **procedure** builds PhotoCraft commands itself. A **workflow** is a professional job made of '
        'procedures; it expands into them, they are ordered by stage with everything else in the request, and '
        'each one is checked on its own. The planner (any connected model) only chooses the pipeline id and fills '
        'slots from closed menus; every setting below is computed by the pipeline.',
        '',
        'Stages run in this order: ' + ' → '.join(STAGE_WORDS[s] for s in pipelines.STAGES[:-1]) + '.',
        '',
    ]
    for key, title, group in pipelines.menu():
        lines += [f'## {title}', '']
        for pipeline in group:
            kind = 'workflow' if pipeline.workflow else f'procedure · stage: {STAGE_WORDS[pipeline.stage]}'
            lines += [f'### `{pipeline.id}` — {pipeline.title}', '', f'*{kind}*', '', pipeline.summary[:1].upper()
                      + pipeline.summary[1:] + '.', '']
            if pipeline.workflow:
                lines.append('Procedures: ' + ' → '.join(f'`{step}`' for step in pipeline.steps))
            else:
                commands = steps_of(pipeline)
                if commands:
                    lines.append('Engine commands: ' + ', '.join(f'`{c}`' for c in commands))
            if pipeline.options:
                lines.append('Choice menu: ' + ', '.join(pipeline.options))
            if pipeline.measures:
                lines.append('Measures first: ' + ', '.join(pipeline.measures))
            if pipeline.ai:
                lines.append('Needs the AI content model.')
            if pipeline.examples:
                lines.append('Answers: ' + '; '.join(f'“{e}”' for e in pipeline.examples))
            lines.append('')
    return '\n'.join(lines).replace('\n\n\n', '\n\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', help='also write the catalog as JSON to this path')
    args = parser.parse_args()
    target = ROOT / 'docs' / 'pipelines.md'
    target.write_text(markdown(), encoding='utf-8', newline='\n')
    print(f'Wrote {target} ({len(pipelines.REGISTRY)} pipelines, {len(lang.ACTIONS)} in the edit language)')
    if args.json:
        Path(args.json).write_text(json.dumps(pipelines.catalog(), indent=1, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
