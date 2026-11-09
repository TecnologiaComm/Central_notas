/* Central de Notas – site (GitHub Pages) + Supabase (login, dados e arquivos). */
const sb = supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);
const $ = (s, el = document) => el.querySelector(s);
const main = $("#conteudo");
let PERFIL = null, FILIAIS = [], OPCOES = { produto: [], cc: [], conta_contabil: [], prestador: [] };

const STATUS = ["Em conferência", "Aguardando aprovação", "Aprovada", "Reprovada", "NF lançada"];
const COR = { "Em conferência": "amarelo", "Aguardando aprovação": "azul", "Aprovada": "verde", "Reprovada": "vermelho", "NF lançada": "cinza", "Ignorada": "cinza" };
const STATUS_CHAMADO = ["AGUARDANDO ATENDIMENTO", "EM ATENDIMENTO", "SUSPENSO - APROV", "SUSPENSO - RATEIO", "ENCERRADO"];
const STATUS_NOTA = ["AGUARDANDO LANÇAMENTO FISCAL", "NF LANÇADA"];
const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const brl = (v) => v == null || v === "" ? "—" : Number(v).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const data = (d) => d ? new Date(d.length === 10 ? d + "T12:00:00" : d).toLocaleDateString("pt-BR") : "—";
const dataHora = (d) => d ? new Date(d).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";
const ehAprovador = () => ["aprovador", "admin"].includes(PERFIL?.papel);

function aviso(msg, erro = false) {
  const el = document.createElement("div");
  el.className = "aviso" + (erro ? " erro" : "");
  el.textContent = msg;
  $("#avisos").replaceChildren(el);
  setTimeout(() => el.remove(), 7000);
}

/* ------------------------------------------------------------------ login */
let RECUPERANDO = false;

async function iniciar() {
  // Link "Criar nova senha" do e-mail: ?recuperar=<token>
  const token = new URLSearchParams(location.search).get("recuperar");
  if (token) {
    history.replaceState(null, "", location.pathname);
    const { error } = await sb.auth.verifyOtp({ token_hash: token, type: "recovery" });
    if (error) {
      telaLogin();
      return ($("#erro-login").textContent = "Link expirado ou já usado. Peça outro em \"Esqueci minha senha\".");
    }
    RECUPERANDO = true;
  }
  const { data: { session } } = await sb.auth.getSession();
  if (!session) return telaLogin();
  const { data: p } = await sb.from("perfis").select("*").eq("id", session.user.id).single();
  PERFIL = p || { nome: session.user.email, email: session.user.email, papel: "analista", trocar_senha: false };
  if (PERFIL.trocar_senha || RECUPERANDO) return telaSenha();
  document.body.classList.add("logado");
  $("#quem").textContent = PERFIL.nome;
  $("#papel").textContent = { admin: "Administrador", aprovador: "Aprovador", analista: "Analista" }[PERFIL.papel] || PERFIL.papel;
  await carregarListas();
  rotear();
}

function telaLogin() {
  document.body.classList.remove("logado");
  main.replaceChildren($("#tpl-login").content.cloneNode(true));
  $("#form-login").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const { error } = await sb.auth.signInWithPassword({ email: f.get("email").trim(), password: f.get("senha") });
    if (error) return ($("#erro-login").textContent = "E-mail ou senha inválidos.");
    iniciar();
  };
  $("#lnk-esqueci").onclick = (e) => { e.preventDefault(); telaEsqueci($('[name="email"]', main).value); };
}

function telaEsqueci(emailDigitado = "") {
  document.body.classList.remove("logado");
  main.replaceChildren($("#tpl-esqueci").content.cloneNode(true));
  $('[name="email"]', main).value = emailDigitado;
  $("#lnk-voltar").onclick = (e) => { e.preventDefault(); telaLogin(); };
  $("#form-esqueci").onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.submitter; btn.disabled = true;
    const email = new FormData(e.target).get("email").trim();
    const { data, error } = await sb.functions.invoke("esqueci-senha", { body: { email } });
    const msg = $("#msg-esqueci");
    if (error || !data?.ok) {
      msg.className = "erro";
      msg.textContent = data?.mensagem || "Não foi possível enviar agora. Tente de novo em alguns minutos.";
      btn.disabled = false;
    } else {
      msg.className = "aviso";
      msg.textContent = data.mensagem + " Confira também a caixa de spam. O link vale por 1 hora.";
    }
  };
}

function telaSenha() {
  document.body.classList.remove("logado");
  main.replaceChildren($("#tpl-senha").content.cloneNode(true));
  if (RECUPERANDO) $("#txt-senha").textContent = "Crie uma nova senha para a Central de Notas. Use pelo menos 10 caracteres.";
  $("#form-senha").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    if (f.get("s1") !== f.get("s2")) return ($("#erro-senha").textContent = "As senhas não conferem.");
    const { error } = await sb.auth.updateUser({ password: f.get("s1") });
    if (error) return ($("#erro-senha").textContent = error.message);
    await sb.from("perfis").update({ trocar_senha: false }).eq("id", PERFIL.id);
    RECUPERANDO = false;
    aviso("Senha alterada.");
    iniciar();
  };
}

$("#btn-sair").onclick = async (e) => { e.preventDefault(); PERFIL = null; await sb.auth.signOut(); history.replaceState(null, "", location.pathname); telaLogin(); };
$("#btn-exportar").onclick = (e) => { e.preventDefault(); exportarPlanilha(); };
window.addEventListener("hashchange", () => PERFIL && !PERFIL.trocar_senha && rotear());

async function carregarListas() {
  const { data: f } = await sb.from("filiais").select("*").order("empresa").order("filial");
  FILIAIS = f || [];
  const { data: h } = await sb.from("historico").select("prestador,produto,cc,conta_contabil").limit(5000);
  for (const k of Object.keys(OPCOES)) OPCOES[k] = [...new Set((h || []).map((x) => x[k]).filter(Boolean))].sort();
}

function rotear() {
  const [rota, qs] = location.hash.replace(/^#/, "").split("?");
  const params = new URLSearchParams(qs || "");
  const m = rota.match(/^\/nota\/(\d+)/), mod = rota.match(/^\/m\/(\w+)/);
  const ativo = m ? null : mod ? mod[1] : "";
  document.querySelectorAll("#lateral [data-rota]").forEach((a) => a.classList.toggle("ativo", a.dataset.rota === ativo));
  window.scrollTo(0, 0);
  if (m) return telaNota(Number(m[1]));
  if (mod && MODULOS[mod[1]]) return telaModulo(mod[1], params);
  telaInicio();
}

/* ------------------------------------------------------------------ ícones e módulos */
const ICONE = {
  inicio: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  conferencia: '<path d="M9 5h10M9 12h10M9 19h10"/><path d="M4 5l1 1 2-2M4 12l1 1 2-2M4 19l1 1 2-2"/>',
  acordo: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
  protheus: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
  reprovadas: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
  lancadas: '<path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
  ignoradas: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 22 12a14 14 0 0 1-3.2 4M6.6 6.6A14 14 0 0 0 2 12s4 7 10 7a9 9 0 0 0 4-.9"/>',
  atencao: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  vencendo: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2M9 2h6"/>',
  vencidas: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  alertas: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
  atualizar: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
  exportar: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  busca: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
};
const svg = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONE[k]}</svg>`;
const ABERTAS = ["Em conferência", "Aguardando aprovação", "Aprovada", "Reprovada"];
const CAMPOS_LISTA = "id,status,prestador,descricao,tipo_doc,numero,empresa,filial,despesa,cc,conta_contabil,fornecedor,valor,vencimento," +
  "pc,chamado,status_nota,alertas,comentario,aprovado_por,decisao_em,atualizado_em,atualizado_por,criado_em";

const hoje0 = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
const dias = (n) => n.vencimento ? Math.round((new Date(n.vencimento + "T00:00:00") - hoje0()) / 864e5) : null;
const ATENCAO = {
  vencidas: { rotulo: "Vencidas", cor: "vermelho", f: (n) => { const d = dias(n); return d !== null && d < 0; } },
  vencendo: { rotulo: "Vencendo em até 3 dias", cor: "laranja", f: (n) => { const d = dias(n); return d !== null && d >= 0 && d <= 3; } },
  alertas: { rotulo: "Com alertas", cor: "amarelo", f: (n) => n.alertas?.length > 0 },
};

function idade(iso) {
  if (!iso) return "—";
  const h = (Date.now() - new Date(iso)) / 36e5;
  return h < 24 ? `${Math.max(1, Math.round(h))}h` : `${Math.floor(h / 24)}d ${Math.round(h % 24)}h`;
}
const soma = (l) => l.reduce((t, n) => t + Number(n.valor || 0), 0);
const qtd = (k) => `${k} ${k === 1 ? "nota" : "notas"}`;

/* Colunas reutilizáveis: [cabeçalho, render(n), classe] */
const COL = {
  id: ["#", (n) => n.id],
  etapa: ["Etapa", (n) => `<span class="tag ${COR[n.status]}">${esc(n.status)}</span>`],
  prestador: ["Prestador", (n) => `<b>${esc(n.prestador || "—")}</b><div class="sub">${esc((n.descricao || "").slice(0, 60))}</div>`, "c-prest"],
  nfs: ["NFS", (n) => `${esc(n.tipo_doc)} ${esc(n.numero || "—")}`, "nw"],
  empresa: ["Empresa / Filial", (n) => `${esc(n.empresa || "—")} / ${esc(n.filial || "—")}`, "nw"],
  classif: ["Despesa · CC · Conta", (n) => `${esc(n.despesa || "—")} · ${esc(n.cc || "—")} · ${esc(n.conta_contabil || "—")}`, "nw"],
  fornecedor: ["Fornecedor", (n) => esc(n.fornecedor || "—")],
  valor: ["Valor", (n) => brl(n.valor), "num"],
  venc: ["Vencimento", (n) => { const d = dias(n); return d !== null && d <= 3 && ABERTAS.includes(n.status)
    ? `<span class="tag ${d < 0 ? "vermelho" : "laranja"}">${data(n.vencimento)}</span>` : data(n.vencimento); }, "nw"],
  recebida: ["Recebida há", (n) => idade(n.criado_em), "nw"],
  alertas: ["Alertas", (n) => n.alertas?.length ? n.alertas.map((a) => `<div class="mini-alerta">⚠ ${esc(a)}</div>`).join("") : `<span class="sub">—</span>`, "c-alerta"],
  enviada: ["Enviada", (n) => `${dataHora(n.atualizado_em)}<div class="sub">${esc(n.atualizado_por || "")}</div>`, "nw"],
  aprovada: ["De acordo", (n) => `${dataHora(n.decisao_em)}<div class="sub">${esc(n.aprovado_por || "")}</div>`, "nw"],
  pc: ["PC / Chamado", (n) => `${esc(n.pc || "—")} / ${esc(n.chamado || "—")}`, "nw"],
  statusNota: ["Status nota", (n) => esc(n.status_nota || "—")],
  motivo: ["Motivo", (n) => `<b>${esc(n.comentario || "—")}</b><div class="sub">${esc(n.aprovado_por || "")} · ${dataHora(n.decisao_em)}</div>`, "c-prest"],
};

const MODULOS = {
  conferencia: { titulo: "Em conferência", status: "Em conferência", cor: "amarelo",
    desc: "Notas que o robô leu da caixa. Confira os campos e peça o de acordo.",
    colunas: ["id", "recebida", "prestador", "nfs", "empresa", "valor", "venc", "alertas"], botao: () => ["Conferir", "pri", "abrir"] },
  acordo: { titulo: "Aguardando de acordo", status: "Aguardando aprovação", cor: "azul",
    desc: "Notas conferidas esperando o de acordo do Robson. Clique na linha para ver os detalhes e os arquivos.",
    colunas: ["id", "prestador", "nfs", "empresa", "classif", "valor", "venc", "enviada"],
    botao: () => ehAprovador() ? ["De acordo", "ok", "aprovar"] : ["Abrir", "", "abrir"] },
  protheus: { titulo: "Prontas p/ Protheus", status: "Aprovada", cor: "verde",
    desc: "Com de acordo. Lance no Protheus e registre PC, chamado e status.",
    colunas: ["id", "prestador", "nfs", "empresa", "fornecedor", "valor", "venc", "aprovada", "pc"], botao: () => ["Lançar", "pri", "abrir"] },
  reprovadas: { titulo: "Não de acordo", status: "Reprovada", cor: "vermelho",
    desc: "O Robson não deu o de acordo. Veja o motivo, corrija e envie de novo.",
    colunas: ["id", "prestador", "nfs", "valor", "motivo"], botao: () => ["Corrigir", "pri", "abrir"] },
  lancadas: { titulo: "NF lançadas", status: "NF lançada", cor: "cinza", mes: true,
    desc: "Notas concluídas. Filtre por mês de recebimento.",
    colunas: ["id", "prestador", "nfs", "empresa", "valor", "pc", "statusNota", "venc"], botao: () => ["Ver", "", "abrir"] },
  ignoradas: { titulo: "Ignoradas", status: "Ignorada", cor: "cinza",
    desc: "E-mails que não eram nota ou eram duplicados. Reabra se foi engano.",
    colunas: ["id", "recebida", "prestador", "nfs", "valor"], botao: () => ["Reabrir", "", "reabrir"] },
  atencao: { titulo: "Atenção", cor: "vermelho", abas: true,
    desc: "Notas em aberto vencidas, vencendo em até 3 dias ou com alertas de duplicidade, cadastro ou leitura.",
    colunas: ["id", "etapa", "prestador", "nfs", "valor", "venc", "alertas"], botao: () => ["Abrir", "", "abrir"] },
};
const moduloDoStatus = (s) => Object.keys(MODULOS).find((k) => MODULOS[k].status === s) || "conferencia";

async function buscarNotas() {
  const { data, error } = await sb.from("notas").select(CAMPOS_LISTA)
    .order("vencimento", { ascending: true, nullsFirst: false }).order("id", { ascending: false }).limit(3000);
  if (error) throw error;
  return data;
}

/* ------------------------------------------------------------------ início */
async function telaInicio() {
  main.innerHTML = `<p class="sub">Carregando…</p>`;
  let todas;
  try { todas = await buscarNotas(); } catch (e) { return (main.innerHTML = `<div class="aviso erro">${esc(e.message)}</div>`); }
  const abertas = todas.filter((n) => ABERTAS.includes(n.status));
  const por = (k) => todas.filter((n) => n.status === MODULOS[k].status);
  const att = Object.fromEntries(Object.entries(ATENCAO).map(([k, a]) => [k, abertas.filter(a.f)]));
  const hora = new Date().getHours();
  const saud = hora < 12 ? "Bom dia" : hora < 18 ? "Boa tarde" : "Boa noite";
  const hojeTxt = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  const maisAntiga = (l) => l.length ? idade(l.reduce((a, n) => (n.criado_em < a ? n.criado_em : a), l[0].criado_em)) : "—";

  const cartao = (href, icone, cor, titulo, lista, rodape) => `
    <a class="cartao" href="${href}">
      <span class="icone ${cor}">${svg(icone)}</span>
      <span class="titulo">${titulo}</span>
      <span class="numero"><b>${lista.length}</b> ${lista.length === 1 ? "nota" : "notas"}</span>
      <span class="rodape">${rodape}<span class="seta">›</span></span>
    </a>`;

  main.innerHTML = `
    <section class="hero">
      <div>
        <h1>${saud}, ${esc((PERFIL.nome || "").split(" ")[0])}</h1>
        <p>${hojeTxt} · <b>${qtd(por("conferencia").length)}</b> em conferência, <b>${att.vencidas.length + att.vencendo.length}</b> vencendo ou vencidas</p>
      </div>
      <form id="form-busca" class="busca-hero">${svg("busca")}<input name="q" placeholder="Buscar em todas as notas: prestador, NFS, PC, chamado…"></form>
    </section>
    <div class="acoes-hero">
      <button class="acao destaque" id="btn-atualizar"><span class="icone escuro">${svg("atualizar")}</span>Atualizar agora</button>
      <button class="acao" id="btn-exportar2"><span class="icone claro">${svg("exportar")}</span>Baixar planilha</button>
      <a class="acao" href="#/m/acordo"><span class="icone claro">${svg("acordo")}</span>${ehAprovador() ? "Meus de acordo" : "Aguardando de acordo"}</a>
      <a class="acao" href="#/m/protheus"><span class="icone claro">${svg("protheus")}</span>Prontas p/ Protheus</a>
    </div>

    <h3 class="secao-titulo">ETAPAS <span>notas em aberto</span></h3>
    <div class="cartoes">
      ${cartao("#/m/conferencia", "conferencia", "amarelo", "Em conferência", por("conferencia"), `mais antiga: ${maisAntiga(por("conferencia"))}`)}
      ${cartao("#/m/acordo", "acordo", "azul", "Aguardando de acordo", por("acordo"), `${brl(soma(por("acordo")))} aguardando`)}
      ${cartao("#/m/protheus", "protheus", "verde", "Prontas p/ Protheus", por("protheus"), `${brl(soma(por("protheus")))} para lançar`)}
      ${cartao("#/m/reprovadas", "reprovadas", "vermelho", "Não de acordo", por("reprovadas"), "voltar para conferência")}
    </div>

    <h3 class="secao-titulo">ATENÇÃO</h3>
    <div class="cartoes">
      ${cartao("#/m/atencao?aba=vencidas", "vencidas", "vermelho", "Vencidas", att.vencidas, `${brl(soma(att.vencidas))} em atraso`)}
      ${cartao("#/m/atencao?aba=vencendo", "vencendo", "laranja", "Vencendo em até 3 dias", att.vencendo, `${brl(soma(att.vencendo))} nos próximos dias`)}
      ${cartao("#/m/atencao?aba=alertas", "alertas", "amarelo", "Com alertas", att.alertas, "duplicidade, cadastro ou leitura")}
      ${cartao("#/m/lancadas", "lancadas", "cinza", "NF lançadas", por("lancadas"), `${brl(soma(por("lancadas")))} no total`)}
    </div>
    <p class="sub">O robô verifica a caixa prestacaocontasti@ a cada 15 minutos, de segunda a sexta, das 8h às 19h45.</p>`;

  $("#form-busca").onsubmit = (e) => {
    e.preventDefault();
    const v = new FormData(e.target).get("q").trim();
    if (v) location.hash = "#/m/busca?q=" + encodeURIComponent(v);
  };
  $("#btn-atualizar").onclick = () => telaInicio();
  $("#btn-exportar2").onclick = () => exportarPlanilha();
}

/* ------------------------------------------------------------------ módulos */
MODULOS.busca = { titulo: "Busca", cor: "cinza", oculto: true, desc: "Resultado em todas as notas, de qualquer etapa.",
  colunas: ["id", "etapa", "prestador", "nfs", "empresa", "valor", "venc", "pc"], botao: () => ["Abrir", "", "abrir"] };

async function telaModulo(chave, params) {
  const M = MODULOS[chave], q = params.get("q") || "";
  main.innerHTML = `<p class="sub">Carregando…</p>`;
  let todas;
  try { todas = await buscarNotas(); } catch (e) { return (main.innerHTML = `<div class="aviso erro">${esc(e.message)}</div>`); }

  let lista, abasHtml = "", mesHtml = "";
  if (chave === "atencao") {
    const aba = ATENCAO[params.get("aba")] ? params.get("aba") : "vencidas";
    const abertas = todas.filter((n) => ABERTAS.includes(n.status));
    lista = abertas.filter(ATENCAO[aba].f);
    abasHtml = `<div class="abas">${Object.entries(ATENCAO).map(([k, a]) =>
      `<a class="${k === aba ? "ativa" : ""}" href="#/m/atencao?aba=${k}">${a.rotulo} <span>${abertas.filter(a.f).length}</span></a>`).join("")}</div>`;
  } else if (chave === "busca") {
    lista = todas;
  } else {
    lista = todas.filter((n) => n.status === M.status);
  }
  if (M.mes) {
    const meses = [...new Set(lista.map((n) => (n.criado_em || "").slice(0, 7)))].sort().reverse();
    const mes = params.get("mes") || "";
    if (mes) lista = lista.filter((n) => (n.criado_em || "").startsWith(mes));
    mesHtml = `<select id="sel-mes" class="filtro"><option value="">Todos os meses</option>${meses.map((m) =>
      `<option value="${m}" ${m === mes ? "selected" : ""}>${MESES[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}</option>`).join("")}</select>`;
  }
  const termo = q.toLowerCase();
  if (termo) lista = lista.filter((n) => [n.prestador, n.numero, n.empresa, n.pc, n.chamado, n.descricao, n.fornecedor].join(" ").toLowerCase().includes(termo));

  const [rotBotao, clsBotao] = M.botao();
  main.innerHTML = `
    <section class="cab-modulo">
      <span class="icone grande ${M.cor}">${svg(ICONE[chave] ? chave : "busca")}</span>
      <div class="cab-texto"><h1>${esc(M.titulo)}</h1><p>${esc(M.desc)}</p></div>
      <div class="cab-numeros"><b>${lista.length}</b><span>${lista.length === 1 ? "nota" : "notas"} · ${brl(soma(lista))}</span></div>
    </section>
    ${abasHtml}
    <div class="barra-modulo">
      <form id="form-busca" class="busca-hero borda">${svg("busca")}<input name="q" value="${esc(q)}" placeholder="Filtrar por prestador, NFS, PC, chamado…"></form>
      ${mesHtml}
    </div>
    <div class="card tabela-fila" style="padding:0"><table>
      <tr>${M.colunas.map((c) => `<th class="${COL[c][2] || ""}">${COL[c][0]}</th>`).join("")}<th></th></tr>
      ${lista.map((n) => `<tr class="link" data-id="${n.id}">${M.colunas.map((c) => `<td class="${COL[c][2] || ""}">${COL[c][1](n)}</td>`).join("")}
        <td class="nw"><button class="btn ${clsBotao} pequeno" data-id="${n.id}">${rotBotao}</button></td></tr>`).join("")
        || `<tr><td colspan="${M.colunas.length + 1}" class="vazio">Nada por aqui. ${chave === "conferencia" ? "Quando chegar nota na caixa, ela aparece aqui." : ""}</td></tr>`}
    </table></div>`;

  $("#form-busca").onsubmit = (e) => {
    e.preventDefault();
    const p = new URLSearchParams(params); const v = new FormData(e.target).get("q").trim();
    v ? p.set("q", v) : p.delete("q");
    location.hash = `#/m/${chave}?${p}`;
  };
  const sm = $("#sel-mes");
  if (sm) sm.onchange = () => { const p = new URLSearchParams(params); sm.value ? p.set("mes", sm.value) : p.delete("mes"); location.hash = `#/m/${chave}?${p}`; };

  main.querySelectorAll("tr.link").forEach((tr) => (tr.onclick = () => (location.hash = `#/nota/${tr.dataset.id}`)));
  main.querySelectorAll("button[data-id]").forEach((b) => (b.onclick = async (e) => {
    e.stopPropagation();
    const id = Number(b.dataset.id), acao = M.botao()[2];
    if (acao === "abrir") return (location.hash = `#/nota/${id}`);
    b.disabled = true;
    const status = acao === "aprovar" ? "Aprovada" : "Em conferência";
    const { error } = await sb.from("notas").update(acao === "aprovar" ? { status, comentario: "" } : { status }).eq("id", id);
    if (error) { b.disabled = false; return aviso("Erro: " + error.message, true); }
    await evento(id, acao === "aprovar" ? "De acordo" : "Reaberta para conferência");
    aviso(acao === "aprovar" ? `De acordo registrado na nota #${id}.` : `Nota #${id} voltou para conferência.`);
    telaModulo(chave, params);
  }));
}

/* ------------------------------------------------------------------ nota */
const campo = (nome, rotulo, valor, { tipo = "text", lista = "", cls = "", opcoes = null, req = false } = {}) => {
  if (opcoes) return `<div class="${cls}"><label>${rotulo}</label><select name="${nome}"><option value="">—</option>
    ${opcoes.map((o) => { const [v, t] = Array.isArray(o) ? o : [o, o]; return `<option value="${esc(v)}" ${String(valor ?? "") === String(v) ? "selected" : ""}>${esc(t)}</option>`; }).join("")}</select></div>`;
  return `<div class="${cls}"><label>${rotulo}</label><input name="${nome}" type="${tipo}" value="${esc(valor ?? "")}" ${lista ? `list="l-${lista}"` : ""} ${req ? "required" : ""}></div>`;
};

async function telaNota(id) {
  main.innerHTML = `<p class="sub">Carregando…</p>`;
  const { data: n, error } = await sb.from("notas").select("*, emails(*), documentos(*), eventos(*)").eq("id", id).single();
  if (error) return (main.innerHTML = `<div class="aviso erro">${esc(error.message)}</div>`);
  n.eventos.sort((a, b) => b.id - a.id);
  n.documentos.sort((a, b) => a.id - b.id);
  const editavel = ["Em conferência", "Reprovada"].includes(n.status);
  const empresas = [...new Set(FILIAIS.map((f) => f.empresa))];
  const filiaisOp = FILIAIS.filter((f) => !n.empresa || f.empresa === n.empresa).map((f) => [f.filial, `${f.filial} – ${f.empresa}`]);
  if (n.filial && !filiaisOp.some((o) => o[0] === n.filial)) filiaisOp.push([n.filial, n.filial]);
  const links = await Promise.all(n.documentos.map((d) => sb.storage.from("notas").createSignedUrl(d.caminho, 3600)));

  main.innerHTML = `
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap">
      <a href="#/m/${moduloDoStatus(n.status)}" class="btn">← ${esc((MODULOS[moduloDoStatus(n.status)] || {}).titulo || "Voltar")}</a>
      <h1 style="margin:0">Nota #${n.id} · ${esc(n.prestador || "Sem prestador")} ${esc(n.tipo_doc)} ${esc(n.numero)} ${esc(n.empresa)}</h1>
      <span class="tag ${COR[n.status]}">${esc(n.status)}</span>
    </div>
    ${(n.alertas || []).map((a) => `<div class="alerta">⚠ ${esc(a)}</div>`).join("")}
    ${["prestador", "produto", "cc", "conta_contabil"].map((k) => `<datalist id="l-${k}">${OPCOES[k].map((v) => `<option value="${esc(v)}">`).join("")}</datalist>`).join("")}
    <div class="col" style="margin-top:12px"><div>
      <form id="form-nota" class="card">
        <h2>Linha da planilha</h2>
        ${n.sugestao ? `<p class="sub" style="margin:-6px 0 12px">💡 ${esc(n.sugestao)}</p>` : ""}
        <fieldset ${editavel ? "" : "disabled"} style="border:0;padding:0;margin:0"><div class="grade">
          ${campo("despesa", "Despesa", n.despesa, { opcoes: ["OPEX", "CAPEX"] })}
          ${campo("empresa", "Empresa", n.empresa, { opcoes: empresas })}
          ${campo("filial", "Filial", n.filial, { opcoes: filiaisOp })}
          ${campo("prestador", "Prestador", n.prestador, { lista: "prestador", req: true })}
          ${campo("descricao", "Descrição", n.descricao, { cls: "l4" })}
          ${campo("produto", "Produto", n.produto, { lista: "produto" })}
          ${campo("cc", "CC", n.cc, { lista: "cc" })}
          ${campo("conta_contabil", "Conta contábil", n.conta_contabil, { lista: "conta_contabil" })}
          ${campo("fornecedor", "Fornecedor (Protheus)", n.fornecedor)}
          ${campo("valor", "Valor (R$)", n.valor, { tipo: "number" })}
          ${campo("numero", "NFS", n.numero, { req: true })}
          ${campo("tipo_doc", "Tipo (nome do arquivo)", n.tipo_doc, { opcoes: [["NF", "NF – Nota fiscal"], ["FT", "FT – Fatura"]] })}
          ${campo("vencimento", "Vencimento", n.vencimento, { tipo: "date" })}
          ${campo("razao_social", "Razão social", n.razao_social, { cls: "l2" })}
          ${campo("cnpj_emitente", "CNPJ prestador", n.cnpj_emitente)}
          <div><label>Emissão</label><input value="${data(n.emissao)}" disabled></div>
        </div></fieldset>
        <p class="sub">Lido via <b>${esc(n.origem_dados)}</b>. Ao salvar, os arquivos viram
          <b>${esc((n.prestador || "PRESTADOR") + "_" + n.tipo_doc + "_" + (n.numero || "NÚMERO") + "_" + (n.empresa || "EMPRESA"))}</b>
          e a linha entra no histórico que alimenta as próximas sugestões.</p>
        <div class="acoes">
          ${editavel ? `
            <button class="btn" data-acao="salvar">Salvar</button>
            <button class="btn pri" data-acao="enviar">Salvar e pedir “de acordo”</button>
            <button class="btn perigo" data-acao="ignorar" style="margin-left:auto" formnovalidate>Ignorar</button>` : ""}
          ${n.status === "Aguardando aprovação" && !ehAprovador() ? `<button class="btn" data-acao="reabrir" formnovalidate>Reabrir para conferência</button>` : ""}
          ${n.status === "Ignorada" ? `<button class="btn" data-acao="reabrir" formnovalidate>Reabrir</button>` : ""}
        </div>
      </form>

      ${n.status === "Aguardando aprovação" && ehAprovador() ? `
      <form id="form-decisao" class="card">
        <h2>Seu de acordo</h2>
        <textarea name="comentario" rows="2" placeholder="Comentário (obrigatório para não de acordo)"></textarea>
        <div class="acoes">
          <button class="btn ok" data-decisao="Aprovada">De acordo</button>
          <button class="btn perigo-cheio" data-decisao="Reprovada">Não de acordo</button>
        </div>
      </form>` : ""}

      ${["Aprovada", "NF lançada"].includes(n.status) ? `
      <form id="form-lanc" class="card">
        <h2>Lançamento (Protheus / chamado)</h2>
        <div class="grade">
          ${campo("pc", "PC", n.pc)}${campo("chamado", "Chamado", n.chamado)}
          ${campo("data_chamado", "Data chamado", n.data_chamado, { tipo: "date" })}<div></div>
          ${campo("status_chamado", "Status chamado", n.status_chamado, { opcoes: STATUS_CHAMADO, cls: "l2" })}
          ${campo("status_nota", "Status nota", n.status_nota, { opcoes: STATUS_NOTA, cls: "l2" })}
        </div>
        <div class="acoes"><button class="btn ok">Salvar lançamento</button>
          <span class="sub">Com “NF LANÇADA”, a nota sai da fila.</span></div>
      </form>` : ""}

      <div class="card"><h2>Histórico</h2><ul class="hist">
        ${n.eventos.map((ev) => `<li><b>${esc(ev.acao)}</b> <span class="sub">· ${dataHora(ev.quando)} · ${esc(ev.quem)}</span>
          ${ev.detalhe ? `<div class="sub">${esc(ev.detalhe)}</div>` : ""}</li>`).join("")}</ul></div>
    </div><div>
      <div class="card"><h2>Arquivos</h2><table>
        ${n.documentos.map((d, i) => `<tr><td><span class="tag cinza">${esc(d.tipo)}</span></td><td>
          <a href="${esc(links[i].data?.signedUrl || "#")}" target="_blank" rel="noopener">${esc(d.nome_final || d.nome_original)}</a>
          ${d.nome_final ? `<div class="sub">original: ${esc(d.nome_original)}</div>` : ""}</td></tr>`).join("")}
      </table>${n.pasta ? `<p class="sub">Pasta: ${esc(n.pasta)}</p>` : ""}</div>
      ${n.emails ? `<div class="card"><h2>E-mail de origem</h2><div><b>${esc(n.emails.assunto)}</b></div>
        <div class="sub">${esc(n.emails.remetente)} · ${dataHora(n.emails.recebido_em)}</div>
        <p style="white-space:pre-wrap">${esc(n.emails.preview)}</p>
        ${n.emails.web_link ? `<a class="btn" href="${esc(n.emails.web_link)}" target="_blank" rel="noopener">Abrir no Outlook</a>` : ""}</div>` : ""}
      ${n.aprovado_por ? `<div class="card"><h2>De acordo</h2><div><b>${esc(n.status)}</b> por ${esc(n.aprovado_por)}</div>
        <div class="sub">${dataHora(n.decisao_em)}</div>${n.comentario ? `<p>${esc(n.comentario)}</p>` : ""}</div>` : ""}
    </div></div>`;

  // filial acompanha a empresa escolhida
  const selEmp = $('[name="empresa"]', main), selFil = $('[name="filial"]', main);
  if (selEmp && selFil) selEmp.onchange = () => {
    selFil.innerHTML = `<option value="">—</option>` + FILIAIS.filter((f) => f.empresa === selEmp.value)
      .map((f) => `<option value="${esc(f.filial)}">${esc(f.filial)} – ${esc(f.empresa)}</option>`).join("");
  };

  $("#form-nota").onsubmit = async (e) => {
    e.preventDefault();
    const acao = e.submitter?.dataset.acao || "salvar";
    if (acao === "ignorar" && !confirm("Marcar como ignorada (não é nota / duplicada)?")) return;
    e.submitter.disabled = true;
    try {
      if (acao === "salvar" || acao === "enviar") await salvarConferencia(n, new FormData(e.target), acao === "enviar");
      if (acao === "ignorar") await mudarStatus(n, "Ignorada", "Ignorada");
      if (acao === "reabrir") await mudarStatus(n, "Em conferência", "Reaberta para conferência");
      aviso(acao === "enviar" ? "Enviada para o de acordo. O aprovador será avisado por e-mail." : "Salvo.");
      telaNota(n.id);
    } catch (err) { aviso("Erro: " + err.message, true); e.submitter.disabled = false; }
  };

  const fd = $("#form-decisao");
  if (fd) fd.onsubmit = async (e) => {
    e.preventDefault();
    const status = e.submitter.dataset.decisao, comentario = new FormData(fd).get("comentario").trim();
    if (status === "Reprovada" && !comentario) return aviso("Escreva o motivo do não de acordo.", true);
    const { error } = await sb.from("notas").update({ status, comentario }).eq("id", n.id);
    if (error) return aviso("Erro: " + error.message, true);
    await evento(n.id, status === "Aprovada" ? "De acordo" : "Não de acordo", comentario);
    aviso(status === "Aprovada" ? "De acordo registrado." : "Não de acordo registrado."); telaNota(n.id);
  };

  const fl = $("#form-lanc");
  if (fl) fl.onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(fl));
    const valores = { pc: f.pc, chamado: f.chamado, status_chamado: f.status_chamado, status_nota: f.status_nota, data_chamado: f.data_chamado || null };
    if (f.status_nota === "NF LANÇADA") valores.status = "NF lançada";
    const { error } = await sb.from("notas").update(valores).eq("id", n.id);
    if (error) return aviso("Erro: " + error.message, true);
    await sb.from("historico").update({ nfs: n.numero }).eq("nota_id", n.id);
    await evento(n.id, "Lançamento atualizado", `PC ${f.pc || "—"} · chamado ${f.chamado || "—"} · ${f.status_nota || "—"}`);
    aviso("Lançamento salvo."); telaNota(n.id);
  };
}

/* ------------------------------------------------------------------ ações */
const limpar = (t) => (t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toUpperCase().trim().replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "");
const SUFIXO = { BOLETO: "_BOLETO", MC: "_MC", OUTRO: "_ANEXO" };

async function evento(nota_id, acao, detalhe = "") {
  await sb.from("eventos").insert({ nota_id, acao, detalhe, quem: PERFIL.email });
}

async function mudarStatus(n, status, acao) {
  const { error } = await sb.from("notas").update({ status }).eq("id", n.id);
  if (error) throw error;
  await evento(n.id, acao);
}

async function salvarConferencia(n, form, pedirDeAcordo) {
  const f = Object.fromEntries(form);
  const v = {
    despesa: f.despesa, empresa: f.empresa, filial: f.filial, prestador: (f.prestador || "").toUpperCase().trim(),
    descricao: f.descricao, produto: (f.produto || "").toUpperCase().trim(), cc: f.cc, conta_contabil: f.conta_contabil,
    fornecedor: (f.fornecedor || "").toUpperCase().trim(), valor: f.valor === "" ? null : Number(f.valor), numero: (f.numero || "").trim(),
    tipo_doc: f.tipo_doc || "NF", vencimento: f.vencimento || null, razao_social: f.razao_social, cnpj_emitente: (f.cnpj_emitente || "").replace(/\D/g, ""),
  };
  // Alertas que dependem do preenchimento são recalculados; duplicidade é mantida.
  const alertas = (n.alertas || []).filter((a) => /DUPLICIDADE|já consta/.test(a));
  if (!v.empresa) alertas.push("Empresa/filial não preenchida");
  if (!v.fornecedor) alertas.push("Sem código de fornecedor (Protheus)");
  if (!v.valor || !v.vencimento) alertas.push("Falta valor ou vencimento");
  v.alertas = alertas;

  // Renomeia os arquivos: PRESTADOR_NFouFT_NÚMERO_EMPRESA[_BOLETO|_MC] em <EMPRESA>/<AAAA-MM>/
  const base = [limpar(v.prestador) || "SEMPRESTADOR", v.tipo_doc, limpar(v.numero) || "SEMNUMERO", limpar(v.empresa) || "SEMEMPRESA"].join("_");
  const ref = (n.emissao || n.criado_em || new Date().toISOString()).slice(0, 7);
  const pasta = `${limpar(v.empresa) || "SEM-EMPRESA"}/${ref}`;
  const usados = new Set();
  for (const d of n.documentos) {
    const ext = (d.nome_original.match(/\.[^.]+$/) || [""])[0].toLowerCase();
    let nome = base + (["NF", "FT", "XML"].includes(d.tipo) ? "" : SUFIXO[d.tipo] || "") + ext;
    for (let i = 2; usados.has(nome); i++) nome = nome.replace(/(_\d+)?(\.[^.]+)$/, `_${i}$2`);
    usados.add(nome);
    const destino = `${pasta}/${nome}`;
    if (destino === d.caminho) continue;
    await sb.storage.from("notas").remove([destino]); // nome já usado por versão anterior desta nota
    const { error } = await sb.storage.from("notas").move(d.caminho, destino);
    if (error) throw new Error(`Não foi possível renomear ${d.nome_original}: ${error.message}`);
    await sb.from("documentos").update({ caminho: destino, nome_final: nome }).eq("id", d.id);
  }
  v.pasta = pasta;
  if (pedirDeAcordo) { v.status = "Aguardando aprovação"; v.status_chamado = n.status_chamado || "SUSPENSO - APROV"; }
  const { error } = await sb.from("notas").update(v).eq("id", n.id);
  if (error) throw error;

  // Aprende: histórico (base das sugestões) e código do fornecedor por empresa
  const h = { nota_id: n.id, origem: "app", data_ref: (n.criado_em || "").slice(0, 7) + "-01", nfs: v.numero, despesa: v.despesa, empresa: v.empresa,
    prestador: v.prestador, descricao: v.descricao, filial: v.filial, produto: v.produto, cc: v.cc, conta_contabil: v.conta_contabil, fornecedor: v.fornecedor, valor: v.valor };
  await sb.from("historico").upsert(h, { onConflict: "nota_id" });
  if (v.cnpj_emitente && v.prestador) {
    const { data: atual } = await sb.from("fornecedores").select("*").eq("cnpj", v.cnpj_emitente).maybeSingle();
    const codigos = { ...(atual?.codigos || {}) };
    if (v.empresa && v.fornecedor) codigos[v.empresa] = v.fornecedor;
    await sb.from("fornecedores").upsert({ cnpj: v.cnpj_emitente, apelido: v.prestador, razao: v.razao_social || atual?.razao || "", codigos });
  }
  await evento(n.id, pedirDeAcordo ? "Enviada para o de acordo" : "Conferência salva", `Arquivos em ${pasta}`);
}

/* ------------------------------------------------------------------ planilha */
const COLUNAS = [["DESPESA", "despesa"], ["EMPRESA", "empresa"], ["PRESTADOR", "prestador"], ["DESCRIÇÃO", "descricao"], ["FILIAL", "filial"],
  ["PRODUTO", "produto"], ["CC ", "cc"], ["CONTA CONTABIL ", "conta_contabil"], ["FORNECEDOR", "fornecedor"], ["VALOR", "valor"], ["PC", "pc"],
  ["NFS", "numero"], ["CHAMADO", "chamado"], ["STATUS CHAMADO", "status_chamado"], ["STATUS NOTA", "status_nota"], ["DATA CHAMADO", "data_chamado"],
  ["VENCIMENTO", "vencimento"]];

async function exportarPlanilha() {
  const { data: notas, error } = await sb.from("notas").select("*").neq("status", "Ignorada").order("criado_em").order("id");
  if (error) return aviso("Erro: " + error.message, true);
  const valor = (n, k) => {
    const x = n[k];
    if (x == null || x === "") return "";
    if (k === "valor") return Number(x);
    if (["vencimento", "data_chamado"].includes(k)) return new Date(x + "T12:00:00");
    if (["filial", "cc", "conta_contabil", "numero"].includes(k) && /^[1-9]\d*$/.test(x)) return Number(x);
    return x;
  };
  const wb = XLSX.utils.book_new(), abas = {};
  for (const n of notas) {
    const d = new Date(n.criado_em), aba = `${MESES[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
    (abas[aba] ||= []).push(COLUNAS.map(([, k]) => valor(n, k)));
  }
  for (const [aba, linhas] of Object.entries(abas)) {
    const ws = XLSX.utils.aoa_to_sheet([COLUNAS.map((c) => c[0]), ...linhas], { cellDates: true, dateNF: "dd/mm/yyyy" });
    ws["!cols"] = [10, 10, 18, 60, 8, 12, 8, 15, 12, 14, 10, 12, 12, 24, 30, 13, 13].map((w) => ({ wch: w }));
    XLSX.utils.book_append_sheet(wb, ws, aba);
  }
  const ctrl = [["ID", "ETAPA", "PRESTADOR", "NFS", "RAZÃO SOCIAL", "CNPJ", "APROVADO POR", "DATA DECISÃO", "PASTA"],
    ...notas.map((n) => [n.id, n.status, n.prestador, n.numero, n.razao_social, n.cnpj_emitente, n.aprovado_por, n.decisao_em ? new Date(n.decisao_em) : "", n.pasta])];
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(ctrl, { cellDates: true }), "Controle app");
  XLSX.writeFile(wb, `CONTROLE_NOTAS_${new Date().toISOString().slice(0, 10)}.xlsx`);
}

iniciar();
