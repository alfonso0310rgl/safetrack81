"""Converte i Word 'AGGIORNAMENTI DOCUMENTAZIONE' nel modello di importazione SafeTrack 81.
Uso: python3 word2excel.py output.xlsx file1.docx [file2.docx ...]
Regole: riga in rosso = dipendente non in forza; riga in giallo = datore di lavoro (mansione Amministratore);
DVR 4 anni; date su più giorni -> ultimo giorno; voci 'DA FARE' non contano come fatte."""
import sys, re, datetime as dt, unicodedata, difflib
import docx, openpyxl
from docx.oxml.ns import qn
from openpyxl.styles import Font, Alignment, PatternFill

TPL = '/home/claude/safetrack81/modello_importazione.xlsx'

# ---------------- utilità ----------------
def clean(s): return re.sub(r'\s+', ' ', (s or '').replace('\xa0', ' ').replace('*', '')).strip()
def norm(s): return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFD', (s or '').lower()).encode('ascii', 'ignore').decode())
def parole(s): return [unicodedata.normalize('NFD', w.upper()).encode('ascii', 'ignore').decode() for w in clean(s).split()]

AVVISI = []
def dte(s, ctx=''):
    """prima data valida nel testo; '16-17-18/01/2024' -> 18/01/2024"""
    s = s or ''
    m = re.search(r'((?:\d{1,2}\s*-\s*)+)(\d{1,2})/(\d{1,2})/(\d{4})', s) or re.search(r'()(\d{1,2})[/.](\d{1,2})[/.](\d{4})', s)
    if not m: return None
    try: return dt.date(int(m[4]), int(m[3]), int(m[2]))
    except ValueError:
        if ctx: AVVISI.append(f'{ctx}: data non valida "{m[0]}" — non importata')
        return None
def resto_testo(s):
    s = re.sub(r'((?:\d{1,2}\s*-\s*)*)\d{1,2}[/.]\d{1,2}[/.]\d{4}', '', s or '')
    return clean(s.strip(' –-:/'))

# codice fiscale: parte cognome e nome
VOC = set('AEIOU')
def _cf_cog(s):
    s = re.sub(r'[^A-Z]', '', s); c = [x for x in s if x not in VOC]; v = [x for x in s if x in VOC]
    return (c + v + ['X'] * 3)[:3]
def _cf_nom(s):
    s = re.sub(r'[^A-Z]', '', s); c = [x for x in s if x not in VOC]; v = [x for x in s if x in VOC]
    if len(c) >= 4: c = [c[0], c[2], c[3]]
    return (c + v + ['X'] * 3)[:3]
def dividi(nome, cf=''):
    """(cognome, nome) usando il codice fiscale quando possibile; altrimenti ultima parola = nome"""
    orig = clean(nome).split(); w = parole(nome)
    if len(w) < 2: return clean(nome), '(da completare)'
    cf = (cf or '').upper()
    if re.fullmatch(r'[A-Z]{6}.*', cf):
        for i in range(1, len(w)):
            for cog, nom in (((0, i), (i, len(w))), ((i, len(w)), (0, i))):
                if ''.join(_cf_cog(''.join(w[cog[0]:cog[1]]))) == cf[:3] and ''.join(_cf_nom(''.join(w[nom[0]:nom[1]]))) == cf[3:6]:
                    return ' '.join(orig[cog[0]:cog[1]]), ' '.join(orig[nom[0]:nom[1]])
    PART = {'DE', 'DI', 'DEL', 'DELLA', 'DELLE', 'DA', 'LA', 'LO', 'DAL', 'DALLA', 'D'}
    if len(w) >= 3 and w[-2] in PART: return ' '.join(orig[-2:]), ' '.join(orig[:-2])   # MARIO DE FELICE
    if w[0] in PART: return ' '.join(orig[:2]), ' '.join(orig[2:])                       # DI PALMA ANDREA
    return orig[0], ' '.join(orig[1:])                                                    # cognome + nome/i

def colori(cell):
    out = set(); tcPr = cell._tc.tcPr
    if tcPr is not None:
        sh = tcPr.find(qn('w:shd'))
        if sh is not None and sh.get(qn('w:fill')) not in (None, 'auto'): out.add(sh.get(qn('w:fill')).upper())
    HL = {'YELLOW': 'FFFF00', 'RED': 'FF0000', 'DARK_RED': 'C00000', 'DARK_YELLOW': 'FFFF00'}
    for p in cell.paragraphs:
        for r in p.runs:
            if r.font.highlight_color is not None:
                out.add(HL.get(str(r.font.highlight_color).split('.')[-1].split(' ')[0], 'XX'))
            rp = r._r.rPr
            if rp is not None and rp.find(qn('w:shd')) is not None:
                f = rp.find(qn('w:shd')).get(qn('w:fill'))
                if f and f != 'auto': out.add(f.upper())
            try:
                if r.font.color is not None and r.font.color.type is not None and r.font.color.rgb is not None:
                    out.add('T' + str(r.font.color.rgb).upper())
            except Exception: pass
    return out
def _rgb(h):
    h = h.lstrip('T'); return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)) if re.fullmatch(r'[0-9A-F]{6}', h) else None
def rosso(c): x = _rgb(c); return bool(x) and x[0] >= 0xB0 and x[1] < 0x60 and x[2] < 0x60
def giallo(c): x = _rgb(c); return bool(x) and not c.startswith('T') and x[0] >= 0xE0 and x[1] >= 0xE0 and x[2] < 0xA0

MESI_LIV = {'basso': 'Livello I', 'medio': 'Livello II', 'alto': 'Livello III'}
def livello_antincendio(t):
    m = re.search(r'(?i)liv(?:ello)?\.?\s*(iii|ii|i|[123])\b', t)
    if m: return 'Livello ' + {'1': 'I', '2': 'II', '3': 'III'}.get(m[1], m[1].upper())
    for k, v in MESI_LIV.items():
        if re.search(r'\b' + k + r'\b', t.lower()): return v
    return ''
def rischio(t):
    for k in ('alto', 'medio', 'basso'):
        if re.search(r'\b' + k + r'\b', (t or '').lower()): return 'Rischio ' + k
    return ''
def anni_corso(nome):
    n = norm(nome)
    if 'ponteggi' in n: return 4
    if 'haccp' in n or 'alimentar' in n: return 3
    return 5

# ---------------- lettura di un Word ----------------
def leggi(path):
    d = docx.Document(path)
    R = {'az': {}, 'dip': [], 'fig': [], 'doc': [], 'for': [], 'ido': []}
    righe = [clean(p.text) for p in d.paragraphs if clean(p.text)]
    az = R['az']
    primo = righe[0]
    m = re.match(r'^(.*?)\s*-\s*\((.*)\)?$', primo)
    az['nome'] = clean(m[1]) if m else primo
    ateco = [clean(m[2]).rstrip(')')] if m else []
    if not ateco:
        for t in righe[1:]:
            if re.match(r'(?i)^(sede|partita|p\.?\s*iva|codice fiscale|amministrat|datore|mail)', t): break
            ateco.append(t)
    az['settore'] = re.sub(r'[()]', '', ' '.join(ateco)).replace('Codice ATECO: ', '').replace('Codice: ', '').strip()
    ctx = az['nome']
    rspp = {'nome': '', 'nom': None, 'att': [], 'note': []}
    prep, rls = {}, {}
    medico = None; dvr = []
    ultimo = ''; consulente = False; assunz = {}
    for t in righe[1:]:
        if re.search(r'(?i)consulente', t): consulente = True
        if '@' in t and not az.get('email') and not consulente:
            em = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', t)
            if em: az['email'] = em[0]
        if '@' not in t and not re.search(r'(?i)consulente', t) and not t.startswith('michela'): consulente = consulente and '@' in t
        ma = re.match(r'(?i)^data di assunzione\s+(.+?)\s*:\s*(.*)$', t)
        if ma:
            if dte(ma[2]): assunz[' '.join(sorted(parole(ma[1])))] = dte(ma[2])
            continue
        mx = re.match(r'(?i)^(att\.?(?:\s*agg\.?)?)\s*[-–]\s*(.*)$', t)
        if mx and ':' not in t: t = mx[1] + ' ' + ultimo + ': ' + mx[2]
        lab, sep, rest = t.partition(':')
        if not sep:
            lab, sep, rest = t.partition(' – ')
            if not sep or not dte(rest): continue
        L = norm(lab); rest = clean(rest).rstrip(':').strip()
        if L in ('att', 'attagg') and ultimo: L = L + ultimo; lab = lab + ' ' + ultimo
        for ruolo in ('rspp', 'preposto', 'rls', 'medicocompetente'):
            if ruolo in L: ultimo = ruolo
        # nome – data – note
        mm = re.match(r'^(.*?)\s*(?:–|—|\s-\s|-\s*$|-(?=\s*\d))\s*(.*)$', rest)
        nome, coda = (clean(mm[1]), mm[2]) if mm else (re.sub(r'\(.*?\)', '', resto_testo(rest)).strip(), re.sub(r'^[^(]*', '', rest) if not dte(rest) else rest)
        if re.fullmatch(r'\(.*\)|', nome or ''): nome = ''
        data = dte(coda, f'{ctx} — {clean(lab)}')
        nota = resto_testo(coda).strip('() ')
        dafare = bool(re.search(r'(?i)da fare|da nominare|da aprire', coda))
        if dafare: data = None
        if L.startswith('partitaiva') or L.startswith('piva'): az['piva'] = re.sub(r'\D', '', rest) or rest
        elif L.startswith('sedelegale'):
            az['sl'] = rest
            if 'operativ' in L: az['so'] = rest
        elif L.startswith('sedeoperativa'):
            extra = re.sub(r'^sedeoperativa', '', L)
            val = (clean(lab.split('Operativa', 1)[-1]) + ': ' if extra else '') + rest
            az['so'] = (az['so'] + ' / ' + val) if az.get('so') else val
        elif (L.startswith('amministrat') or L.startswith('datoredilavoro')) and not az.get('ref'):
            az['ref'] = ('Datore di lavoro: ' if 'datore' in L else 'Amministratore: ') + rest; az['datore'] = re.sub(r'\(.*?\)', '', rest).strip()
        elif 'rspp' in L:
            if not L.startswith('att'):
                rspp['nome'] = nome or rspp['nome']; rspp['nom'] = data
                if nota: rspp['note'].append('Nomina: ' + nota)
            else:
                rspp['nome'] = rspp['nome'] or nome
                if data: rspp['att'].append(data)
                elif nota: rspp['note'].append('Attestato: ' + nota)
        elif 'preposto' in L:
            if not nome: continue
            p = prep.setdefault(norm(nome), {'nome': nome, 'nom': None, 'att': [], 'note': []})
            if not L.startswith('att'): p['nom'] = data or p['nom']
            elif data: p['att'].append(data)
            if nota: p['note'].append(nota)
        elif 'rls' in L:
            if not nome: continue
            r = rls.setdefault(norm(nome), {'nome': nome, 'nom': None, 'att': [], 'note': []})
            if not L.startswith('att'): r['nom'] = data
            elif data: r['att'].append(data)
            if nota and not data: r['note'].append(('Attestato: ' if L.startswith('att') else 'Elezione: ') + nota)
        elif 'medicocompetente' in L:
            medico = [nome or rest, data, nota]
        elif L.startswith('dvr'):
            mr = re.search(r'(?i)rev\.?\s*[:.n°]*\s*(\d+)', t)
            if data: dvr.append((data, 'Rev. ' + mr[1] if mr else ''))
            elif dafare: AVVISI.append(f'{ctx}: DVR {("Rev. " + mr[1]) if mr else ""} indicato "DA FARE" — non importato')
        elif 'riunioneperiodica' in L:
            if data: R['doc'].append(['Verbale Riunione Periodica', data, None, None, nota])
        elif 'evacuazione' in L:
            if data: R['doc'].append(['Verbale Prova Evacuazione', data, None, None, nota])
        elif L.startswith('visit') or L.startswith('macchinari') or L.startswith('note'):
            continue
        elif L.startswith('nomina'):
            if data: R['doc'].append([clean(lab).capitalize() + (' — ' + nome if nome else ''), data, None, None, nota])
        elif nome and data:
            R['for'].append(['@' + nome, None, None, clean(lab), '', data, anni_corso(lab), nota])
        elif data and len(lab) < 80:
            R['doc'].append([clean(lab), data, None, None, nota])
    # figure
    if rspp['nome']:
        att = max(rspp['att']) if rspp['att'] else None
        R['fig'].append(['RSPP', rspp['nome'], rspp['nom'], att, 5 if att else None, '; '.join(rspp['note'])])
    for p in prep.values():
        att = max(p['att']) if p['att'] else None
        R['fig'].append(['Preposto', p['nome'], p['nom'], att, 2 if att else None, '; '.join(dict.fromkeys(p['note']))])
    for r in rls.values():
        att = max(r['att']) if r['att'] else None
        R['fig'].append(['RLS', r['nome'], r['nom'], att, 1 if att else None, '; '.join(r['note'])])
    if medico and medico[0]:
        R['fig'].append(['Medico competente', medico[0], medico[1], None, None, medico[2]])
    if dvr:
        data, rev = max(dvr, key=lambda x: x[0]); R['doc'].insert(0, ['DVR', data, 4, rev, ''])

    # ---------- tabelle ----------
    legenda = {}
    for tb in d.tables:
        for r in tb.rows:
            txt = clean(' '.join(c.text for c in r.cells))
            mL = re.match(r'(?i)^dipendenti\s+(.+?):?$', txt)
            if mL:
                for c in r.cells:
                    for col in colori(c):
                        if _rgb(col) and not rosso(col) and not giallo(col): legenda[col] = 'Sede ' + mL[1].strip(' :').title()
    visti = {}
    datore_n = set(parole(az.get('datore', '')))
    liv_ateco = rischio(az.get('settore', ''))
    for tb in d.tables:
        rows = [[[clean(p.text) for p in c.paragraphs if clean(p.text)] for c in r.cells] for r in tb.rows]
        if not rows: continue
        head = [norm(' '.join(c)) for c in rows[0]]
        if any(h.startswith('nominativ') for h in head):
            col = lambda *ks: next((j for j, h in enumerate(head) for k in ks if h.startswith(k)), None)
            iN = col('nominativ'); iCF = col('codic'); iDN = col('datadinascita'); iLN = col('luogodinascita', 'logodinascita')
            iDA = col('dataassunzione'); iM = col('mansione'); iF = col('form'); iI = col('inform'); iD = col('dpi'); iV = col('visit')
            liv = rischio(' '.join(rows[0][iF])) if iF is not None else ''
            liv = liv or liv_ateco or 'Rischio alto'
            for k, r in enumerate(rows[1:], 1):
                g = lambda j: (' '.join(r[j]) if j is not None and j < len(r) else '')
                n = clean(g(iN))
                if not n or norm(n).startswith('nominativ'): continue
                cf = re.sub(r'\s', '', g(iCF)).upper()
                cog, nom = dividi(n, cf)
                dn0 = dte(g(iDN))
                if dn0 and re.fullmatch(r'[A-Z]{6}\d{2}.*', cf) and cf[6:8] != dn0.strftime('%y'):
                    AVVISI.append(f'{ctx}: {n} — la data di nascita {dn0:%d/%m/%Y} non corrisponde al codice fiscale ({cf})')
                if len(parole(n)) < 2: AVVISI.append(f'{ctx}: dipendente "{n}" senza cognome/nome completo — inserito come "{n} (da completare)"')
                if cf and not re.fullmatch(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]', cf):
                    AVVISI.append(f'{ctx}: codice fiscale da controllare per {n} ({cf})')
                cells = tb.rows[k].cells
                cl = colori(cells[iN]); tutti = set().union(*[colori(c) for c in cells])
                attivo = 'NO' if any(rosso(c) for c in cl) else 'SI'
                mans0 = clean(g(iM)).strip('/ ')
                datore = any(giallo(c) for c in cl) or bool(re.match(r'(?i)^(datore|amminis)', mans0))
                note = []
                if datore:
                    mans = 'Amministratore'
                    note.append('Datore di lavoro' + (' — ' + mans0 if mans0 and not re.match(r'(?i)^(datore|amministr\.?|amministratore)$', mans0) else ''))
                else: mans = mans0
                dn = dte(g(iDN)); ln = clean(g(iLN)).strip('/ ')
                if dn or ln: note.append('Nato il ' + (dn.strftime('%d/%m/%Y') if dn else '?') + (' a ' + ln if ln else ''))
                inf = dte(g(iI))
                if inf: note.append('Informazione: ' + inf.strftime('%d/%m/%Y'))
                dpi = g(iD)
                if dte(dpi): note.append('Consegna DPI: ' + dte(dpi).strftime('%d/%m/%Y'))
                elif re.search(r'(?i)da\s*agg', dpi): note.append('DPI da aggiornare')
                for c in tutti:
                    if c in legenda and legenda[c] not in note: note.append(legenda[c])
                # formazione lavoratori
                fv = g(iF); fd = dte(fv, f'{ctx} — formazione {n}'); fx = resto_testo(fv).strip('/- ')
                if fd and dn and fd == dn:
                    AVVISI.append(f'{ctx}: {n} ha come data di formazione {fd:%d/%m/%Y} (coincide con la nascita?) — non importata'); fd = None
                if fx and not fd: note.append('Formazione: ' + fx)
                if attivo == 'NO' and fx and fd: note.append(fx)
                key = cf or norm(cog + nom)
                if key in visti:
                    if not datore: AVVISI.append(f'{ctx}: {n} compare due volte nell\'elenco dipendenti — tenuto una volta')
                    continue
                visti[key] = 1
                R['dip'].append([cog, nom, cf, mans, dte(g(iDA)) or assunz.get(' '.join(sorted(parole(n)))), attivo, '; '.join(note)])
                if fd: R['for'].append([cog, nom, cf, 'Formazione specifica', liv, fd, 5, ('Formazione lavoratori' + (' — ' + fx if fx else ''))])
                vv = g(iV); vd = dte(vv)
                if vd:
                    ma = re.search(r'(\d+)\s*ANN', vv.upper())
                    R['ido'].append([cog, nom, cf, vd, int(ma[1]) if ma else 1, ''])
            continue
        # tabelle corsi
        h1 = [norm(' '.join(c)) for c in rows[0][1:]]
        if h1 and any(x in ('formazione', 'aggiornamento') for x in h1):
            corso = clean(' '.join(rows[0][0]))
            for r in rows[1:]:
                nomi = r[0] if r else []
                ds = [x for x in (dte(' '.join(c), f'{ctx} — {corso}') for c in r[1:]) if x]
                if not nomi: continue
                if not ds: AVVISI.append(f'{ctx}: corso "{corso}" di {", ".join(nomi)} senza data — non importato'); continue
                for n in nomi:
                    nota = ''; mm = re.search(r'\((.*?)\)', n)
                    if mm: nota = mm[1]; n = clean(n[:mm.start()])
                    R['for'].append(['@' + n, None, None, corso, '', max(ds), anni_corso(corso), nota])
            continue
        prec = ''
        for r in rows:
            if len(r) < 3: continue
            corso = clean(' '.join(r[0])); nomi = r[1]; dtxt = ' '.join(' '.join(c) for c in r[2:])
            if re.fullmatch(r'(?i)(liv\.?\s*\w+|basso|medio|alto)', corso) and prec: corso = prec + ' ' + corso
            prec = re.sub(r'(?i)\s*(liv(ello)?\.?\s*\w+|basso|medio|alto)$', '', corso) or prec
            if not nomi or norm(corso).startswith('dipendenti'): continue
            ds = [x for x in (dte(' '.join(c), f'{ctx} — {corso}') for c in r[2:]) if x]; data = max(ds) if ds else None
            c = norm(corso)
            if 'antincendio' in c or c in ('basso', 'medio', 'alto'):
                tipo, lvl, anni = 'Antincendio', livello_antincendio(corso), 5
            elif 'primosoccorso' in c:
                tipo, anni = 'Primo soccorso', 3
                lvl = 'Gruppo A' if re.search(r'(?i)gruppo\s*a\b', corso) or re.match(r'0[5-9]', az.get('settore', '')) else ('Gruppo B/C' if re.search(r'(?i)gruppo\s*[bc]', corso) else '')
            else:
                tipo, lvl, anni = corso, '', anni_corso(corso)
            if not data:
                AVVISI.append(f'{ctx}: corso "{corso}" di {", ".join(nomi)} senza data — non importato'); continue
            for n in nomi:
                nota = ''; mm = re.search(r'\((.*?)\)', n)
                if mm: nota = mm[1]; n = clean(n[:mm.start()])
                R['for'].append(['@' + n, None, None, tipo, lvl, data, anni, nota])

    # collega i nomi dei corsi ai dipendenti
    def chiave(n): return ' '.join(sorted(parole(n)))
    idx = {chiave(a + ' ' + b): (a, b, cf) for a, b, cf, *_ in R['dip']}
    nuovi = {}
    for f in R['for']:
        if not str(f[0]).startswith('@'): continue
        n = f[0][1:]; k = chiave(n)
        if k not in idx:
            def quasi(a, b):
                A, B = a.split(), b.split()
                if len(A) != len(B): return False
                diff = [(x, y) for x, y in zip(A, B) if x != y]
                return len(diff) == 1 and abs(len(diff[0][0]) - len(diff[0][1])) <= 1 and difflib.SequenceMatcher(None, *diff[0]).ratio() >= 0.75
            simili = [x for x in idx if quasi(k, x)] or [x for x in idx if len(k.split()) >= 2 and set(k.split()) < set(x.split())]
            if len(simili) == 1:
                AVVISI.append(f'{ctx}: "{n}" nel corso "{f[3]}" associato a {" ".join(idx[simili[0]][:2])} (nome scritto in modo diverso)')
                k = simili[0]
        if k in idx: f[0], f[1], f[2] = idx[k]
        else:
            cog, nom = dividi(n)
            if set(parole(n)) == datore_n and datore_n: mans, nt = 'Amministratore', 'Datore di lavoro'
            else: mans, nt = '', 'Aggiunto dai corsi: non presente nell\'elenco dipendenti del Word'
            R['dip'].append([cog, nom, '', mans, None, 'SI', nt]); idx[k] = (cog, nom, '')
            f[0], f[1], f[2] = cog, nom, ''
            if mans != 'Amministratore': AVVISI.append(f'{ctx}: {n} ha il corso "{f[3]}" ma non è nell\'elenco dipendenti — aggiunto')
    # dedup corsi identici
    seen = set(); out = []
    for f in R['for']:
        k = (norm(f[0] + f[1]), norm(f[3]), f[5])
        if k in seen: continue
        seen.add(k); out.append(f)
    R['for'] = out
    return R

# ---------------- scrittura ----------------
def scrivi(out, docs):
    wb = openpyxl.load_workbook(TPL); nxt = {}
    def put(sh, vals):
        ws = wb[sh]; r = nxt.get(sh, 3); nxt[sh] = r + 1
        for j, v in enumerate(vals, 1):
            if v is not None and v != '': ws.cell(r, j, v)
    letti = [leggi(p) for p in docs]
    nomi = [R['az']['nome'] for R in letti]
    riep = []
    for R in letti:
        a = R['az']
        if nomi.count(a['nome']) > 1:
            m = re.search(r'\d{5}\s*-?\s*([A-Z’\' .]+?)\s*\((\w\w)\)', a.get('so', '')) or re.search(r'\d{5}\s*-?\s*([A-Z’\' .]+?)\s*\((\w\w)\)', a.get('sl', ''))
            if m: a['nome'] = f"{a['nome']} - {clean(m[1])} ({m[2]})"
        N = a['nome']
        put('Aziende', [N, a.get('piva'), a.get('settore'), a.get('email'), a.get('ref'), a.get('sl'), a.get('so'), None])
        for r in R['dip']: put('Dipendenti', [N] + r)
        for ru, nome, dn, da, anni, nota in R['fig']: put('Figure', [N, ru, nome, dn, None, None, da, anni, None, nota])
        for nome, data, anni, rev, nota in R['doc']: put('Documenti', [N, nome, data, anni, None, rev, nota])
        for f in R['for']: put('Formazione', [N] + f[:6] + [f[6], None, f[7]])
        for v in R['ido']: put('Idoneità mediche', [N] + v[:4] + [v[4], None, v[5]])
        riep.append((N, len(R['dip']), len(R['fig']), len(R['doc']), len(R['for']), len(R['ido'])))
    # foglio controlli (ignorato dall'importazione)
    ws = wb.create_sheet('Da controllare', 1)
    ws.column_dimensions['A'].width = 130
    ws['A1'] = 'Cose da controllare prima di importare (questo foglio non viene importato)'
    ws['A1'].font = Font(name='Arial', bold=True, size=12, color='B8571D')
    for i, a in enumerate(AVVISI, 3):
        c = ws.cell(i, 1, '• ' + a); c.font = Font(name='Arial', size=10); c.alignment = Alignment(wrap_text=True)
    wb.save(out)
    return riep

if __name__ == '__main__':
    for r in scrivi(sys.argv[1], sys.argv[2:]): print(r)
    for a in AVVISI: print('AVVISO', a)
