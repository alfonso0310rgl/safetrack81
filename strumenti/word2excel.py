"""Converte i Word 'AGGIORNAMENTI DOCUMENTAZIONE' nel modello di importazione SafeTrack 81.
Uso: python3 word2excel.py output.xlsx file1.docx [file2.docx ...]"""
import sys,re,datetime as dt,docx,openpyxl,unicodedata
TPL='/home/claude/safetrack81/modello_importazione.xlsx'
DATE=r'(\d{1,2})[/.](\d{1,2})[/.](\d{4})'
def dte(s):
    s=s or ''; m=re.search(r'(\d{1,2})-(\d{1,2})/(\d{1,2})/(\d{4})',s)   # 10-11/01/2023 -> ultimo giorno
    if m: return dt.date(int(m[4]),int(m[3]),int(m[2]))
    m=re.search(DATE,s); return dt.date(int(m[3]),int(m[2]),int(m[1])) if m else None
def norm(s): return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFD',s.lower()).encode('ascii','ignore').decode())
def clean(s): return re.sub(r'\s+',' ',(s or '').replace('\xa0',' ')).strip()
def leggi(path,avvisi):
    d=docx.Document(path); R={'az':{},'dip':[],'fig':[],'doc':[],'for':[],'ido':[]}
    righe=[clean(p.text) for p in d.paragraphs if clean(p.text)]
    az=R['az']; az['nome']=righe[0]; ateco=[]
    prep={}; rls={}; dvr=[]
    for t in righe[1:]:
        lab,_,rest=t.partition(':'); L=norm(lab); rest=clean(rest)
        m=re.match(r'^(.*?)\s*[–-]\s*'+DATE+r'\s*$',rest); nome=clean(m[1]) if m else ''; data=dte(rest)
        if L.startswith('ateco'): ateco.append(rest)
        elif L=='sedelegale': az['sl']=rest
        elif L=='sedeoperativa': az['so']=rest
        elif L.startswith('amministratore'): az['ref']='Amministratore: '+rest
        elif L=='nominarspp': R['fig'].append(['RSPP',nome,data,None,None])
        elif 'preposto' in L and m:
            p=prep.setdefault(norm(nome),{'nome':nome,'nom':None,'att':None})
            if L.startswith('nomina'): p['nom']=data
            else: p['att']=max(filter(None,[p['att'],data]))
        elif 'rls' in L and m:
            r=rls.setdefault(norm(nome),{'nome':nome,'nom':None,'att':None})
            if L.startswith('elezione'): r['nom']=data
            else: r['att']=max(filter(None,[r['att'],data]))
        elif 'medicocompetente' in L: R['fig'].append(['Medico competente',nome,data,None,None])
        elif L.startswith('dvr'): mr=re.search(r'(?i)rev\.?\s*[:n°]*\s*(\d+)',t); dvr.append((data,'Rev. '+mr[1] if mr else ''))
        elif 'riunioneperiodica' in L and data: R['doc'].append(['Verbale Riunione Periodica',data,None,None])
        elif 'evacuazione' in L and data: R['doc'].append(['Verbale Prova Evacuazione',data,None,None])
        elif data and not m and len(lab)<80 and not L.startswith('visit'): R['doc'].append([clean(lab).title(),data,None,None])
    az['settore']='; '.join(ateco)
    for p in prep.values(): R['fig'].append(['Preposto',p['nome'],p['nom'],p['att'],2])
    for r in rls.values(): R['fig'].append(['RLS',r['nome'],r['nom'],r['att'],1])
    if dvr:
        data,rev=max(dvr,key=lambda x:x[0] or dt.date.min); R['doc'].insert(0,['DVR',data,None,rev])
    for t in d.tables:
        rows=[[ [clean(p.text) for p in c.paragraphs if clean(p.text)] for c in r.cells] for r in t.rows]
        head=[norm(' '.join(c)) for c in rows[0]]
        if any('nominativo' in h for h in head):
            col=lambda k:next((i for i,h in enumerate(head) if k in h),None)
            iN,iCF,iDN,iLN,iDA,iM,iF,iI,iD=[col(k) for k in ['nominativo','codicefisc','datadinascita','luogodinascita','dataassunzione','mansione','formazione','informazione','dpi']]
            g=lambda r,i:(' '.join(r[i]) if i is not None and i<len(r) else '')
            for r in rows[1:]:
                n=clean(g(r,iN))
                if not n: continue
                parti=n.split(); cog,nom=' '.join(parti[:-1]),parti[-1]
                cf=clean(g(r,iCF)).upper()
                if cf and not re.fullmatch(r'[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]',cf): avvisi.append(f'{az["nome"]}: codice fiscale da controllare per {n} ({cf})')
                note=[]
                if g(r,iDN) or g(r,iLN): note.append('Nato il '+clean(g(r,iDN))+(' a '+clean(g(r,iLN)) if g(r,iLN) else ''))
                if dte(g(r,iI)): note.append('Informazione: '+clean(g(r,iI)))
                if dte(g(r,iD)): note.append('Consegna DPI: '+clean(g(r,iD)))
                R['dip'].append([cog,nom,cf,clean(g(r,iM)),dte(g(r,iDA)),'SI','; '.join(note)])
                if dte(g(r,iF)): R['for'].append([cog,nom,cf,'Formazione specifica','Rischio alto',dte(g(r,iF)),5,'Formazione lavoratori (generale + specifica)'])
        elif len(rows[0])>=3:
            for r in rows:
                corso,nomi,data=' '.join(r[0]),r[1],dte(' '.join(r[2]))
                if not nomi or not data: continue
                c=norm(corso)
                if 'antincendio' in c:
                    lv=re.search(r'(?i)livello\s*(i{1,3}|[123])',corso); lvl='Livello '+(lv[1].upper() if lv else 'I'); tipo,anni='Antincendio',5
                elif 'primosoccorso' in c: tipo,anni='Primo soccorso',3; lvl='Gruppo A' if re.search(r'gruppo\s*a\b',corso,re.I) or re.match(r'0[5-9]',az.get('settore','')) else ('Gruppo B/C' if re.search(r'gruppo\s*[bc]',corso,re.I) else '')
                else: tipo,lvl,anni=clean(corso),'',5
                for n in nomi:
                    nota=''; mm=re.search(r'\((.*?)\)',n)
                    if mm: nota=mm[1]; n=clean(n[:mm.start()])
                    R['for'].append(['@'+n,None,None,tipo,lvl,data,anni,nota])
    # collega i nomi dei corsi ai dipendenti (cognome/nome esatti)
    idx={norm(a+b):(a,b,cf) for a,b,cf,*_ in R['dip']}
    for f in R['for']:
        if str(f[0]).startswith('@'):
            n=f[0][1:]; k=norm(n)
            if k in idx: f[0],f[1],f[2]=idx[k]
            else:
                p=n.split(); f[0],f[1]=' '.join(p[:-1]),p[-1]; avvisi.append(f'{az["nome"]}: {n} ha il corso "{f[3]}" ma non è nell\'elenco dipendenti (verrà creato)')
    return R
def scrivi(out,docs):
    wb=openpyxl.load_workbook(TPL); avvisi=[]; nxt={}
    def put(sh,vals):
        ws=wb[sh]; r=nxt.get(sh,3); nxt[sh]=r+1
        for j,v in enumerate(vals,1):
            if v is not None and v!='': ws.cell(r,j,v)
    for p in docs:
        R=leggi(p,avvisi); a=R['az']; N=a['nome']
        put('Aziende',[N,None,a.get('settore'),None,a.get('ref'),a.get('sl'),a.get('so'),None])
        for r in R['dip']: put('Dipendenti',[N]+r)
        for ru,nome,dn,da,anni in R['fig']: put('Figure',[N,ru,nome,dn,None,None,da,anni if da else None,None,None])
        for nome,data,anni,rev in R['doc']: put('Documenti',[N,nome,data,anni,None,rev,None])
        for f in R['for']: put('Formazione',[N]+f[:6]+[f[6],None,f[7]])
        print(N,{k:len(v) for k,v in R.items() if k!='az'})
    wb.save(out); return avvisi
if __name__=='__main__':
    for a in scrivi(sys.argv[1],sys.argv[2:]): print('AVVISO',a)
