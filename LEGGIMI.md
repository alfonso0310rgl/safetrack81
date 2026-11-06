# SafeTrack 81 — messa online (circa 15 minuti, una volta sola)

Il programma è composto da 3 file:
- `index.html`: il gestionale
- `config.js`: indirizzo e chiave del tuo database (da compilare al punto 3)
- `supabase_setup.sql`: crea il database (si usa una sola volta, al punto 1)

Come funziona:
- Il cliente apre il sito, preme **Registrati** e crea il suo account.
- L'account resta **in attesa** finché non lo attivi tu dal pannello **👑 Clienti e abbonamenti**, scegliendo il piano e la scadenza.
- Alla scadenza l'accesso si blocca da solo. I dati del cliente restano conservati e ricompaiono appena rinnovi.
- Ogni cliente ha il suo gestionale, invisibile agli altri. Può aggiungere colleghi, che lavorano sugli stessi dati in tempo reale.

---

## 1. Crea il database (Supabase, gratuito)
1. Vai su https://supabase.com, registrati e premi **New project**.
   - Region: **Central EU (Frankfurt)**, così i dati restano in Europa.
   - Annota la password del database, anche se l'app non la usa.
2. Quando il progetto è pronto, apri **SQL Editor → New query**.
3. Incolla tutto il contenuto di `supabase_setup.sql` e premi **Run**. Deve comparire "Success".

## 2. Imposta gli accessi
1. **Authentication → Sign In / Providers → Email**:
   - lascia attivo **Allow new users to sign up**, così i clienti possono registrarsi;
   - disattiva **Confirm email**: il cliente entra subito e vede la schermata "in attesa di attivazione". Gli account falsi non ottengono comunque accesso finché non li attivi tu. Il servizio email gratuito di Supabase, inoltre, invia pochissime email l'ora.

## 3. Collega l'app al database
1. **Project Settings → API** (oppure **Data API / API Keys**): copia **Project URL** e la chiave **anon public** (o **publishable**).
2. Apri `config.js` e:
   - sostituisci i due testi `INSERISCI_…` con i valori copiati;
   - controlla email e telefono di contatto, che vengono mostrati ai clienti in attesa o scaduti;
   - se hai un'informativa privacy online, mettine il link in `PRIVACY_URL`.

## 4. Pubblica il sito (GitHub Pages, gratuito)
1. Registrati su https://github.com e premi **New repository**.
   - Nome: `safetrack81`. Visibilità: **Public** (il codice è visibile, i dati no).
2. Nella pagina del repository premi **uploading an existing file**, trascina i 3 file e premi **Commit changes**.
3. Vai in **Settings → Pages**:
   - Source: **Deploy from a branch**
   - Branch: **main**, cartella **/ (root)**
   - premi **Save**.
4. Dopo 1–2 minuti il sito è online su `https://TUONOME.github.io/safetrack81/`.
5. Torna su Supabase, **Authentication → URL Configuration**, e incolla questo indirizzo in **Site URL**. Serve per il link "Password dimenticata".

## 5. Diventa amministratore
1. Apri il sito e **registrati** con la tua email.
2. In Supabase, **SQL Editor**, esegui questa riga con la tua email:
   `update public.profili set admin = true where email = 'la-tua-email@esempio.it';`
3. Premi **🔄 Ricontrolla**. Entri senza scadenza e nella barra a sinistra compare **👑 Clienti e abbonamenti**.
4. Per caricare le aziende che hai già, usa **📤 Importa**. Puoi scegliere:
   - un file salvato con **📥 Esporta** dalla versione vecchia;
   - un file `backup_AAAA-MM-GG.json` della cartella `SafeTrack81_Dati/backup`.

## 6. Gestire clienti e abbonamenti
- **👑 Clienti e abbonamenti** elenca tutti gli iscritti con nome, azienda, telefono e data di registrazione. Il numero rosso indica quanti sono in attesa.
- **+1 mese / +1 anno**: attiva o rinnova. Se l'abbonamento è ancora valido, il periodo si aggiunge alla scadenza attuale, così il cliente non perde giorni.
- **Salva**: imposta piano, data e note a mano (es. "pagato con bonifico il…"). Va bene anche per una prova gratuita.
- **Sospendi**: blocca subito l'accesso, i dati restano conservati.
- Il cliente vede un avviso nei 15 giorni prima della scadenza.
- **Colleghi**:
  - del tuo studio: si registrano e tu li aggiungi da **⚙️ Account e colleghi**. Non serve attivarli, perché usano il tuo gestionale;
  - di un cliente: li aggiunge il cliente stesso, e sono coperti dal suo abbonamento.

## 7. Aggiornamenti futuri
- Collega GitHub nelle impostazioni di Claude e indica il nome del repository: le modifiche vengono pubblicate direttamente e il sito si aggiorna da solo in circa un minuto.
- In alternativa: carica di nuovo `index.html` su GitHub con **Add file → Upload files**.

## Da sapere
- **Backup automatico**: ogni giorno viene salvata una copia nel database (tabella `backup`) e vengono tenuti gli ultimi 30 giorni. Puoi sempre fare anche **📥 Esporta**.
- **Piano gratuito di Supabase**: il progetto va in pausa se nessuno lo usa per 7 giorni. Si riattiva dalla dashboard con **Restore**. Con l'uso quotidiano non succede.
- **Privacy**: il gestionale contiene dati dei lavoratori, comprese le idoneità mediche. Tieni la regione UE e valuta di accettare il DPA di Supabase (GDPR) dalle impostazioni dell'organizzazione.
