-- =====================================================================
-- SafeTrack 81 — configurazione database Supabase
-- Incolla TUTTO questo testo in Supabase > SQL Editor > New query > Run
-- (si può rieseguire senza problemi)
-- =====================================================================

-- ---------- TABELLE ----------
create table if not exists public.spazi (
  id         uuid primary key default gen_random_uuid(),
  nome       text not null,
  creato_da  uuid references auth.users(id) on delete set null,
  creato_il  timestamptz not null default now()
);

create table if not exists public.membri (
  spazio_id  uuid not null references public.spazi(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  ruolo      text not null default 'membro' check (ruolo in ('titolare','membro')),
  aggiunto_il timestamptz not null default now(),
  primary key (spazio_id, user_id)
);

create table if not exists public.aziende (
  spazio_id     uuid not null references public.spazi(id) on delete cascade,
  id            text not null,
  dati          jsonb not null,
  versione      integer not null default 1,
  aggiornato_il timestamptz not null default now(),
  aggiornato_da uuid,
  primary key (spazio_id, id)
);

create table if not exists public.backup (
  spazio_id  uuid not null references public.spazi(id) on delete cascade,
  giorno     date not null,
  dati       jsonb not null,
  primary key (spazio_id, giorno)
);

-- profilo e abbonamento di ogni utente registrato
create table if not exists public.profili (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  email         text,
  nome          text,
  azienda       text,
  telefono      text,
  piano         text,            -- es. Mensile, Annuale, Prova
  scadenza      date,            -- null = in attesa di attivazione
  admin         boolean not null default false,
  note          text,
  registrato_il timestamptz not null default now()
);

alter table public.aziende add column if not exists scadenze jsonb;           -- elenco scadenze calcolato dall'app
alter table public.profili add column if not exists avvisi_email boolean not null default true;
alter table public.profili add column if not exists cognome   text;
alter table public.profili add column if not exists piva      text;
alter table public.profili add column if not exists indirizzo text;
alter table public.profili add column if not exists cap       text;
alter table public.profili add column if not exists citta     text;
alter table public.profili add column if not exists provincia text;

-- crea il profilo in automatico a ogni nuova registrazione
create or replace function public.nuovo_utente() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profili (user_id, email, nome, cognome, azienda, piva, indirizzo, cap, citta, provincia, telefono)
  values (new.id, new.email, new.raw_user_meta_data->>'nome', new.raw_user_meta_data->>'cognome', new.raw_user_meta_data->>'azienda',
          new.raw_user_meta_data->>'piva', new.raw_user_meta_data->>'indirizzo', new.raw_user_meta_data->>'cap',
          new.raw_user_meta_data->>'citta', upper(new.raw_user_meta_data->>'provincia'), new.raw_user_meta_data->>'telefono')
  on conflict (user_id) do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.nuovo_utente();
-- utenti già esistenti
insert into public.profili (user_id, email) select id, email from auth.users on conflict (user_id) do nothing;

-- ---------- FUNZIONI DI CONTROLLO ----------
create or replace function public.is_membro(s uuid) returns boolean
language sql security definer stable set search_path = public as $$
  select exists (select 1 from public.membri where spazio_id = s and user_id = auth.uid());
$$;

create or replace function public.is_titolare(s uuid) returns boolean
language sql security definer stable set search_path = public as $$
  select exists (select 1 from public.membri where spazio_id = s and user_id = auth.uid() and ruolo = 'titolare');
$$;

create or replace function public.is_admin() returns boolean
language sql security definer stable set search_path = public as $$
  select coalesce((select admin from public.profili where user_id = auth.uid()), false);
$$;

-- uno spazio è attivo se il suo titolare è amministratore o ha un abbonamento non scaduto
create or replace function public.spazio_attivo(s uuid) returns boolean
language sql security definer stable set search_path = public as $$
  select exists (
    select 1 from public.membri m join public.profili p on p.user_id = m.user_id
    where m.spazio_id = s and m.ruolo = 'titolare'
      and (p.admin or (p.scadenza is not null and p.scadenza >= current_date))
  );
$$;

-- timbro automatico su chi/quando ha modificato
create or replace function public.timbra_azienda() returns trigger
language plpgsql set search_path = public as $$
begin
  new.aggiornato_il := now();
  new.aggiornato_da := auth.uid();
  return new;
end $$;
drop trigger if exists trg_timbra_azienda on public.aziende;
create trigger trg_timbra_azienda before insert or update on public.aziende
  for each row execute function public.timbra_azienda();

-- ---------- SICUREZZA: ognuno vede solo i propri spazi ----------
alter table public.spazi   enable row level security;
alter table public.membri  enable row level security;
alter table public.aziende enable row level security;
alter table public.backup  enable row level security;
alter table public.profili enable row level security;

drop policy if exists profili_leggi on public.profili;
create policy profili_leggi on public.profili for select to authenticated using (user_id = auth.uid() or public.is_admin());
-- nessuna policy di modifica: l'abbonamento lo cambia solo l'amministratore tramite funzione

drop policy if exists spazi_leggi on public.spazi;
create policy spazi_leggi on public.spazi for select to authenticated using (public.is_membro(id));

drop policy if exists membri_leggi on public.membri;
create policy membri_leggi on public.membri for select to authenticated using (public.is_membro(spazio_id));

drop policy if exists aziende_tutto on public.aziende;
create policy aziende_tutto on public.aziende for all to authenticated
  using (public.is_membro(spazio_id) and public.spazio_attivo(spazio_id))
  with check (public.is_membro(spazio_id) and public.spazio_attivo(spazio_id));

drop policy if exists backup_leggi on public.backup;
create policy backup_leggi on public.backup for select to authenticated using (public.is_membro(spazio_id) and public.spazio_attivo(spazio_id));
drop policy if exists backup_scrivi on public.backup;
create policy backup_scrivi on public.backup for insert to authenticated with check (public.is_membro(spazio_id) and public.spazio_attivo(spazio_id));
drop policy if exists backup_elimina on public.backup;
create policy backup_elimina on public.backup for delete to authenticated using (public.is_membro(spazio_id) and public.spazio_attivo(spazio_id));

-- ---------- FUNZIONI USATE DALL'APP ----------
drop function if exists public.miei_spazi();
create or replace function public.miei_spazi()
returns table (id uuid, nome text, ruolo text, attivo boolean, scadenza date)
language sql security definer stable set search_path = public as $$
  select s.id, s.nome, m.ruolo, public.spazio_attivo(s.id),
         (select p.scadenza from public.membri t join public.profili p on p.user_id = t.user_id
           where t.spazio_id = s.id and t.ruolo = 'titolare' limit 1)
  from public.membri m join public.spazi s on s.id = m.spazio_id
  where m.user_id = auth.uid()
  order by public.spazio_attivo(s.id) desc, (m.ruolo = 'titolare') desc, s.creato_il;
$$;

drop function if exists public.mio_stato();
create or replace function public.mio_stato()
returns table (email text, nome text, piano text, scadenza date, admin boolean, avvisi_email boolean)
language sql security definer stable set search_path = public as $$
  select p.email, p.nome, p.piano, p.scadenza, p.admin, p.avvisi_email from public.profili p where p.user_id = auth.uid();
$$;

create or replace function public.imposta_avvisi(attivi boolean)
returns void
language sql security definer set search_path = public as $$
  update public.profili set avvisi_email = attivi where user_id = auth.uid();
$$;

-- elenco utenti per il pannello amministratore
drop function if exists public.admin_lista_utenti();
create or replace function public.admin_lista_utenti()
returns table (user_id uuid, email text, nome text, cognome text, azienda text, piva text, indirizzo text, cap text, citta text, provincia text,
               telefono text, piano text, scadenza date, admin boolean, note text, registrato_il timestamptz, gestionali text, ultimo_accesso timestamptz)
language plpgsql security definer stable set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Solo l''amministratore'; end if;
  return query
    select p.user_id, coalesce(p.email, u.email::text), p.nome, p.cognome, p.azienda, p.piva, p.indirizzo, p.cap, p.citta, p.provincia,
           p.telefono, p.piano, p.scadenza, p.admin, p.note, p.registrato_il,
           (select string_agg(sp.nome || case when m.ruolo = 'titolare' then '' else ' (collega)' end, ', ')
              from public.membri m join public.spazi sp on sp.id = m.spazio_id where m.user_id = p.user_id),
           u.last_sign_in_at
    from public.profili p join auth.users u on u.id = p.user_id
    order by (p.scadenza is null) desc, p.registrato_il desc;
end $$;

create or replace function public.admin_imposta_abbonamento(u uuid, nuovo_piano text, nuova_scadenza date, nuove_note text)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'Solo l''amministratore'; end if;
  update public.profili set piano = nuovo_piano, scadenza = nuova_scadenza, note = nuove_note where user_id = u;
end $$;

-- il gestionale creato alla registrazione prende il nome dell'azienda del cliente
create or replace function public.crea_spazio_personale()
returns uuid
language plpgsql security definer set search_path = public as $$
declare sid uuid; nm text;
begin
  if auth.uid() is null then raise exception 'Non autenticato'; end if;
  select spazio_id into sid from public.membri where user_id = auth.uid() limit 1;
  if sid is not null then return sid; end if;
  select coalesce(nullif(trim(azienda), ''), 'Il mio gestionale') into nm from public.profili where user_id = auth.uid();
  insert into public.spazi (nome, creato_da) values (coalesce(nm, 'Il mio gestionale'), auth.uid()) returning id into sid;
  insert into public.membri (spazio_id, user_id, ruolo) values (sid, auth.uid(), 'titolare');
  return sid;
end $$;

create or replace function public.membri_spazio(s uuid)
returns table (user_id uuid, email text, ruolo text)
language plpgsql security definer stable set search_path = public as $$
begin
  if not public.is_membro(s) then raise exception 'Accesso negato'; end if;
  return query
    select m.user_id, u.email::text, m.ruolo
    from public.membri m join auth.users u on u.id = m.user_id
    where m.spazio_id = s
    order by (m.ruolo = 'titolare') desc, u.email;
end $$;

create or replace function public.aggiungi_membro(s uuid, email_utente text)
returns void
language plpgsql security definer set search_path = public as $$
declare uid uuid;
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare può aggiungere colleghi'; end if;
  if not public.spazio_attivo(s) then raise exception 'Abbonamento non attivo'; end if;
  select id into uid from auth.users where lower(email) = lower(trim(email_utente));
  if uid is null then raise exception 'Nessun utente con questa email. Il collega deve prima registrarsi dall''app.'; end if;
  insert into public.membri (spazio_id, user_id, ruolo) values (s, uid, 'membro') on conflict do nothing;
end $$;

create or replace function public.rimuovi_membro(s uuid, u uuid)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare può rimuovere colleghi'; end if;
  if u = auth.uid() then raise exception 'Non puoi rimuovere te stesso'; end if;
  delete from public.membri where spazio_id = s and user_id = u;
end $$;

create or replace function public.rinomina_spazio(s uuid, nuovo_nome text)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare può rinominare'; end if;
  if coalesce(trim(nuovo_nome), '') = '' then raise exception 'Nome non valido'; end if;
  update public.spazi set nome = trim(nuovo_nome) where id = s;
end $$;

revoke all on function public.miei_spazi()                    from public, anon;
revoke all on function public.mio_stato()                     from public, anon;
revoke all on function public.imposta_avvisi(boolean)         from public, anon;
revoke all on function public.admin_lista_utenti()            from public, anon;
revoke all on function public.admin_imposta_abbonamento(uuid, text, date, text) from public, anon;
revoke all on function public.crea_spazio_personale()         from public, anon;
revoke all on function public.membri_spazio(uuid)             from public, anon;
revoke all on function public.aggiungi_membro(uuid, text)     from public, anon;
revoke all on function public.rimuovi_membro(uuid, uuid)      from public, anon;
revoke all on function public.rinomina_spazio(uuid, text)     from public, anon;
grant execute on function public.miei_spazi()                 to authenticated;
grant execute on function public.mio_stato()                  to authenticated;
grant execute on function public.imposta_avvisi(boolean)      to authenticated;
grant execute on function public.admin_lista_utenti()         to authenticated;
grant execute on function public.admin_imposta_abbonamento(uuid, text, date, text) to authenticated;
grant execute on function public.crea_spazio_personale()      to authenticated;
grant execute on function public.membri_spazio(uuid)          to authenticated;
grant execute on function public.aggiungi_membro(uuid, text)  to authenticated;
grant execute on function public.rimuovi_membro(uuid, uuid)   to authenticated;
grant execute on function public.rinomina_spazio(uuid, text)  to authenticated;

-- ---------- INTESTAZIONE DI OGNI GESTIONALE (firma email, CC, documenti) ----------
alter table public.spazi add column if not exists intestazione jsonb;

-- intestazione salvata, oppure (se mai compilata) costruita dai dati di registrazione del titolare
create or replace function public.intestazione_spazio(s uuid)
returns jsonb
language plpgsql security definer stable set search_path = public as $$
declare j jsonb; p record;
begin
  if not public.is_membro(s) then raise exception 'Accesso negato'; end if;
  select intestazione into j from public.spazi where id = s;
  if j is not null then return j || jsonb_build_object('salvata', true); end if;
  select pr.* into p from public.membri m join public.profili pr on pr.user_id = m.user_id
   where m.spazio_id = s and m.ruolo = 'titolare' limit 1;
  return jsonb_build_object(
    'nome',      coalesce(nullif(p.azienda, ''), trim(coalesce(p.nome, '') || ' ' || coalesce(p.cognome, ''))),
    'referente', trim(coalesce(p.nome, '') || ' ' || coalesce(p.cognome, '')),
    'email',     p.email,
    'telefono',  p.telefono,
    'whatsapp',  p.telefono,
    'indirizzo', concat_ws(', ', nullif(p.indirizzo, ''), nullif(trim(concat_ws(' ', p.cap, p.citta, case when coalesce(p.provincia, '') <> '' then '(' || p.provincia || ')' end)), '')),
    'piva',      p.piva,
    'salvata',   false);
end $$;

create or replace function public.salva_intestazione(s uuid, dati jsonb)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare può modificare l''intestazione'; end if;
  update public.spazi set intestazione = (dati - 'salvata') where id = s;
end $$;

revoke all on function public.intestazione_spazio(uuid)        from public, anon;
revoke all on function public.salva_intestazione(uuid, jsonb)  from public, anon;
grant execute on function public.intestazione_spazio(uuid)       to authenticated;
grant execute on function public.salva_intestazione(uuid, jsonb) to authenticated;



-- ---------- AGGIORNAMENTO IN TEMPO REALE ----------
do $$ begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'aziende') then
    alter publication supabase_realtime add table public.aziende;
  end if;
end $$;

-- =====================================================================
-- AVVISI EMAIL SCADENZE (ogni mattina, tramite Brevo)
-- Ogni scadenza viene segnalata 3 volte: a 30 giorni, a 7 giorni e quando scade.
-- =====================================================================
create extension if not exists pg_net;
create extension if not exists pg_cron;

create table if not exists public.impostazioni (chiave text primary key, valore text);
alter table public.impostazioni enable row level security;          -- nessuna policy: non leggibile dall'app
revoke all on public.impostazioni from anon, authenticated;
insert into public.impostazioni (chiave, valore) values
  ('brevo_api_key',  'INSERISCI_CHIAVE_BREVO'),
  ('mittente_email', 'INSERISCI_EMAIL_MITTENTE'),
  ('mittente_nome',  'SafeTrack 81'),
  ('url_app',        'https://alfonso0310rgl.github.io/safetrack81/'),
  ('telegram_bot_token',    'INSERISCI_TOKEN_BOT'),
  ('telegram_bot_username', 'INSERISCI_NOME_BOT')
on conflict (chiave) do nothing;

-- collegamento di una chat/gruppo Telegram a ciascun gestionale
alter table public.spazi add column if not exists telegram_chat_id   text;
alter table public.spazi add column if not exists telegram_codice    text;
alter table public.spazi add column if not exists telegram_codice_il timestamptz;

create table if not exists public.avvisi_inviati (
  spazio_id  uuid not null references public.spazi(id) on delete cascade,
  chiave     text not null,
  soglia     integer not null,          -- 30, 7 oppure 0 (scaduta)
  inviato_il date not null default current_date,
  primary key (spazio_id, chiave, soglia)
);
alter table public.avvisi_inviati enable row level security;
revoke all on public.avvisi_inviati from anon, authenticated;

create or replace function public.st81_html(t text) returns text
language sql immutable as $$
  select replace(replace(replace(coalesce(t, ''), '&', '&amp;'), '<', '&lt;'), '>', '&gt;');
$$;

create or replace function public.st81_data(t text) returns date
language plpgsql immutable as $$
begin
  if t is null or t !~ '^\d{4}-\d{2}-\d{2}$' then return null; end if;
  return t::date;
exception when others then return null;
end $$;

create or replace function public.st81_email_configurata() returns boolean
language sql security definer stable set search_path = public as $$
  select exists (select 1 from public.impostazioni where chiave = 'brevo_api_key' and valore not like 'INSERISCI%' and coalesce(valore,'') <> '')
     and exists (select 1 from public.impostazioni where chiave = 'mittente_email' and valore not like 'INSERISCI%' and coalesce(valore,'') <> '');
$$;

create or replace function public.st81_invia_telegram(chat text, testo text) returns bigint
language plpgsql security definer set search_path = public, extensions as $$
declare tok text; rid bigint;
begin
  select valore into tok from public.impostazioni where chiave = 'telegram_bot_token';
  if tok is null or tok like 'INSERISCI%' or chat is null then return null; end if;
  select net.http_post(
    url     := 'https://api.telegram.org/bot' || tok || '/sendMessage',
    body    := jsonb_build_object('chat_id', chat, 'text', testo, 'parse_mode', 'HTML', 'disable_web_page_preview', true),
    headers := jsonb_build_object('Content-Type', 'application/json'),
    timeout_milliseconds := 15000
  ) into rid;
  return rid;
end $$;

-- legge i messaggi ricevuti dal bot per completare i collegamenti (/start CODICE); gira ogni minuto
create or replace function public.st81_telegram_poll() returns void
language plpgsql security definer set search_path = public, extensions as $$
declare
  tok text; req bigint; req_il timestamptz; off bigint; resp text; js jsonb; u jsonb; txt text; m text[]; sid uuid; chat text;
begin
  select valore into tok from public.impostazioni where chiave = 'telegram_bot_token';
  if tok is null or tok like 'INSERISCI%' then return; end if;
  select nullif(valore, '')::bigint into req from public.impostazioni where chiave = 'tg_req_id';
  select nullif(valore, '')::timestamptz into req_il from public.impostazioni where chiave = 'tg_req_il';
  select coalesce(nullif(valore, '')::bigint, 0) into off from public.impostazioni where chiave = 'tg_offset';
  if req is not null then
    perform 1 from net._http_response where id = req;
    if not found then
      if req_il is not null and req_il > now() - interval '10 minutes' then return; end if;  -- risposta ancora in arrivo
    else
      select content into resp from net._http_response where id = req;
      begin js := resp::jsonb; exception when others then js := null; end;
      if js is not null and coalesce((js->>'ok')::boolean, false) then
        for u in select * from jsonb_array_elements(js->'result') loop
          off := greatest(off, (u->>'update_id')::bigint + 1);
          txt  := coalesce(u->'message'->>'text', u->'channel_post'->>'text', '');
          chat := coalesce(u->'message'->'chat'->>'id', u->'channel_post'->'chat'->>'id');
          m := regexp_match(txt, '^/(start|collega)(@[A-Za-z0-9_]+)?\s+([A-Za-z0-9_-]+)');
          if m is not null and chat is not null then
            sid := null;
            update public.spazi set telegram_chat_id = chat, telegram_codice = null
              where telegram_codice = m[3] and telegram_codice_il > now() - interval '1 day'
              returning id into sid;
            if sid is not null then
              perform public.st81_invia_telegram(chat, '✅ <b>SafeTrack 81</b> collegato al gestionale <b>' ||
                public.st81_html((select nome from public.spazi where id = sid)) || '</b>.' || chr(10) ||
                'Qui riceverai ogni mattina gli avvisi delle scadenze (a 30 giorni, a 7 giorni e alla scadenza).');
            end if;
          end if;
        end loop;
      end if;
    end if;
    req := null;
  end if;
  insert into public.impostazioni values ('tg_offset', off::text) on conflict (chiave) do update set valore = excluded.valore;
  if exists (select 1 from public.spazi where telegram_codice is not null and telegram_codice_il > now() - interval '1 day') then
    select net.http_get(url := 'https://api.telegram.org/bot' || tok || '/getUpdates?timeout=0&offset=' || off) into req;
  end if;
  insert into public.impostazioni values ('tg_req_id', coalesce(req::text, '')) on conflict (chiave) do update set valore = excluded.valore;
  insert into public.impostazioni values ('tg_req_il', now()::text) on conflict (chiave) do update set valore = excluded.valore;
end $$;

-- funzioni per la schermata "Account e colleghi" (solo titolare)
create or replace function public.telegram_stato(s uuid)
returns table (collegato boolean, in_attesa boolean, bot text, configurato boolean)
language plpgsql security definer stable set search_path = public as $$
declare b text; t text;
begin
  if not public.is_membro(s) then raise exception 'Accesso negato'; end if;
  select valore into b from public.impostazioni where chiave = 'telegram_bot_username';
  select valore into t from public.impostazioni where chiave = 'telegram_bot_token';
  return query select sp.telegram_chat_id is not null,
                      sp.telegram_codice is not null and sp.telegram_codice_il > now() - interval '1 day',
                      case when b like 'INSERISCI%' then null else ltrim(b, '@') end,
                      (t is not null and t not like 'INSERISCI%' and b is not null and b not like 'INSERISCI%')
               from public.spazi sp where sp.id = s;
end $$;

create or replace function public.telegram_genera_codice(s uuid)
returns text
language plpgsql security definer set search_path = public as $$
declare c text;
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare può collegare Telegram'; end if;
  if not public.spazio_attivo(s) then raise exception 'Abbonamento non attivo'; end if;
  c := 'st' || substr(md5(random()::text || clock_timestamp()::text), 1, 12);
  update public.spazi set telegram_codice = c, telegram_codice_il = now() where id = s;
  return c;
end $$;

create or replace function public.telegram_scollega(s uuid)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare può scollegare Telegram'; end if;
  update public.spazi set telegram_chat_id = null, telegram_codice = null where id = s;
end $$;

create or replace function public.telegram_prova(s uuid)
returns void
language plpgsql security definer set search_path = public as $$
declare c text;
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare'; end if;
  select telegram_chat_id into c from public.spazi where id = s;
  if c is null then raise exception 'Telegram non collegato'; end if;
  perform public.st81_invia_telegram(c, '🛡️ <b>SafeTrack 81</b>' || chr(10) || '✅ Messaggio di prova: gli avvisi Telegram funzionano.');
end $$;

revoke all on function public.telegram_stato(uuid)         from public, anon;
revoke all on function public.telegram_genera_codice(uuid) from public, anon;
revoke all on function public.telegram_scollega(uuid)      from public, anon;
revoke all on function public.telegram_prova(uuid)         from public, anon;
grant execute on function public.telegram_stato(uuid)         to authenticated;
grant execute on function public.telegram_genera_codice(uuid) to authenticated;
grant execute on function public.telegram_scollega(uuid)      to authenticated;
grant execute on function public.telegram_prova(uuid)         to authenticated;

create or replace function public.st81_invia_email(destinatario text, oggetto text, html text) returns bigint
language plpgsql security definer set search_path = public, extensions as $$
declare k text; me text; mn text; rid bigint;
begin
  select valore into k  from public.impostazioni where chiave = 'brevo_api_key';
  select valore into me from public.impostazioni where chiave = 'mittente_email';
  select valore into mn from public.impostazioni where chiave = 'mittente_nome';
  if k is null or k like 'INSERISCI%' or me is null or me like 'INSERISCI%' then
    raise exception 'Configura brevo_api_key e mittente_email (vedi LEGGIMI, sezione avvisi email)';
  end if;
  select net.http_post(
    url     := 'https://api.brevo.com/v3/smtp/email',
    body    := jsonb_build_object(
                 'sender', jsonb_build_object('name', coalesce(mn, 'SafeTrack 81'), 'email', me),
                 'to', jsonb_build_array(jsonb_build_object('email', destinatario)),
                 'subject', oggetto,
                 'htmlContent', html),
    headers := jsonb_build_object('api-key', k, 'Content-Type', 'application/json', 'accept', 'application/json'),
    timeout_milliseconds := 15000
  ) into rid;
  return rid;
end $$;

-- email di prova:  select public.prova_email('tua@email.it');
create or replace function public.prova_email(destinatario text) returns bigint
language plpgsql security definer set search_path = public as $$
begin
  return public.st81_invia_email(destinatario, 'SafeTrack 81 — email di prova',
    '<div style="font-family:Arial,sans-serif;font-size:14px;">✅ Gli avvisi email di <strong>SafeTrack 81</strong> funzionano correttamente.</div>');
end $$;

create or replace function public.invia_avvisi_scadenze() returns integer
language plpgsql security definer set search_path = public as $$
declare
  sp record; r record; dest record;
  righe text; n integer; tot integer := 0; url text; col text; etich text; html text; ogg text;
  tg text; tg_extra integer; ico text; email_ok boolean := public.st81_email_configurata();
  td text := 'padding:8px 10px;border-bottom:1px solid #e5e7eb;font-size:13px;';
begin
  select valore into url from public.impostazioni where chiave = 'url_app';
  for sp in
    select s.id, s.nome, s.telegram_chat_id from public.spazi s
    where exists (select 1 from public.membri m join public.profili p on p.user_id = m.user_id
                  where m.spazio_id = s.id and m.ruolo = 'titolare'
                    and (p.admin or (p.scadenza is not null and p.scadenza >= current_date)))
  loop
    righe := ''; n := 0; tg := ''; tg_extra := 0;
    for r in
      with x as (
        select a.id as aid, a.dati->>'nome' as azienda, e->>'l' as voce, e->>'p' as persona,
               public.st81_data(e->>'d') as data
        from public.aziende a
        cross join lateral jsonb_array_elements(case when jsonb_typeof(a.scadenze) = 'array' then a.scadenze else '[]'::jsonb end) e
        where a.spazio_id = sp.id
      ), y as (
        select *, (data - current_date) as giorni,
               case when data < current_date then 0 when data - current_date <= 7 then 7 else 30 end as soglia,
               aid || '|' || coalesce(voce, '') || '|' || coalesce(persona, '') || '|' || data::text as chiave
        from x where data is not null and data - current_date between -30 and 30
      )
      select * from y
      where not exists (select 1 from public.avvisi_inviati v where v.spazio_id = sp.id and v.chiave = y.chiave and v.soglia = y.soglia)
      order by giorni, azienda
    loop
      n := n + 1;
      col := case when r.giorni < 0 then '#dc2626' when r.giorni <= 7 then '#ea580c' else '#b45309' end;
      etich := case when r.giorni < 0 then 'Scaduta da ' || abs(r.giorni) || ' gg'
                    when r.giorni = 0 then 'Scade oggi' when r.giorni = 1 then 'Scade domani'
                    else 'Tra ' || r.giorni || ' giorni' end;
      righe := righe || format('<tr><td style="%s"><strong>%s</strong></td><td style="%s">%s</td><td style="%s">%s</td><td style="%s">%s</td><td style="%scolor:%s;font-weight:700;">%s</td></tr>',
        td, public.st81_html(r.azienda), td, public.st81_html(r.voce), td, public.st81_html(coalesce(r.persona, '—')),
        td, to_char(r.data, 'DD/MM/YYYY'), td, col, etich);
      ico := case when r.giorni < 0 then '🔴' when r.giorni <= 7 then '🟠' else '🟡' end;
      if length(tg) < 3300 then
        tg := tg || ico || ' <b>' || public.st81_html(r.azienda) || '</b> — ' || public.st81_html(r.voce)
              || case when coalesce(r.persona, '') = '' then '' else ' · ' || public.st81_html(r.persona) end || chr(10) || '      ' || to_char(r.data, 'DD/MM/YYYY') || ' · ' || etich || chr(10);
      else
        tg_extra := tg_extra + 1;
      end if;
      insert into public.avvisi_inviati (spazio_id, chiave, soglia) values (sp.id, r.chiave, r.soglia) on conflict do nothing;
    end loop;

    if n > 0 then
      ogg := 'SafeTrack 81 — ' || n || case when n = 1 then ' scadenza' else ' scadenze' end || ' da controllare (' || sp.nome || ')';
      html := format('<div style="font-family:Arial,sans-serif;color:#111827;max-width:760px;">
        <div style="background:#2e231b;color:#fff;padding:16px 20px;border-radius:10px 10px 0 0;font-size:18px;font-weight:700;">🛡️ SafeTrack 81 — Avviso scadenze</div>
        <div style="padding:16px 20px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 10px 10px;">
        <p style="font-size:14px;margin:0 0 12px;">Nel gestionale <strong>%s</strong> ci sono %s nuove scadenze da controllare:</p>
        <table style="border-collapse:collapse;width:100%%;"><tr style="background:#f3f4f6;text-align:left;">
        <th style="%s">Azienda</th><th style="%s">Scadenza</th><th style="%s">Persona</th><th style="%s">Data</th><th style="%s">Stato</th></tr>%s</table>
        <p style="margin:18px 0 6px;"><a href="%s" style="background:#b8571d;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:700;font-size:14px;">Apri il gestionale</a></p>
        <p style="font-size:11px;color:#6b7280;margin-top:16px;">Ogni scadenza viene segnalata a 30 giorni, a 7 giorni e quando scade. Puoi disattivare queste email da ⚙️ Account e colleghi.</p>
        </div></div>', public.st81_html(sp.nome), n, td, td, td, td, td, righe, coalesce(url, '#'));
      if sp.telegram_chat_id is not null then
        perform public.st81_invia_telegram(sp.telegram_chat_id,
          '🛡️ <b>SafeTrack 81 — Scadenze</b>' || chr(10) || public.st81_html(sp.nome) || ': ' || n || case when n = 1 then ' nuova scadenza' else ' nuove scadenze' end || chr(10) || chr(10)
          || tg || case when tg_extra > 0 then '…e altre ' || tg_extra || chr(10) else '' end
          || chr(10) || '<a href="' || coalesce(url, '') || '">Apri il gestionale</a>');
      end if;
      if email_ok then
      for dest in
        select u.email from public.membri m
        join auth.users u on u.id = m.user_id
        join public.profili p on p.user_id = m.user_id
        where m.spazio_id = sp.id and p.avvisi_email and u.email is not null
      loop
        perform public.st81_invia_email(dest.email, ogg, html);
      end loop;
      end if;
      tot := tot + n;
    end if;
  end loop;
  delete from public.avvisi_inviati where inviato_il < current_date - 400;
  return tot;
end $$;

revoke all on function public.st81_invia_email(text, text, text) from public, anon, authenticated;
revoke all on function public.prova_email(text)                  from public, anon, authenticated;
revoke all on function public.invia_avvisi_scadenze()            from public, anon, authenticated;
revoke all on function public.st81_invia_telegram(text, text)    from public, anon, authenticated;
revoke all on function public.st81_telegram_poll()               from public, anon, authenticated;
revoke all on function public.st81_email_configurata()           from public, anon, authenticated;

-- ogni giorno alle 6:00 UTC (7:00 ora solare, 8:00 ora legale)
do $$ begin
  if exists (select 1 from cron.job where jobname = 'st81-avvisi-scadenze') then
    perform cron.unschedule('st81-avvisi-scadenze');
  end if;
  perform cron.schedule('st81-avvisi-scadenze', '0 6 * * *', 'select public.invia_avvisi_scadenze()');
  if exists (select 1 from cron.job where jobname = 'st81-telegram-collega') then
    perform cron.unschedule('st81-telegram-collega');
  end if;
  perform cron.schedule('st81-telegram-collega', '* * * * *', 'select public.st81_telegram_poll()');
end $$;

-- =====================================================================
-- INVIO AUTOMATICO ALLE AZIENDE (riepilogo scadenze 30 giorni prima)
-- =====================================================================
alter table public.spazi add column if not exists invio_aziende boolean not null default false;

create table if not exists public.avvisi_aziende (
  spazio_id  uuid not null references public.spazi(id) on delete cascade,
  azienda_id text not null,
  chiave     text not null,
  inviato_il date not null default current_date,
  primary key (spazio_id, azienda_id, chiave)
);
alter table public.avvisi_aziende enable row level security;
revoke all on public.avvisi_aziende from anon, authenticated;

create table if not exists public.invii_aziende (
  id          bigserial primary key,
  spazio_id   uuid not null references public.spazi(id) on delete cascade,
  azienda_id  text not null,
  destinatario text,
  n_scadenze  integer,
  richiesta   bigint,
  inviato_il  timestamptz not null default now()
);
alter table public.invii_aziende enable row level security;
revoke all on public.invii_aziende from anon, authenticated;

-- intestazione senza controllo di accesso (uso interno)
create or replace function public.st81_intestazione(s uuid)
returns jsonb
language plpgsql security definer stable set search_path = public as $$
declare j jsonb; p record;
begin
  select intestazione into j from public.spazi where id = s;
  if j is not null then return j || jsonb_build_object('salvata', true); end if;
  select pr.* into p from public.membri m join public.profili pr on pr.user_id = m.user_id
   where m.spazio_id = s and m.ruolo = 'titolare' limit 1;
  return jsonb_build_object(
    'nome',      coalesce(nullif(p.azienda, ''), trim(coalesce(p.nome, '') || ' ' || coalesce(p.cognome, ''))),
    'referente', trim(coalesce(p.nome, '') || ' ' || coalesce(p.cognome, '')),
    'email',     p.email,
    'telefono',  p.telefono,
    'whatsapp',  p.telefono,
    'indirizzo', concat_ws(', ', nullif(p.indirizzo, ''), nullif(trim(concat_ws(' ', p.cap, p.citta, case when coalesce(p.provincia, '') <> '' then '(' || p.provincia || ')' end)), '')),
    'piva',      p.piva,
    'salvata',   false);
end $$;

create or replace function public.intestazione_spazio(s uuid)
returns jsonb
language plpgsql security definer stable set search_path = public as $$
begin
  if not public.is_membro(s) then raise exception 'Accesso negato'; end if;
  return public.st81_intestazione(s);
end $$;

create or replace function public.st81_invia_email_az(destinatario text, cc text, rispondi_a text, nome_mittente text, oggetto text, html text)
returns bigint
language plpgsql security definer set search_path = public, extensions as $$
declare k text; me text; rid bigint; body jsonb;
begin
  select valore into k  from public.impostazioni where chiave = 'brevo_api_key';
  select valore into me from public.impostazioni where chiave = 'mittente_email';
  if not public.st81_email_configurata() then return null; end if;
  body := jsonb_build_object(
    'sender', jsonb_build_object('name', left(coalesce(nullif(nome_mittente, ''), 'SafeTrack 81'), 70), 'email', me),
    'to', jsonb_build_array(jsonb_build_object('email', destinatario)),
    'subject', oggetto, 'htmlContent', html);
  if coalesce(rispondi_a, '') ~ '^\S+@\S+\.\S+$' then
    body := body || jsonb_build_object('replyTo', jsonb_build_object('email', rispondi_a, 'name', left(coalesce(nome_mittente, ''), 70)));
    if lower(rispondi_a) <> lower(destinatario) and coalesce(cc, '') ~ '^\S+@\S+\.\S+$' then
      body := body || jsonb_build_object('cc', jsonb_build_array(jsonb_build_object('email', cc)));
    end if;
  end if;
  select net.http_post(
    url := 'https://api.brevo.com/v3/smtp/email', body := body,
    headers := jsonb_build_object('api-key', k, 'Content-Type', 'application/json', 'accept', 'application/json'),
    timeout_milliseconds := 15000) into rid;
  return rid;
end $$;

create or replace function public.st81_rinnovo(anni text) returns text
language sql immutable as $$
  select case nullif(regexp_replace(coalesce(anni, ''), '\D', '', 'g'), '')::int
    when 1 then 'Aggiornamento Annuale' when 2 then 'Aggiornamento Biennale' when 3 then 'Aggiornamento Triennale'
    when 4 then 'Aggiornamento Quadriennale' when 5 then 'Aggiornamento Quinquennale'
    else case when nullif(regexp_replace(coalesce(anni, ''), '\D', '', 'g'), '') is null or nullif(regexp_replace(coalesce(anni, ''), '\D', '', 'g'), '')::int = 0 then null
              else 'Aggiornamento ogni ' || regexp_replace(anni, '\D', '', 'g') || ' anni' end end;
$$;

-- invio giornaliero: un'email per azienda quando una scadenza entra nei 30 giorni (o è scaduta e non ancora segnalata)
create or replace function public.invia_avvisi_aziende() returns integer
language plpgsql security definer set search_path = public as $$
declare
  sp record; az record; r record; it jsonb; tot integer := 0; n integer; nuovi integer;
  righe text; html text; ogg text; mitt text; wa text; tel text; em text; contatto text; canale text; firma text; rid bigint; p text := '<p style="margin:0 0 4px 0;">';
begin
  if not public.st81_email_configurata() then return 0; end if;
  for sp in
    select s.id from public.spazi s
    where s.invio_aziende
      and exists (select 1 from public.membri m join public.profili pr on pr.user_id = m.user_id
                  where m.spazio_id = s.id and m.ruolo = 'titolare'
                    and (pr.admin or (pr.scadenza is not null and pr.scadenza >= current_date)))
  loop
    it := public.st81_intestazione(sp.id);
    mitt := coalesce(nullif(it->>'nome', ''), 'Il tuo consulente per la sicurezza');
    wa := trim(coalesce(it->>'whatsapp', '')); tel := trim(coalesce(it->>'telefono', '')); em := trim(coalesce(it->>'email', ''));
    contatto := case when wa <> '' then ' oppure contattarci su WhatsApp al <strong>' || st81_html(wa) || '</strong>'
                     when tel <> '' then ' oppure telefonarci al <strong>' || st81_html(tel) || '</strong>' else '' end;
    canale := case when wa <> '' then 'sempre via email o WhatsApp' when tel <> '' then 'sempre via email o telefono' else 'sempre via email' end;
    firma := p || 'Cordiali saluti</p>' || p || '<strong>' || st81_html(mitt) || '</strong></p>'
      || case when coalesce(it->>'referente', '') not in ('', mitt) then p || st81_html(it->>'referente') || '</p>' else '' end
      || case when em <> '' then p || 'Email: ' || st81_html(em) || '</p>' else '' end
      || case when tel <> '' then p || 'Tel: ' || st81_html(tel) || '</p>' else '' end
      || case when wa <> '' and wa <> tel then p || 'WhatsApp: ' || st81_html(wa) || '</p>' else '' end
      || case when coalesce(it->>'indirizzo', '') <> '' then p || st81_html(it->>'indirizzo') || '</p>' else '' end
      || case when coalesce(it->>'piva', '') <> '' then p || 'P.IVA ' || st81_html(it->>'piva') || '</p>' else '' end;

    for az in
      select a.id, a.dati->>'nome' as nome, trim(a.dati->>'email') as email, a.scadenze
      from public.aziende a
      where a.spazio_id = sp.id
        and coalesce(a.dati->>'email', '') ~ '^\s*\S+@\S+\.\S+\s*$'
        and coalesce(a.dati->>'avvisoAutoEmail', 'true') <> 'false'
        and jsonb_typeof(a.scadenze) = 'array'
    loop
      righe := ''; n := 0; nuovi := 0;
      for r in
        select e->>'l' as voce, e->>'p' as persona, e->>'a' as anni, public.st81_data(e->>'d') as data,
               az.id || '|' || coalesce(e->>'l', '') || '|' || coalesce(e->>'p', '') || '|' || coalesce(e->>'d', '') as chiave
        from jsonb_array_elements(az.scadenze) e
        where public.st81_data(e->>'d') is not null and public.st81_data(e->>'d') - current_date <= 30
        order by public.st81_data(e->>'d')
      loop
        n := n + 1;
        righe := righe || '<div style="margin-bottom:18px;">' || p || '- <strong>' || st81_html(r.voce)
          || case when coalesce(r.persona, '') <> '' then ' — ' || st81_html(r.persona) else '' end || '</strong></p>'
          || p || '<strong>SCADENZA: ' || to_char(r.data, 'DD/MM/YYYY') || '</strong></p>'
          || coalesce(p || '<strong>' || public.st81_rinnovo(r.anni) || '</strong></p>', '') || '</div>';
        if r.data - current_date >= -30 and not exists (select 1 from public.avvisi_aziende v where v.spazio_id = sp.id and v.azienda_id = az.id and v.chiave = r.chiave) then
          nuovi := nuovi + 1;
          insert into public.avvisi_aziende (spazio_id, azienda_id, chiave) values (sp.id, az.id, r.chiave) on conflict do nothing;
        end if;
      end loop;
      if nuovi > 0 then
        ogg := 'Riepilogo Scadenze D.Lgs. 81/08 — ' || az.nome;
        html := '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#2b2119;max-width:680px;">'
          || '<p style="margin:0 0 16px 0;">Gentile <strong>' || st81_html(az.nome) || '</strong>,</p>'
          || '<p style="margin:0 0 16px 0;">di seguito il riepilogo dei documenti in scadenza nel prossimo mese. Ti invitiamo a prendere visione e a contattarci per pianificare il rinnovo.</p>'
          || '<p style="margin:0 0 10px 0;"><strong>Documenti in scadenza:</strong></p>' || righe
          || '<p style="margin:0 0 10px 0;"><strong>Come procedere all''aggiornamento:</strong></p>'
          || '<p style="margin:0 0 6px 0;"><strong>1. Rinnovo e aggiornamento scadenze</strong></p>'
          || '<p style="margin:0 0 16px 0;">Per procedere al rinnovo di uno o più documenti in scadenza, è sufficiente rispondere direttamente a questa email' || contatto || '. Provvederemo a organizzare tutto il necessario nel più breve tempo possibile.</p>'
          || '<p style="margin:0 0 6px 0;"><strong>2. Variazioni aziendali</strong></p>'
          || '<p style="margin:0 0 16px 0;">In caso di cambiamenti in azienda — quali nuove assunzioni, cambi di mansione, modifiche organizzative o acquisto di nuovi macchinari/attrezzature — Vi chiediamo di aggiornarci tempestivamente, ' || canale || '. Queste informazioni sono essenziali per mantenere la documentazione conforme al D.lgs. 81/08 e garantire la tutela di tutti i lavoratori.</p>'
          || firma || '</div>';
        rid := public.st81_invia_email_az(az.email, em, em, mitt, ogg, html);
        insert into public.invii_aziende (spazio_id, azienda_id, destinatario, n_scadenze, richiesta) values (sp.id, az.id, az.email, n, rid);
        tot := tot + 1;
      end if;
    end loop;
  end loop;
  delete from public.avvisi_aziende where inviato_il < current_date - 800;
  return tot;
end $$;

-- funzioni per l'app
create or replace function public.imposta_invio_aziende(s uuid, attivo boolean)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_titolare(s) then raise exception 'Solo il titolare può cambiare questa impostazione'; end if;
  update public.spazi set invio_aziende = attivo where id = s;
end $$;

create or replace function public.stato_invio_aziende(s uuid)
returns table (attivo boolean, email_ok boolean)
language plpgsql security definer stable set search_path = public as $$
begin
  if not public.is_membro(s) then raise exception 'Accesso negato'; end if;
  return query select sp.invio_aziende, public.st81_email_configurata() from public.spazi sp where sp.id = s;
end $$;

create or replace function public.ultimi_invii_aziende(s uuid)
returns table (azienda_id text, inviato_il timestamptz, destinatario text, n_scadenze integer)
language plpgsql security definer stable set search_path = public as $$
begin
  if not public.is_membro(s) then raise exception 'Accesso negato'; end if;
  return query select distinct on (i.azienda_id) i.azienda_id, i.inviato_il, i.destinatario, i.n_scadenze
    from public.invii_aziende i where i.spazio_id = s order by i.azienda_id, i.inviato_il desc;
end $$;

revoke all on function public.st81_intestazione(uuid) from public, anon, authenticated;
revoke all on function public.st81_invia_email_az(text, text, text, text, text, text) from public, anon, authenticated;
revoke all on function public.invia_avvisi_aziende() from public, anon, authenticated;
revoke all on function public.imposta_invio_aziende(uuid, boolean) from public, anon;
revoke all on function public.stato_invio_aziende(uuid) from public, anon;
revoke all on function public.ultimi_invii_aziende(uuid) from public, anon;
grant execute on function public.imposta_invio_aziende(uuid, boolean) to authenticated;
grant execute on function public.stato_invio_aziende(uuid) to authenticated;
grant execute on function public.ultimi_invii_aziende(uuid) to authenticated;

-- ogni giorno alle 6:05 UTC (7:05 ora solare)
do $$ begin
  if exists (select 1 from cron.job where jobname = 'st81-avvisi-aziende') then perform cron.unschedule('st81-avvisi-aziende'); end if;
  perform cron.schedule('st81-avvisi-aziende', '5 6 * * *', 'select public.invia_avvisi_aziende()');
end $$;

-- =====================================================================
-- ULTIMO PASSO: dopo esserti registrato dall'app, rendi amministratore il tuo account.
-- Sostituisci l'email e riesegui SOLO questa riga:
-- update public.profili set admin = true where email = 'la-tua-email@esempio.it';
-- =====================================================================
