-- Rodar DEPOIS de criar os 5 usuários em Authentication → Users → Add user.
-- Ajusta nomes e papéis. Senhas não ficam aqui: cada um troca a provisória no primeiro acesso.
update public.perfis p set nome = v.nome, papel = v.papel, trocar_senha = true
from (values
  ('refreitas@commcenter.com.br',  'Renan da Silva Freitas',           'admin'),
  ('lherrero@commcenter.com.br',   'Lukas Gabriel Herrero',            'analista'),
  ('mprado@commcenter.com.br',     'Moacir Aparecido Da Rocha Prado',  'analista'),
  ('rbastos@commcenter.com.br',    'Robson Gonçalves Bastos',          'aprovador'),
  ('acpereira@commcenter.com.br',  'Alexandre Marques Correa Pereira', 'analista')
) as v(email, nome, papel)
where lower(p.email) = v.email;

select nome, email, papel from public.perfis order by nome;
