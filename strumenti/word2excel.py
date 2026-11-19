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
def parole(s): return [unicodedata.normalize('NFD', w.upper().replace('’', "'").replace('`', "'")).encode('ascii', 'ignore').decode() for w in clean(s).split()]

AVVISI = []
def dte(s, ctx=''):
    """prima data valida nel testo; '16-17-18/01/2024' -> 18/01/2024"""
    s = (s or '').replace('//', '/')
    if re.search(r'(?i)senza data', s): return None
    m0 = re.fullmatch(r'.*?\b(\d{1,2})-(\d{1,2})-(\d{4})\b.*', s)
    if m0:
        try: return dt.date(int(m0[3]), int(m0[2]), int(m0[1]))
        except ValueError: pass
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

def persona(n):
    n0 = re.sub(r'\(.*?\)', '', n or '').strip()
    if not n0 or len(n0.split()) > 6 or re.search(r'[;,:]', n0) or n0[:1].islower(): return False
    if re.search(r'(?i)posture|vibraz|microclima|\bmmc\b|biologic|alcoo?l|rumore|\bvdt\b|rischio|chimic|polveri|videotermin|giubbino|scarpe|guanti|accordo|droga|s\.r\.l|srl|movimentaz', n0): return False
    return True
def e_corso(t):
    t = re.sub(r'\(.*?\)', '', t or '')
    return bool(re.search(r'(?i)antincend|soccorso|haccp|formaz|corso|addett|conduzion|conduttor|ponteg|carrell|trattor|\bgru\b|\bple\b|quota|\bdpi\b|responsabil|alimentar|attestat|escavat|muletti|elevator|movimento terra|^liv|^(basso|medio|alto)$', t))
def classifica(corso, settore=''):
    c = norm(corso); sede = re.findall(r'\(([^)]*)\)', corso)
    if 'antincendio' in c or c in ('basso', 'medio', 'alto'):
        return 'Antincendio', livello_antincendio(corso), 5
    if 'primosoccorso' in c:
        lvl = 'Gruppo A' if re.search(r'(?i)gruppo\s*a\b', corso) or re.match(r'0[5-9]', settore) else ('Gruppo B/C' if re.search(r'(?i)gruppo\s*[bc]', corso) else '')
        return 'Primo soccorso', lvl, 3
    return clean(re.sub(r'(?i)^att\.?\s*', '', corso)), '', anni_corso(corso)

def voce_figura(diz, nome):
    """stessa persona scritta con o senza note tra parentesi -> una sola voce; omonimi con date di nascita diverse restano separati"""
    base = norm(re.sub(r'\(.*?\)', '', nome)); par = ' '.join(re.findall(r'\((.*?)\)', nome))
    dpar = dte(par)
    for k, v in diz.items():
        if v['base'] != base: continue
        if dpar and v['dnasc'] and v['dnasc'] != dpar: continue
        if dpar and not v['dnasc']: v['dnasc'] = dpar; v['nome'] = nome
        if par and not dpar and par not in v['note']: v['note'].append(par)
        return v
    v = {'nome': nome if dpar else clean(re.sub(r'\(.*?\)', '', nome)), 'nom': None, 'att': [], 'note': [par] if par and not dpar else [], 'base': base, 'dnasc': dpar}
    diz[norm(nome)] = v
    return v

# ---------------- lettura di un Word ----------------
def leggi(path):
    d = docx.Document(path)
    R = {'az': {}, 'dip': [], 'fig': [], 'doc': [], 'for': [], 'ido': []}
    righe = [clean(p.text) for p in d.paragraphs if clean(p.text)]
    for tb0 in d.tables:
        if len(tb0.columns) == 1:
            righe += [clean(c.text) for r0 in tb0.rows for c in r0.cells[:1] if clean(c.text)]
    p0 = next((p.text for p in d.paragraphs if clean(p.text)), '')
    if re.search(r'\*{2,}\s*[^*]+\*{2,}', p0): righe[0] = clean(re.sub(r'\*{2,}\s*([^*]+?)\s*\*{2,}', r' - \1', p0))
    az = R['az']
    primo = righe[0]
    m = re.match(r'^(.*?)\s*-\s*\((.*)\)?$', primo)
    az['nome'] = (clean(m[1]) if m else primo).rstrip(' –-')
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
    ultimo = ''; consulente = False; assunz = {}; correzioni_cf = {}; att_rspp_altri = {}
    in_visite = False
    for t in righe[1:]:
        if re.match(r'(?i)^visite mediche', t): in_visite = True
        if re.search(r'(?i)consulente', t): consulente = True
        if '@' in t and not az.get('email') and not consulente and not ultimo:
            em = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', t)
            if em: az['email'] = em[0]
        if '@' not in t and not re.search(r'(?i)consulente', t) and not t.startswith('michela'): consulente = consulente and '@' in t
        mcf = re.search(r'(?i)modifica codice fiscale di (.+?) da ([A-Z0-9]{16}) a ([A-Z0-9]{16})', t)
        if mcf:
            AVVISI.append(f'{ctx}: codice fiscale di {mcf[1]} corretto da {mcf[2]} a {mcf[3]} (come indicato nel Word)')
            correzioni_cf[mcf[2].upper()] = mcf[3].upper(); continue
        if re.match(r'(?i)^(mansione .+ da .+ a |sulla visita medica di)', t): AVVISI.append(f'{ctx}: nota nel Word — {t}')
        ma = re.match(r'(?i)^data di assunzione\s+(.+?)\s*:\s*(.*)$', t)
        if ma:
            if dte(ma[2]): assunz[' '.join(sorted(parole(ma[1])))] = dte(ma[2])
            continue
        mx = re.match(r'(?i)^(att\.?(?:\s*agg\.?)?)\s*[-–]\s*(.*)$', t)
        if mx and ':' not in t: t = mx[1] + ' ' + ultimo + ': ' + mx[2]
        lab, sep, rest = t.partition(':')
        if not sep:
            lab, sep, rest = t.partition(' – ')
            if not sep:
                mp = re.match(r'^(.*?)\s+(\d{1,2}[/.]\d{1,2}[/.]\d{4}.*)$', t)
                if mp and len(mp[1]) < 60 and re.search(r'(?i)verbale|prova|riunione', mp[1]): lab, sep, rest = mp[1], ':', mp[2]
            if not sep or not dte(rest): continue
        L = norm(lab); rest = clean(rest).rstrip(':').strip()
        rest = re.sub(r'(?<=[A-Za-z)])\s*:\s*(?=\d)', ' – ', rest)
        if L in ('att', 'attagg') and ultimo: L = L + ultimo; lab = lab + ' ' + ultimo
        for ruolo in ('rspp', 'preposto', 'rls', 'medicocompetente'):
            if ruolo in L: ultimo = ruolo
        # nome – data – note
        mm = re.match(r'^(.*?)\s*(?:–|—|\s-\s|-\s*$|-(?=\s*\d))\s*(.*)$', rest)
        nome, coda = (clean(mm[1]), mm[2]) if mm else (re.sub(r'\(.*?\)', '', resto_testo(rest)).strip(), re.sub(r'^[^(]*', '', rest) if not dte(rest) else rest)
        nome = re.sub(r'(?i)\s+(attestato|att\.)\b.*$', '', nome or '').strip()
        if re.fullmatch(r'\(.*\)|', nome or '') or re.match(r'(?i)^(da fare|da nominare|da aprire|no\b|in corso)', nome or ''): nome = ''
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
            if not L.startswith(('att', 'agg')):
                rspp['nome'] = nome or rspp['nome']; rspp['nom'] = max(filter(None, [rspp['nom'], data]), default=None)
                sedeL = re.search(r'\(([^)]*)\)', lab)
                if sedeL and data: rspp['note'].append(f'Nomina {sedeL[1].title()}: {data:%d/%m/%Y}')
                if nota: rspp['note'].append('Nomina: ' + nota)
            else:
                if rspp['nome'] and nome and not (set(parole(rspp['nome'])) <= set(parole(nome)) or set(parole(nome)) <= set(parole(rspp['nome']))):
                    # "Att. RSPP" di un'altra persona vicino al preposto: è il suo attestato da preposto (aggiornamento ogni 2 anni)
                    if data: att_rspp_altri.setdefault(norm(nome), []).append(data)
                    continue
                rspp['nome'] = rspp['nome'] or nome
                if data: rspp['att'].append(data)
                elif nota: rspp['note'].append('Attestato: ' + nota)
        elif 'preposto' in L:
            if not nome: continue
            p = voce_figura(prep, nome)
            if not L.startswith(('att', 'agg')): p['nom'] = data or p['nom']
            elif data: p['att'].append(data)
            if nota: p['note'].append(nota)
        elif 'rls' in L:
            if not nome: continue
            r = voce_figura(rls, nome)
            if not L.startswith(('att', 'agg')): r['nom'] = data
            elif data: r['att'].append(data)
            if nota and not data: r['note'].append(('Attestato: ' if L.startswith(('att', 'agg')) else 'Elezione: ') + nota)
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
        elif re.match(r'(?i)^(il|la|i|le)\s+dipend', lab):
            AVVISI.append(f'{ctx}: nota nel Word — {t}'); continue
        elif L.startswith('visit') or L.startswith('macchinari') or L.startswith('note'):
            continue
        elif L.startswith('nomina'):
            if data: R['doc'].append([clean(lab).capitalize() + (' — ' + nome if nome else ''), data, None, None, nota])
        elif nome and data:
            R['for'].append(['@' + nome, None, None, clean(lab), '', data, anni_corso(lab), nota])
        elif nome and not in_visite and persona(nome) and e_corso(lab) and len(parole(nome)) >= 2 and not re.search(r'(?i)nomina|elezione|dvr|verbale', lab):
            R['for'].append(['@' + nome, None, None, clean(lab), '', None, None, '; '.join(x for x in ('DATA DA INSERIRE', nota) if x)])
            AVVISI.append(f'{ctx}: corso "{clean(lab)}" di {nome} senza data — inserito con la data da completare')
        elif data and len(lab) < 80:
            R['doc'].append([clean(lab), data, None, None, nota])
    # figure
    if rspp['nome']:
        att = max(rspp['att']) if rspp['att'] else None
        R['fig'].append(['RSPP', rspp['nome'], rspp['nom'], att, 5 if att else None, '; '.join(rspp['note'])])
    for k0, ds0 in att_rspp_altri.items():
        hit = [v for v in prep.values() if v['base'] == norm(re.sub(r'\(.*?\)', '', k0))]
        if hit: hit[0]['att'] += ds0
        else: AVVISI.append(f'{ctx}: attestato RSPP di {k0.upper()} non collegato: la persona non è né RSPP né preposto — non importato')
    for p in prep.values():
        att = max(p['att']) if p['att'] else None
        R['fig'].append(['Preposto', p['nome'], p['nom'], att, 2 if att else None, '; '.join(dict.fromkeys(p['note']))])
    for r in rls.values():
        att = max(r['att']) if r['att'] else None
        R['fig'].append(['RLS', r['nome'], r['nom'], att, 1 if att else None, '; '.join(r['note'])])
    if len(rls) > 1:
        AVVISI.append(f'{ctx}: nel Word ci sono {len(rls)} RLS ({", ".join(r["nome"] for r in rls.values())}): il gestionale ne tiene uno solo, viene caricato l\'ultimo ({list(rls.values())[-1]["nome"]})')
    if medico and medico[0]:
        R['fig'].append(['Medico competente', medico[0], medico[1], None, None, medico[2]])
    if dvr:
        data, rev = max(dvr, key=lambda x: x[0]); R['doc'].insert(0, ['DVR', data, 4, rev, ''])

    # ---------- tabelle ----------
    # paragrafo che precede ogni tabella (es. "DIPENDENTI NOLA:")
    prime = []; ultimo_p = ''
    for el in d.element.body.iterchildren():
        if el.tag == qn('w:p'):
            t = clean(''.join(x.text or '' for x in el.iter(qn('w:t'))))
            if t: ultimo_p = t
        elif el.tag == qn('w:tbl'):
            prime.append(ultimo_p); ultimo_p = ''
    # legende di colore: "DIPENDENTI SALERNO", "LAVORATORI NON PIU' PRESENTI", "AMMINISTRATORE"...
    legenda = {}; col_off = set(); col_dat = set()
    for tb in d.tables:
        for r in tb.rows:
            txt = clean(' '.join(c.text for c in r.cells))
            cols = set().union(*[colori(c) for c in r.cells]) - {x for x in set().union(*[colori(c) for c in r.cells]) if x.startswith('T')}
            if not cols or len(r.cells) > 3: continue
            if re.match(r'(?i)^dipendenti\s+(.+?):?$', txt):
                for col in cols:
                    if not rosso(col) and not giallo(col): legenda[col] = 'Sede ' + re.match(r'(?i)^dipendenti\s+(.+?):?$', txt)[1].strip(' :').title()
            elif re.search(r'(?i)non pi[uù]|non assunt|licenziat|cessat', txt):
                col_off |= cols
                if re.search(r'(?i)non assunt', txt):
                    for col in cols: legenda[col] = 'Non assunto (solo visita medica)'
            elif re.search(r'(?i)amministrator|datore', txt): col_dat |= cols
    visti = {}; prec = ''
    tutto_doc = ' '.join(p.text for p in d.paragraphs)
    rosso_rinnovo = bool(re.search(r'(?i)rosso\W{0,3}\s*(da\s+)?rinnov', tutto_doc))
    datore_n = set(parole(az.get('datore', '')))
    liv_ateco = rischio(az.get('settore', ''))
    head_prec = None
    for ti, tb in enumerate(d.tables):
        rows = [[[clean(p.text) for p in c.paragraphs if clean(p.text)] for c in r.cells] for r in tb.rows]
        if not rows: continue
        head = [norm(' '.join(c)) for c in rows[0]]
        offset = 0; inizio = 1
        dip_tab = len(rows[0]) >= 6 and any(h.startswith('nominativ') for h in head)
        if not dip_tab and head_prec and len(rows[0]) >= 8 and len(rows[0]) in (len(head_prec), len(head_prec) - 1):
            head = head_prec; offset = len(head_prec) - len(rows[0]); inizio = 0; dip_tab = True   # riga del datore in tabella a parte
        if dip_tab:
            head_prec = head
            pm = re.match(r'(?i)^dipendenti\s+([A-Za-zÀ-ÿ’\' ]+?)\s*:?$', (prime[ti] if ti < len(prime) else ''))
            sede = ('Sede ' + pm[1].title()) if pm else ''
            col = lambda *ks: next((j for j, h in enumerate(head) for k in ks if h.startswith(k)), None)
            iN = col('nominativ'); iCF = col('codic'); iDN = col('datadinascita'); iLN = col('luogodinascita', 'logodinascita')
            iDA = col('dataassunzione', 'datainizio'); iM = col('mansione'); iF = col('form'); iI = col('inform'); iD = col('dpi'); iV = col('visit')
            liv = rischio(' '.join(head[iF:iF + 1])) if iF is not None else ''
            liv = liv or liv_ateco or 'Rischio alto'
            dup_tab = []
            for k in range(inizio, len(rows)):
                r = [[]] * offset + rows[k]
                g = lambda j: (' '.join(r[j]) if j is not None and j < len(r) else '')
                n = clean(g(iN))
                if not n or norm(n).startswith('nominativ'): continue
                tag = ' '.join(re.findall(r'\((.*?)\)', n)); n = clean(re.sub(r'\(.*?\)', '', n))
                cf = re.sub(r'[^A-Za-z0-9]', '', g(iCF)).upper(); cf = correzioni_cf.get(cf, cf)
                cog, nom = dividi(n, cf)
                dn0 = dte(g(iDN))
                if dn0 and re.fullmatch(r'[A-Z]{6}\d{2}.*', cf) and cf[6:8] != dn0.strftime('%y'):
                    AVVISI.append(f'{ctx}: {n} — la data di nascita {dn0:%d/%m/%Y} non corrisponde al codice fiscale ({cf})')
                if len(parole(n)) < 2: AVVISI.append(f'{ctx}: dipendente "{n}" senza cognome/nome completo — inserito come "{n} (da completare)"')
                if cf and not re.fullmatch(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]', cf):
                    AVVISI.append(f'{ctx}: codice fiscale da controllare per {n} ({cf})')
                cells = [None] * offset + list(tb.rows[k].cells)
                cl = colori(cells[iN]) if cells[iN] is not None else set()
                tutti = set().union(*[colori(c) for c in cells if c is not None])
                attivo = 'NO' if any((rosso(c) and not rosso_rinnovo) or c in col_off for c in cl) else 'SI'
                if rosso_rinnovo and any(rosso(c) for c in cl):
                    AVVISI.append(f'{ctx}: {n} è in rosso, ma in questo Word il rosso significa "da rinnovare": lasciato in forza')
                mans0 = clean(g(iM)).strip('/ ')
                datore = any(giallo(c) or c in col_dat for c in cl) or bool(re.match(r'(?i)^(datore|amminis)', mans0))
                note = []
                if datore:
                    mans = 'Amministratore'
                    note.append('Datore di lavoro' + (' — ' + mans0 if mans0 and not re.match(r'(?i)^(datore|amministr\w*\.?|amministratore)$', mans0) else ''))
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
                if sede and sede not in note: note.append(sede)
                if tag: note.append(tag)
                fv = g(iF); fd = dte(fv, f'{ctx} — formazione {n}'); fx = resto_testo(fv).strip('/- ')
                if fd and dn and fd == dn:
                    AVVISI.append(f'{ctx}: {n} ha come data di formazione {fd:%d/%m/%Y} (coincide con la nascita?) — non importata'); fd = None
                if fx and not fd: note.append('Formazione: ' + fx)
                senza_f = bool(fx and not fd and re.search(r'[A-Za-z]', fx))
                key = cf or norm(cog + nom)
                if key in visti:
                    if not datore: dup_tab.append(n)
                    continue
                visti[key] = 1
                R['dip'].append([cog, nom, cf, mans, dte(g(iDA)) or assunz.get(' '.join(sorted(parole(n)))), attivo, '; '.join(note)])
                if fd: R['for'].append([cog, nom, cf, 'Formazione specifica', liv, fd, 5, ('Formazione lavoratori' + (' — ' + fx if fx else ''))])
                elif senza_f: R['for'].append([cog, nom, cf, 'Formazione specifica', liv, None, 5, 'DATA DA INSERIRE; Formazione lavoratori — ' + fx])
                vv = g(iV); vd = dte(vv)
                if vd:
                    ma = re.search(r'(\d+)\s*ANN', vv.upper())
                    R['ido'].append([cog, nom, cf, vd, int(ma[1]) if ma else 1, ''])
            if len(dup_tab) >= 3: AVVISI.append(f'{ctx}: l\'elenco dipendenti è ripetuto due volte nel Word ({len(dup_tab)} nomi) — tenuto una volta sola')
            else:
                for n in dup_tab: AVVISI.append(f'{ctx}: {n} compare due volte nell\'elenco dipendenti — tenuto una volta')
            continue
        # ----- tabelle corsi (formato libero) -----
        if len(tb.columns) == 1: continue
        if re.search(r'(?i)visite mediche|rischi', (prime[ti] if ti < len(prime) else '')): continue
        if len(re.findall(r'(?i)posture|vibrazion|microclima|\bmmc\b|biologic|alcoo?l|rumore|\bvdt\b|rischio terzi|polveri', ' '.join(p for r in rows for c in r for p in c))) >= 2: continue
        if rows and re.search(r'(?i)\brischi\b|\bfasi\b', ' '.join(' '.join(c) for c in rows[0])) and not dip_tab: continue
        if any(len(p) > 120 or re.search(r'(?i)visite mediche\s*:', p) for r in rows for c in r for p in c): continue
        if re.search(r'(?i)legenda', (prime[ti] if ti < len(prime) else '')) or re.search(r'(?i)lavoratori (assunti|non)', ' '.join(' '.join(c) for r in rows for c in r)): continue
        tutto = ' '.join(p for r in rows for c in r for p in c)
        if not dte(re.sub(r'\(.*?\)', '', tutto)) and not any(e_corso(' '.join(r[0])) for r in rows if r): continue
        corso = ''; pend = []
        def nodata(nomi, cr, stato=''):
            if not nomi or not cr or len(cr) > 80: return
            nomi = [n for n in nomi if persona(n)]
            if not nomi: return
            AVVISI.append(f'{ctx}: corso "{cr}" di {", ".join(nomi)} senza data — inserito con la data da completare')
            for n in nomi:
                nota = ''; mm = re.search(r'\((.*?)\)', n)
                if mm: nota = mm[1]; n = clean(n[:mm.start()])
                n = clean(n.strip(' -–'))
                if n: R['for'].append(['@' + n, None, None, cr, '', None, None, '; '.join(x for x in ('DATA DA INSERIRE', stato, nota) if x)])
        for ri, r in enumerate(rows):
            txt = [' '.join(c) for c in r]
            if norm(' '.join(txt)).startswith('dipendenti') or not norm(' '.join(txt)): continue
            # celle ripetute dalle unioni di Word
            vistec = []; cel = []
            for j, c in enumerate(r):
                if j and c == r[j - 1] and c: continue
                cel.append(c)
            ds = []; tc = []
            for c in cel:
                t = ' '.join(c)
                if not t: continue
                x = dte(re.sub(r'\(.*?\)', '', t), f'{ctx} — {corso or txt[0]}')
                if x: ds.append(x)
                elif re.search(r'\d{1,2}[/.]\d{1,2}', re.sub(r'\(.*?\)', '', t)): continue
                elif re.fullmatch(r'(formazione|aggiornament\w*|aggformazione|nominativo|nominativi|nome|data|attestato|att|aggatt|svoltoil|corso)', norm(t)): continue
                elif re.match(r'(?i)^\(?\s*(in corso|fatto test|da fare|da chiudere|gi[aà].{0,2}lo tiene|test da chiudere|manca|non |da agg|online)', t): continue
                else: tc.append(c)
            def set_corso(t):
                nonlocal corso, prec
                t = clean(t)
                if re.fullmatch(r'(?i)(liv(ello)?\.?\s*\w+|basso|medio|alto)', t) and prec: t = prec + ' ' + t
                prec = re.sub(r'(?i)\s*(liv(ello)?\.?\s*\w+|basso|medio|alto)$', '', t) or prec
                corso = t
            if not ds:
                if not tc: continue
                first = ' '.join(tc[0])
                if ri == 0 or e_corso(first):
                    nodata(pend, corso); set_corso(first); pend = list(tc[1]) if len(tc) > 1 else []
                else:
                    stato = ' '.join(' '.join(c) for c in cel if c and c is not tc[0] and re.match(r'(?i)^\(?\s*(in corso|fatto test|da fare|da chiudere|gi[aà].{0,2}lo tiene|test da chiudere|manca|non |da agg|online)', ' '.join(c)))
                    nodata(tc[0], corso, stato)
                continue
            if len(tc) >= 2: set_corso(' '.join(tc[0])); nomi = tc[1]
            elif len(tc) == 1 and e_corso(' '.join(tc[0])) and pend: set_corso(' '.join(tc[0])); nomi = pend
            elif len(tc) == 1: nomi = tc[0]
            else: nomi = pend
            if nomi is pend or all(p in nomi for p in pend): pend = []
            if not corso: continue
            for n in nomi:
                nota = ''; mm = re.search(r'\((.*?)\)', n)
                if mm: nota = mm[1]; n = clean(n[:mm.start()])
                n = clean(n.strip(' -–'))
                ml = re.match(r'^(.*\S)\s+(ELEVATO|MEDIO|BASSO|ALTO)$', n)
                if ml and len(ml[1].split()) >= 2: n = ml[1]; nota = (nota + ' ' + ml[2].lower()).strip()
                if n: R['for'].append(['@' + n, None, None, corso, '', max(ds), None, nota])
        nodata(pend, corso)

    # classifica tutti i corsi trovati (tabelle e paragrafi)
    for f in R['for']:
        if str(f[0]).startswith('@'):
            f[3], f[4], f[6] = classifica(f[3], az.get('settore', ''))

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
            w = n.split()
            for cut in range(2, len(w) - 1):
                a1, b1 = chiave(' '.join(w[:cut])), chiave(' '.join(w[cut:]))
                if a1 in idx and b1 in idx:
                    R['for'].append(['@' + ' '.join(w[cut:])] + f[1:]); n = ' '.join(w[:cut]); k = a1
                    AVVISI.append(f'{ctx}: "{" ".join(w)}" diviso in due persone nel corso "{f[3]}"'); break
            simili = [x for x in idx if quasi(k, x)] or [x for x in idx if len(k.split()) >= 2 and set(k.split()) < set(x.split())]
            if len(simili) == 1:
                AVVISI.append(f'{ctx}: "{n}" nel corso "{f[3]}" associato a {" ".join(idx[simili[0]][:2])} (nome scritto in modo diverso)')
                k = simili[0]
        if k in idx:
            f[0], f[1], f[2] = idx[k]
            anno = re.search(r'\b(19|20)(\d\d)\b', f[7] or '')
            omon = [d0 for d0 in R['dip'] if chiave(d0[0] + ' ' + d0[1]) == k]
            if len(omon) > 1 and not anno:
                AVVISI.append(f'{ctx}: ci sono {len(omon)} dipendenti di nome {n}: il corso "{f[3]}" è stato assegnato a quello con codice fiscale {f[2]} — controlla che sia quello giusto')
            if anno:   # omonimi: "CASILLO GIUSEPPE (1983)" -> anno di nascita nel codice fiscale
                for a, b, cf, *_ in R['dip']:
                    if chiave(a + ' ' + b) == k and cf[6:8] == anno[2]: f[0], f[1], f[2] = a, b, cf; f[7] = ''
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
    import hashlib
    unici, hs = [], set()
    for p in docs:
        h = hashlib.md5(open(p, 'rb').read()).hexdigest()
        if h in hs: AVVISI.append(f'File Word duplicato (identico a un altro): {p.split("/")[-1]} — usato una volta sola'); continue
        hs.add(h); unici.append(p)
    letti = [leggi(p) for p in unici]
    nomi = [R['az']['nome'] for R in letti]
    riep = []
    for R in letti:
        a = R['az']
        if nomi.count(a['nome']) > 1:
            m = re.search(r'\d{5}\s*-?\s*([A-Z’\' .]+?)\s*\((\w\w)\)', a.get('so', '')) or re.search(r'\d{5}\s*-?\s*([A-Z’\' .]+?)\s*\((\w\w)\)', a.get('sl', ''))
            if m: a['nome'] = f"{a['nome']} - {clean(m[1])} ({m[2]})"
    nomi2 = [R['az']['nome'] for R in letti]
    for R in letti:
        a = R['az']
        if nomi2.count(a['nome']) > 1:
            via = clean(re.split(r'\s*[-–]\s*\d{5}', a.get('so', ''))[0])
            if via: a['nome'] = f"{a['nome'].split(' - ')[0]} - {via}"
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
