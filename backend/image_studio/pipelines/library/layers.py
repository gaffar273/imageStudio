"""Layer housekeeping on layers that already exist. Only accepted when the request talks about
layers; otherwise the clause is read as something to keep unchanged."""

from image_studio.pipelines.core import procedure

SUMMARIES = {
    'layer_opacity': 'change an existing layer’s opacity (object = layer name, value = %)',
    'layer_visibility': 'hide (decrease) or show (increase) an existing layer (object = layer name)',
    'layer_delete': 'delete an existing layer (object = layer name)',
    'layer_rename': 'rename an existing layer (object = old name, text = new name)',
    'layer_blend': 'set an existing layer’s blend mode (object = layer name, choice = mode)',
}


def layer_edit(b, index, edit):
    layer = b.layer_named(edit['object'] or edit['choice'])
    if layer is None:
        b.blocking.append(f'Which layer does “{edit["quote"]}” mean? Use its name from the Layers panel.')
        return
    action, lid, name = edit['action'], layer['id'], layer['name']
    if action == 'layer_opacity':
        if edit['value'] is None:
            b.blocking.append(f'What opacity should “{name}” have? Give a percentage.')
            return
        b.add(index, 'layer.setProps', {'layer': lid, 'opacity': max(0, min(100, edit['value'])) / 100},
              f'Set “{name}” to {edit["value"]:g}% opacity')
    elif action == 'layer_visibility':
        visible = edit['direction'] == 'increase' or 'show' in edit['quote'].lower()
        b.add(index, 'layer.setProps', {'layer': lid, 'visible': visible}, f'{"Show" if visible else "Hide"} “{name}”')
    elif action == 'layer_delete':
        b.add(index, 'layer.delete', {'layer': lid}, f'Delete “{name}”')
    elif action == 'layer_rename':
        if not edit['text']:
            b.blocking.append('What should the new layer name be?')
            return
        b.add(index, 'layer.renameLayer', {'layer': lid, 'name': edit['text'][:80]},
              f'Rename “{name}” to “{edit["text"][:40]}”')
    elif action == 'layer_blend':
        mode = (edit['choice'] or '').strip().title().replace(' ', '')
        if not mode:
            b.blocking.append('Which blend mode, for example Multiply, Screen, Overlay or Soft Light?')
            return
        mode = {'Softlight': 'Soft Light', 'Hardlight': 'Hard Light', 'Lineardodge': 'Linear Dodge'}.get(mode, mode)
        b.add(index, 'layer.setProps', {'layer': lid, 'blend': mode}, f'Blend “{name}” with {mode}')


for _action, _summary in SUMMARIES.items():
    procedure(_action, _action.replace('_', ' ').capitalize(), 'layers', 'layer', _summary)(layer_edit)
