"""
Merge all scene JSON fragments into a new opening_map.json
Each scene normalized to standard schema:
  blurb, scene_id, available_exits, chapters[ch][present + dialogue_flow]
dialogue_flow beats: speaker/text/stage/beat_type/improv/condition/pause_after/scene_end/introduces
"""
import json, sys, re

sys.stdout.reconfigure(encoding='utf-8')

def is_cjk(ch):
    return ord(ch) > 0x3000

def clean_beat(beat):
    """Strip extra fields, normalize beat to standard schema."""
    b = {}
    for k in ('speaker', 'text', 'stage', 'beat_type', 'improv',
              'condition', 'pause_after', 'scene_end', 'introduces'):
        if k in beat:
            b[k] = beat[k]
    sp = b.get('speaker', '')
    # Normalize speakers
    if sp in ('narrative', '主持人'): b['speaker'] = '导演'
    elif sp in ('柳絮', 'liuxu', '主角/女声'): b['speaker'] = 'C.player.WMAIN'
    elif sp in ('(场景)', '场景', 'narrative'): b['speaker'] = '导演'
    elif sp in ('秋人', '岸本', '川口秋人'): b['speaker'] = 'C.akito.WMAIN'
    elif sp in ('修哉', '折原修哉'): b['speaker'] = 'C.xiuzai.WMAIN'
    elif sp in ('卡卡西', '坂本晴明', '银发青'): b['speaker'] = 'C.kakashi.WMAIN'
    elif sp in ('真纪', '张尘', '魏初', '斑驳', '雨璇'):
        cons_map = {'真纪': 'C.maki.WMAIN', '张尘': 'C.zhangchen.WMAIN',
                    '魏初': 'C.weichu.WMAIN', '斑驳': 'C.banbo.WMAIN', '雨璇': 'C.yuxuan.WMAIN'}
        if sp in cons_map: b['speaker'] = cons_map[sp]
    # Normalize beat_type
    bt = b.get('beat_type', '')
    norm_bt = {
        'dialogue': 'normal', 'action': 'normal', 'inner': 'normal',
        'canon': 'normal', 'scene_exit': 'normal', 'scene_transition': 'normal',
        'canon_sequence': 'normal', 'narrator_action': 'normal',
        'inner_thought': 'normal', 'canon_transition': 'normal',
        'canon_locked': 'normal', 'soft_constraint': 'normal',
        'narrative_stage': 'normal', 'player_beat': 'player_choice',
        'player_choice': 'player_choice', 'canon_dark_clock': 'normal',
    }.get(bt, bt)
    b['beat_type'] = norm_bt if norm_bt else 'normal'
    # improv defaults
    if 'improv' not in b or b['improv'] is None:
        b['improv'] = 'anchored'
    # Remove player_options / choices / extra beat fields
    for extra in ('player_options', 'choices', 'beat', 'beat_id', 'lock_id',
                  'canon_lock', 'canon_ref', 'canon_note', 'original_text',
                  'option_id', 'effect', 'next_scene', 'canon_event',
                  'trigger', 'narrative', 'delta_note', 'delta', 'delta_effect'):
        b.pop(extra, None)
    return b

def clean_chapter(ch):
    """Normalize chapter, strip encounters/extra keys."""
    out = {'present': ch.get('present', []), 'dialogue_flow': []}
    for beat in ch.get('dialogue_flow', []):
        if isinstance(beat, dict):
            cleaned = clean_beat(beat)
            if cleaned.get('speaker') and cleaned.get('text'):
                out['dialogue_flow'].append(cleaned)
    out.pop('encounters', None)
    return out

def clean_scene(name, scene):
    """Normalize a full scene."""
    s = {
        'blurb': scene.get('blurb', ''),
        'scene_id': scene.get('scene_id', ''),
        'available_exits': scene.get('available_exits', []),
        'chapters': {}
    }
    for ch_key, ch_data in scene.get('chapters', {}).items():
        if isinstance(ch_data, dict):
            s['chapters'][ch_key] = clean_chapter(ch_data)
    return name, s

# ---- Load fragments ----
fragments = {}

# N6B + NB from the fixed JSON file
with open('runtime/opening_map_N6_NB.json', encoding='utf-8') as f:
    nb_data = json.load(f)
for name, scene in nb_data.items():
    key, s = clean_scene(name, scene)
    fragments[key] = s
    print(f"Loaded N6B/NB: {key}")

print(f"Total fragments loaded: {len(fragments)}")
print("Done - next step is to build remaining fragments from agent outputs")