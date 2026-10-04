import os, re, shutil, difflib
src = r'E:\Documents\VS\CIVOLINK\CIVOLINK_QS_ESTIMATING_ENGINE'
tmp = os.path.join(os.environ['TEMP'], 'opencode')
after_dir = os.path.join(tmp, 'after_mix_design')
before_dir = os.path.join(tmp, 'before_mix_design')
if os.path.exists(before_dir): shutil.rmtree(before_dir)
shutil.copytree(after_dir, before_dir, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'dist', '.pytest_cache'))

# 1. schemas.py
p = os.path.join(before_dir, 'qs_engine/master_data/schemas.py')
s = open(p, encoding='utf-8').read()
# Remove MIX_DESIGNS from DOMAINS tuple
s = re.sub(r'\n    MIX_DESIGNS,\n    MASONRY_UNITS,', '\n    MASONRY_UNITS,', s)
s = s.replace('CONCRETE_CLASSES = "concrete_classes"\nMIX_DESIGNS = "mix_designs"\nMASONRY_UNITS = "masonry_units"',
              'CONCRETE_CLASSES = "concrete_classes"\nMASONRY_UNITS = "masonry_units"')
s = re.sub(r'\n    MIX_DESIGNS: \("designation",\s*"bs_8500_designation",\s*"min_cement_content_kg_per_m3",\s*"max_wc_ratio",\s*"fine_agg_ratio",\s*"coarse_agg_ratio",\s*"target_density",\s*"cement_code",\s*"fine_agg_code",\s*"coarse_agg_code",\s*"default_wastage_pct"\),\n    MASONRY_UNITS',
           '\n    MASONRY_UNITS', s, flags=re.DOTALL)
s = re.sub(r'\n    MIX_DESIGNS: \("min_cement_content_kg_per_m3",\s*"max_wc_ratio",\s*"fine_agg_ratio",\s*"coarse_agg_ratio",\s*"target_density",\s*"default_wastage_pct"\),\n    MASONRY_UNITS',
           '\n    MASONRY_UNITS', s, flags=re.DOTALL)
open(p, 'w', encoding='utf-8').write(s)
print('schemas MIX_DESIGNS remaining:', 'MIX_DESIGNS' in open(p, encoding='utf-8').read())

# 2. session.py - remove last_mix_design attribute
p = os.path.join(before_dir, 'qs_engine/ui/session.py')
s = open(p, encoding='utf-8').read()
lines = s.split('\n')
out = []
skip = False
for ln in lines:
    if 'last_mix_design' in ln and 'self.last_mix_design' in ln:
        skip = True
        continue
    if skip and (ln.startswith('        ') or ln.startswith('\t')):
        continue
    if skip:
        skip = False
    out.append(ln)
open(p, 'w', encoding='utf-8').write('\n'.join(out))
print('sess last_mix_design remaining:', 'last_mix_design' in open(p, encoding='utf-8').read())

# 3. views.py - remove mix_design additions
p = os.path.join(before_dir, 'qs_engine/ui/views.py')
s = open(p, encoding='utf-8').read()

# PANEL_SPECS mix_design entry
idx = s.find('"mix_design": ("Mix Design", "mix_design_controller"')
if idx >= 0:
    end = s.find(']),', idx)
    if end >= 0:
        s = s[:idx] + s[end+3:]

# PANEL_INSTRUCTIONS mix_design
idx = s.find('"mix_design": "\\u2022 Pick a Eurocode')
if idx >= 0:
    end = s.find('",\n}', idx)
    if end >= 0:
        s = s[:idx] + s[end+len('",\n}'):]

# FIELD_CUES mix_design
s = s.replace('     ("mix_design", "designation"): "e.g., C20/25 (ST4 / PAV 1)",\n', '')
s = s.replace('     ("mix_design", "net_volume"): "e.g., 10",\n', '')

# NAV_GROUPS CONSTITUENTS
idx = s.find('("CONSTITUENTS", (')
if idx >= 0:
    end = s.find(')),', idx)
    if end >= 0:
        s = s[:idx] + s[end+3:]

# NAV_ITEM_ICONS mix_design
idx = s.find('"mix_design": "\\u2022"')
if idx >= 0:
    end = s.find(',\n }', idx)
    if end >= 0:
        s = s[:idx] + s[end+len(',\n }'):]

# NAV_ITEM_ICONS mix_design (handles any icon char)
idx = s.find('"mix_design": "')
if idx >= 0:
    end = s.find(',\n }', idx)
    if end >= 0:
        s = s[:idx] + s[end+len(',\n }'):]

# PAGES mix_design
s = s.replace('     "mix_design": build_mix_design_page,\n', '')

# build_mix_design_page function
idx = s.find('\ndef build_mix_design_page(body, app):')
if idx >= 0:
    end = s.find('\n\n#: Reconciliation review grid columns.', idx)
    if end >= 0:
        s = s[:idx] + s[end:]

# default_bindings mix_design
s = s.replace('         "mix_design": controllers.mix_design_controller,\n     }', '     }')
open(p, 'w', encoding='utf-8').write(s)
print('views build_mix_design remaining:', 'build_mix_design_page' in open(p, encoding='utf-8').read())
print('views mix_design remaining:', '"mix_design"' in open(p, encoding='utf-8').read())

# 4. spec
p = os.path.join(before_dir, 'CIVOLINK-QS.spec')
s = open(p, encoding='utf-8').read()
s = s.replace(', \'qs_engine.mixes\', \'qs_engine.mixes.calculator\']', ']')
open(p, 'w', encoding='utf-8').write(s)

# 4b. Revert controllers.py - remove mix_design_controller function
p = os.path.join(before_dir, 'qs_engine/ui/controllers.py')
s = open(p, encoding='utf-8').read()
idx = s.find('\n\ndef mix_design_controller(')
if idx >= 0:
    s = s[:idx] + '\n'
open(p, 'w', encoding='utf-8').write(s)

# 5. Remove test_mix_design_engine.py, mix_designs.json, and mixes/ from before
p = os.path.join(before_dir, 'tests/test_mix_design_engine.py')
if os.path.exists(p): os.remove(p)
p = os.path.join(before_dir, 'qs_engine/master_data/tables/mix_designs.json')
if os.path.exists(p): os.remove(p)
mixes_dir = os.path.join(before_dir, 'qs_engine/mixes')
if os.path.exists(mixes_dir): shutil.rmtree(mixes_dir)

# 6. Revert master_data test
p = os.path.join(before_dir, 'tests/test_master_data.py')
s = open(p, encoding='utf-8').read()
s = s.replace('    # Phase 9 adds the rate_templates domain; Phase 6 adds mix_designs: eleven in total.\n    assert set(DOMAINS) == {\n        "materials", "concrete_classes", "masonry_units", "rebar_bars",\n        "coverages", "labour", "plant", "trucks", "soils",\n        "rate_templates", "mix_designs",\n    }',
              '    # Phase 9 adds the rate_templates domain: ten in total.\n    assert set(DOMAINS) == {\n        "materials", "concrete_classes", "masonry_units", "rebar_bars",\n        "coverages", "labour", "plant", "trucks", "soils",\n        "rate_templates",\n    }')
open(p, 'w', encoding='utf-8').write(s)

# Verify
print('=== VERIFICATION ===')
print('schemas MIX_DESIGNS:', 'MIX_DESIGNS' in open(os.path.join(before_dir,'qs_engine/master_data/schemas.py'),encoding='utf-8').read())
print('sess last_mix_design:', 'last_mix_design' in open(os.path.join(before_dir,'qs_engine/ui/session.py'),encoding='utf-8').read())
print('views build_mix_design:', 'build_mix_design_page' in open(os.path.join(before_dir,'qs_engine/ui/views.py'),encoding='utf-8').read())
print('views mix_design:', '"mix_design"' in open(os.path.join(before_dir,'qs_engine/ui/views.py'),encoding='utf-8').read())
print('spec mixes:', 'qs_engine.mixes' in open(os.path.join(before_dir,'CIVOLINK-QS.spec'),encoding='utf-8').read())

# Generate diff
out_path = os.path.join(tmp, 'mix_design_engine.diff')
files = ['qs_engine/master_data/tables/mix_designs.json', 'qs_engine/mixes/__init__.py', 'qs_engine/mixes/calculator.py', 'tests/test_mix_design_engine.py', 'qs_engine/master_data/schemas.py', 'qs_engine/ui/session.py', 'qs_engine/ui/views.py', 'qs_engine/ui/controllers.py', 'CIVOLINK-QS.spec', 'tests/test_master_data.py']
with open(out_path, 'w', encoding='utf-8') as out:
    out.write("Phase 6 Mix Design & Constituent Engine\n")
    out.write("Files changed: {}\n\n".format(len(files)))
    for f in files:
        before_file = os.path.join(before_dir, f)
        after_file = os.path.join(after_dir, f)
        before_lines = open(before_file, encoding='utf-8').read().splitlines(True) if os.path.exists(before_file) else []
        after_lines = open(after_file, encoding='utf-8').read().splitlines(True)
        diff = list(difflib.unified_diff(before_lines, after_lines, fromfile='a/'+f, tofile='b/'+f, n=3))
        if diff:
            out.write(''.join(diff))
            out.write('\n')
print('diff size:', os.path.getsize(out_path), 'bytes')
