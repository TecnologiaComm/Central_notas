// Esqueci minha senha: gera um link de troca de senha e envia pela caixa prestacaocontasti@ (Microsoft Graph).
// O e-mail padrão do Supabase só entrega para membros da organização no Supabase, por isso não é usado.
import { createClient } from "jsr:@supabase/supabase-js@2";

const SITE = Deno.env.get("SITE_URL") ?? "https://tecnologiacomm.github.io/Central_notas/";
const CAIXA = Deno.env.get("CAIXA_NOTAS") ?? "prestacaocontasti@commcenter.com.br";
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const resposta = (corpo: unknown, status = 200) =>
  new Response(JSON.stringify(corpo), { status, headers: { ...cors, "Content-Type": "application/json" } });

async function tokenGraph(): Promise<string> {
  const tenant = Deno.env.get("GRAPH_TENANT_ID")!;
  const r = await fetch(`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token`, {
    method: "POST",
    body: new URLSearchParams({
      client_id: Deno.env.get("GRAPH_CLIENT_ID")!, client_secret: Deno.env.get("GRAPH_CLIENT_SECRET")!,
      scope: "https://graph.microsoft.com/.default", grant_type: "client_credentials",
    }),
  });
  const j = await r.json();
  if (!j.access_token) throw new Error("Login no Graph falhou: " + (j.error_description ?? r.status));
  return j.access_token;
}

async function enviarEmail(para: string, nome: string, link: string) {
  const html = `<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;color:#1a1a1a">
    <p>Olá, ${nome}.</p>
    <p>Recebemos um pedido para trocar a sua senha da <b>Central de Notas</b>.</p>
    <p style="margin:24px 0"><a href="${link}" style="background:#f2b824;color:#121212;padding:12px 22px;border-radius:10px;
      text-decoration:none;font-weight:700">Criar nova senha</a></p>
    <p style="color:#6b6b6b;font-size:13px">O link vale por 1 hora e só pode ser usado uma vez.
    Se não foi você que pediu, ignore este e-mail: sua senha atual continua valendo.</p></div>`;
  const r = await fetch(`https://graph.microsoft.com/v1.0/users/${CAIXA}/sendMail`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await tokenGraph()}`, "Content-Type": "application/json" },
    body: JSON.stringify({ message: { subject: "Central de Notas: troca de senha",
      body: { contentType: "HTML", content: html }, toRecipients: [{ emailAddress: { address: para } }] },
      saveToSentItems: false }),
  });
  if (!r.ok) throw new Error(`Graph sendMail ${r.status}: ${(await r.text()).slice(0, 300)}`);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return resposta({ erro: "método não permitido" }, 405);
  const ok = { ok: true, mensagem: "Se o e-mail estiver cadastrado, você vai receber o link em instantes." };
  try {
    const { email } = await req.json();
    const e = String(email ?? "").trim().toLowerCase();
    if (!/^[^@\s]+@commcenter\.com\.br$/.test(e)) return resposta(ok); // resposta igual: não revela quem existe

    const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
    const { data: perfil } = await sb.from("perfis").select("nome").eq("email", e).maybeSingle();
    if (!perfil) return resposta(ok);

    // no máximo 1 pedido a cada 2 minutos e 5 por dia, por e-mail
    const { data: recentes } = await sb.from("pedidos_senha").select("criado_em").eq("email", e)
      .gte("criado_em", new Date(Date.now() - 864e5).toISOString()).order("criado_em", { ascending: false });
    if (recentes && (recentes.length >= 5 || (recentes[0] && Date.now() - Date.parse(recentes[0].criado_em) < 120_000)))
      return resposta(ok);
    await sb.from("pedidos_senha").insert({ email: e });

    const { data, error } = await sb.auth.admin.generateLink({ type: "recovery", email: e });
    if (error || !data?.properties?.hashed_token) throw new Error(error?.message ?? "link não gerado");
    const link = `${SITE}?recuperar=${encodeURIComponent(data.properties.hashed_token)}`;
    await enviarEmail(e, String(perfil.nome || "").split(" ")[0] || "tudo bem", link);
    return resposta(ok);
  } catch (err) {
    console.error("esqueci-senha:", err instanceof Error ? err.message : err);
    return resposta({ ok: false, mensagem: "Não foi possível enviar agora. Tente de novo em alguns minutos ou fale com o Renan." }, 500);
  }
});
