-- =====================================================================
-- Central de Notas – estrutura do banco (rodar UMA vez no SQL Editor do Supabase)
-- =====================================================================

-- ---------- Perfis e papéis ----------
create table if not exists public.perfis (
  id            uuid primary key references auth.users(id) on delete cascade,
  nome          text not null default '',
  email         text not null default '',
  papel         text not null default 'analista' check (papel in ('analista','aprovador','admin')),
  trocar_senha  boolean not null default true,
  criado_em     timestamptz not null default now()
);

-- Cria o perfil automaticamente quando um usuário é criado em Authentication.
-- Papéis iniciais: Robson = aprovador, Renan = admin, demais = analista.
create or replace function public.criar_perfil() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.perfis (id, nome, email, papel)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'nome', split_part(new.email, '@', 1)),
    new.email,
    case lower(new.email)
      when 'rbastos@commcenter.com.br'   then 'aprovador'
      when 'refreitas@commcenter.com.br' then 'admin'
      else 'analista'
    end
  )
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists ao_criar_usuario on auth.users;
create trigger ao_criar_usuario after insert on auth.users
  for each row execute function public.criar_perfil();

create or replace function public.meu_papel() returns text
language sql stable security definer set search_path = public as $$
  select papel from public.perfis where id = auth.uid()
$$;

-- ---------- Cadastros vindos da planilha ----------
create table if not exists public.filiais (
  cnpj     text primary key,
  empresa  text not null,
  filial   text not null
);

create table if not exists public.fornecedores (
  cnpj     text primary key,
  apelido  text not null,
  razao    text not null default '',
  codigos  jsonb not null default '{}'::jsonb   -- {"VMT":"ZERDG2","AXT":"10H7Q5","*":"..."}
);

create table if not exists public.historico (
  id              bigserial primary key,
  data_ref        date,
  origem          text not null default 'planilha',
  nota_id         bigint,
  despesa         text default '', empresa text default '', prestador text default '',
  descricao       text default '', filial  text default '', produto   text default '',
  cc              text default '', conta_contabil text default '', fornecedor text default '',
  valor           numeric(14,2),
  nfs             text default ''
);
create index if not exists historico_prestador on public.historico (prestador, empresa);
create unique index if not exists historico_nota on public.historico (nota_id) where nota_id is not null;

-- ---------- E-mails, notas, documentos, eventos ----------
create table if not exists public.emails (
  id           bigserial primary key,
  graph_id     text unique not null,
  remetente    text default '',
  assunto      text default '',
  recebido_em  timestamptz,
  preview      text default '',
  web_link     text default '',
  tipo         text default 'nota',     -- nota | sem_anexo
  criado_em    timestamptz not null default now()
);

create table if not exists public.notas (
  id              bigserial primary key,
  email_id        bigint references public.emails(id),
  status          text not null default 'Em conferência'
                  check (status in ('Em conferência','Aguardando aprovação','Aprovada','Reprovada','NF lançada','Ignorada')),
  -- lidos do documento
  tipo_doc        text not null default 'NF',
  serie           text default '', chave_acesso text default '',
  cnpj_emitente   text default '', razao_social text default '', cnpj_tomador text default '',
  emissao         date,
  origem_dados    text default '',
  sugestao        text default '',
  -- as 17 colunas da planilha
  despesa text default '', empresa text default '', prestador text default '', descricao text default '',
  filial  text default '', produto text default '', cc text default '', conta_contabil text default '',
  fornecedor text default '', valor numeric(14,2), pc text default '', numero text default '',
  chamado text default '', status_chamado text default '', status_nota text default '',
  data_chamado date, vencimento date,
  -- controle
  alertas         text[] not null default '{}',
  pasta           text default '',
  aprovado_por    text default '',
  decisao_em      timestamptz,
  comentario      text default '',
  notificado      boolean not null default false,
  criado_em       timestamptz not null default now(),
  atualizado_em   timestamptz not null default now(),
  atualizado_por  text default ''
);
create index if not exists notas_status on public.notas (status);

create table if not exists public.documentos (
  id             bigserial primary key,
  nota_id        bigint references public.notas(id) on delete set null,
  email_id       bigint references public.emails(id),
  tipo           text not null default 'OUTRO',   -- NF FT XML BOLETO MC OUTRO
  nome_original  text not null,
  nome_final     text default '',
  caminho        text not null,                   -- caminho no bucket "notas"
  sha256         text default ''
);

create table if not exists public.eventos (
  id       bigserial primary key,
  nota_id  bigint references public.notas(id) on delete cascade,
  quando   timestamptz not null default now(),
  quem     text not null default 'sistema',
  acao     text not null,
  detalhe  text default ''
);

-- Só aprovador/admin decide; registra quem e quando. O robô (service role) não passa por aqui.
create or replace function public.controlar_nota() returns trigger
language plpgsql security definer set search_path = public as $$
declare v_email text;
begin
  new.atualizado_em := now();
  if auth.uid() is null then return new; end if;
  select email into v_email from public.perfis where id = auth.uid();
  new.atualizado_por := coalesce(v_email, '');
  if new.status in ('Aprovada','Reprovada') and new.status is distinct from old.status then
    if public.meu_papel() not in ('aprovador','admin') then
      raise exception 'Somente o aprovador pode dar o de acordo';
    end if;
    new.aprovado_por := v_email;
    new.decisao_em   := now();
  end if;
  if new.status = 'Aguardando aprovação' and old.status is distinct from 'Aguardando aprovação' then
    new.notificado := false;
    new.aprovado_por := ''; new.decisao_em := null;
  end if;
  return new;
end $$;

drop trigger if exists antes_de_alterar_nota on public.notas;
create trigger antes_de_alterar_nota before update on public.notas
  for each row execute function public.controlar_nota();

-- ---------- Segurança: só usuários logados ----------
alter table public.perfis       enable row level security;
alter table public.filiais      enable row level security;
alter table public.fornecedores enable row level security;
alter table public.historico    enable row level security;
alter table public.emails       enable row level security;
alter table public.notas        enable row level security;
alter table public.documentos   enable row level security;
alter table public.eventos      enable row level security;

do $$
declare t text;
begin
  foreach t in array array['filiais','fornecedores','historico','emails','notas','documentos','eventos'] loop
    execute format('drop policy if exists logados_tudo on public.%I', t);
    execute format('create policy logados_tudo on public.%I for all to authenticated using (true) with check (true)', t);
  end loop;
end $$;

drop policy if exists perfis_ler on public.perfis;
create policy perfis_ler on public.perfis for select to authenticated using (true);
drop policy if exists perfis_proprio on public.perfis;
create policy perfis_proprio on public.perfis for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid() and papel = (select papel from public.perfis where id = auth.uid()));

-- ---------- Arquivos (bucket privado) ----------
insert into storage.buckets (id, name, public) values ('notas', 'notas', false)
on conflict (id) do nothing;

drop policy if exists notas_logados on storage.objects;
create policy notas_logados on storage.objects for all to authenticated
  using (bucket_id = 'notas') with check (bucket_id = 'notas');
