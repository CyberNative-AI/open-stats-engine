"""Pick evidence packages per first-unknown command by counts only (no output text read).

Usage: OSE_CENSUS_DIR=... OSE_WORDING_TABLE=... pick_evidence.py CMD [CMD...]. Prints usable, redistributable-licence packages whose
Stata text log first stops at CMD, smallest first. Add a package to open-list.tsv before reading its log."""
import json, os, sys, glob
HERE = os.path.dirname(os.path.abspath(__file__))
for sub in ('corpus', 'harness', 'engine'):
    sys.path.insert(0, os.path.join(HERE, '..', sub))
import command_freq as CF, logmatch as L
D = os.environ['OSE_CENSUS_DIR']   # the census output directory (kept outside the tree)
want = set(sys.argv[1:])
idx = json.load(open(D + '/logs.json'))
rows = {r['pid']: r for r in json.load(open(D + '/census.json'))['rows']}
reg, _ = CF.known_words()
openl = {l.split('\t')[1] for l in open(os.path.join(HERE, 'open-list.tsv')) if not l.startswith('#')}
out = {w: [] for w in want}
for fid, r in idx.items():
    if r.get('kind') != 'stata-text' or r.get('status') != 'ok': continue
    row = rows.get(r['pid'])
    if not row or row['tier'] != 'usable' or not row.get('redistributable'): continue
    blocks = L.parse_log(open(f'{D}/logs/{fid}.log', encoding='utf-8', errors='replace').read())
    fu = None; pos = 0; n = 0
    for b in blocks:
        if b.is_comment or b.is_logcmd: continue
        w = CF.cmd_word(b.key)
        if not w: continue
        n += 1
        if CF.canon(w, reg) is None and w not in ('if','else','foreach','forvalues','while','end','program'):
            fu = w; pos = n; break
    if fu in want:
        out[fu].append((row['files'], r['pid'], fid, r['name'], r['size'], pos, row['licence'], r['pid'] in openl))
for w, l in out.items():
    l.sort()
    print(w, len(l))
    for x in l[:6]: print('  files=%s %s log=%s %r size=%s first_unknown_at_cmd=%s %s open=%s' % x)
