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
async function iniciar() {
  const { data: { session } } = await sb.auth.getSession();
  if (!session) return telaLogin();
  const { data: p } = await sb.from("perfis").select("*").eq("id", session.user.id).single();
  PERFIL = p || { nome: session.user.email, email: session.user.email, papel: "analista", trocar_senha: false };
  if (PERFIL.trocar_senha) return telaSenha();
  $("#topo").hidden = false;
  $("#quem").textContent = `${PERFIL.nome} (${PERFIL.papel})`;
  $("#lnk-aprovar").hidden = !ehAprovador();
  await carregarListas();
  rotear();
}

function telaLogin() {
  $("#topo").hidden = true;
  main.replaceChildren($("#tpl-login").content.cloneNode(true));
  $("#form-login").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const { error } = await sb.auth.signInWithPassword({ email: f.get("email").trim(), password: f.get("senha") });
    if (error) return ($("#erro-login").textContent = "E-mail ou senha inválidos.");
    iniciar();
  };
}

function telaSenha() {
  $("#topo").hidden = true;
  main.replaceChildren($("#tpl-senha").content.cloneNode(true));
  $("#form-senha").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    if (f.get("s1") !== f.get("s2")) return ($("#erro-senha").textContent = "As senhas não conferem.");
    const { error } = await sb.auth.updateUser({ password: f.get("s1") });
    if (error) return ($("#erro-senha").textContent = error.message);
    await sb.from("perfis").update({ trocar_senha: false }).eq("id", PERFIL.id);
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
  const m = rota.match(/^\/nota\/(\d+)/);
  if (m) return telaNota(Number(m[1]));
  telaFila(params.get("status") || "", params.get("q") || "");
}

/* ------------------------------------------------------------------ fila */
async function telaFila(filtro, q) {
  main.innerHTML = `<p class="sub">Carregando…</p>`;
  const { data: todas, error } = await sb.from("notas")
    .select("id,status,prestador,descricao,tipo_doc,numero,empresa,filial,despesa,cc,valor,vencimento,pc,chamado,alertas")
    .neq("status", "Ignorada").order("vencimento", { ascending: true, nullsFirst: false }).order("id", { ascending: false }).limit(1000);
  if (error) return (main.innerHTML = `<div class="aviso erro">${esc(error.message)}</div>`);
  const cont = {};
  todas.forEach((n) => (cont[n.status] = (cont[n.status] || 0) + 1));
  const abertas = ["Em conferência", "Aguardando aprovação", "Aprovada", "Reprovada"];
  let lista = filtro ? todas.filter((n) => n.status === filtro) : todas.filter((n) => abertas.includes(n.status));
  const termo = q.toLowerCase();
  if (termo) lista = lista.filter((n) => [n.prestador, n.numero, n.empresa, n.pc, n.chamado, n.descricao].join(" ").toLowerCase().includes(termo));
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  const kpi = (s, rot, n) => `<a class="kpi ${filtro === s ? "ativo" : ""}" href="#/${s ? "?status=" + encodeURIComponent(s) : ""}"><span class="sub">${rot}</span><b>${n}</b></a>`;
  main.innerHTML = `
    <h1>Fila de notas</h1>
    <div class="kpis">${kpi("", "Em aberto", abertas.reduce((t, s) => t + (cont[s] || 0), 0))}${STATUS.map((s) => kpi(s, s, cont[s] || 0)).join("")}</div>
    <div class="card" style="padding:0">
      <form id="form-busca" style="padding:12px 14px;border-bottom:1px solid var(--borda)">
        <input class="busca" name="q" value="${esc(q)}" placeholder="Buscar prestador, NFS, PC, chamado, empresa…">
      </form>
      <div class="tabela-fila"><table>
        <tr><th>#</th><th>Etapa</th><th>Prestador</th><th>NFS</th><th>Empresa / Filial</th><th>Despesa</th><th>CC</th>
            <th class="num">Valor</th><th>Vencimento</th><th>PC / Chamado</th><th>Alertas</th></tr>
        ${lista.map((n) => {
          const venc = n.vencimento ? new Date(n.vencimento + "T12:00:00") : null;
          const urgente = venc && (venc - hoje) / 864e5 <= 3 && n.status !== "NF lançada";
          return `<tr class="link" data-id="${n.id}">
            <td>${n.id}</td><td><span class="tag ${COR[n.status]}">${esc(n.status)}</span></td>
            <td><b>${esc(n.prestador || "—")}</b><div class="sub">${esc((n.descricao || "").slice(0, 50))}</div></td>
            <td>${esc(n.tipo_doc)} ${esc(n.numero || "—")}</td><td>${esc(n.empresa || "—")} / ${esc(n.filial || "—")}</td>
            <td>${esc(n.despesa || "—")}</td><td>${esc(n.cc || "—")}</td><td class="num">${brl(n.valor)}</td>
            <td>${urgente ? `<span class="tag vermelho">${data(n.vencimento)}</span>` : data(n.vencimento)}</td>
            <td class="sub">${esc(n.pc || "—")} / ${esc(n.chamado || "—")}</td>
            <td>${n.alertas?.length ? `<span class="tag amarelo" title="${esc(n.alertas.join(" | "))}">${n.alertas.length}</span>` : ""}</td></tr>`;
        }).join("") || `<tr><td colspan="11" class="sub" style="padding:24px;text-align:center">Nenhuma nota aqui.</td></tr>`}
      </table></div>
    </div>
    <p class="sub">O robô verifica a caixa prestacaocontasti@ a cada 15 minutos em horário comercial.</p>`;
  $("#form-busca").onsubmit = (e) => {
    e.preventDefault();
    const p = new URLSearchParams(); if (filtro) p.set("status", filtro);
    const v = new FormData(e.target).get("q"); if (v) p.set("q", v);
    location.hash = "#/?" + p.toString();
  };
  main.querySelectorAll("tr.link").forEach((tr) => (tr.onclick = () => (location.hash = `#/nota/${tr.dataset.id}`)));
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
      <a href="#/" class="btn">← Fila</a>
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
          ${campo("fornecedor", "Fornecedor (cód. Protheus)", n.fornecedor)}
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
