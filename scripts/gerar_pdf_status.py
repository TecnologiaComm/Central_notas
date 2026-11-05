"""Gera docs/Central_de_Notas_Status_e_Proximos_Passos.pdf  —  python scripts/gerar_pdf_status.py docs/Central_de_Notas_Status_e_Proximos_Passos.pdf"""
import sys
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DV", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", F + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DVM", F + "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DVB", italic="DV", boldItalic="DVB")

AZUL, AZUL2, CINZA, LINHA = colors.HexColor("#1F3864"), colors.HexColor("#2E5597"), colors.HexColor("#667085"), colors.HexColor("#D0D5DD")
FUNDO, VERDE, AMAR = colors.HexColor("#F2F5FA"), colors.HexColor("#1A7F37"), colors.HexColor("#B54708")

st = {
    "h1": ParagraphStyle("h1", fontName="DVB", fontSize=15, textColor=AZUL, spaceBefore=6, spaceAfter=8, leading=19),
    "h2": ParagraphStyle("h2", fontName="DVB", fontSize=11.5, textColor=AZUL2, spaceBefore=10, spaceAfter=5, leading=15, keepWithNext=1),
    "p": ParagraphStyle("p", fontName="DV", fontSize=9.5, leading=13.5, spaceAfter=5, alignment=TA_LEFT),
    "sub": ParagraphStyle("sub", fontName="DV", fontSize=8.5, leading=12, textColor=CINZA),
    "cel": ParagraphStyle("cel", fontName="DV", fontSize=8.5, leading=11.5),
    "celb": ParagraphStyle("celb", fontName="DVB", fontSize=8.5, leading=11.5),
    "cab": ParagraphStyle("cab", fontName="DVB", fontSize=8.5, leading=11.5, textColor=colors.white),
    "bul": ParagraphStyle("bul", fontName="DV", fontSize=9.5, leading=13.5, leftIndent=12, bulletIndent=2, spaceAfter=2),
    "code": ParagraphStyle("code", fontName="DVM", fontSize=8, leading=11, backColor=FUNDO, borderPadding=5,
                           leftIndent=4, spaceBefore=3, spaceAfter=7),
}


def P(t, s="p"):
    return Paragraph(t, st[s])


def B(itens):
    return [Paragraph(i, st["bul"], bulletText="•") for i in itens]


def tabela(cab, linhas, larguras, destaque_col0=False):
    dados = [[P(c, "cab") for c in cab]]
    for l in linhas:
        dados.append([P(c, "celb" if (destaque_col0 and i == 0) else "cel") for i, c in enumerate(l)])
    t = Table(dados, colWidths=larguras, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINHA), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FUNDO]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def caixa(texto, cor=AZUL2):
    t = Table([[P(texto, "cel")]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, cor), ("BACKGROUND", (0, 0), (-1, -1), FUNDO),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def rodape(c, doc):
    c.saveState()
    c.setFont("DV", 7.5)
    c.setFillColor(CINZA)
    c.drawString(18 * mm, 10 * mm, "Central de Notas – Comm · Status do projeto e próximos passos")
    c.drawRightString(192 * mm, 10 * mm, f"Página {doc.page}")
    c.restoreState()


def capa(c, doc):
    c.saveState()
    c.setFillColor(AZUL)
    c.rect(0, A4[1] - 70 * mm, A4[0], 70 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("DVB", 24)
    c.drawString(18 * mm, A4[1] - 32 * mm, "Central de Notas – Comm")
    c.setFont("DV", 13)
    c.drawString(18 * mm, A4[1] - 42 * mm, "Prestação de Contas TI · Status do projeto e próximos passos")
    c.setFont("DV", 9.5)
    c.drawString(18 * mm, A4[1] - 54 * mm, f"Atualizado em {date.today():%d/%m/%Y} · Repositório TecnologiaComm/Central_notas "
                                            "(branch main)")
    c.restoreState()
    rodape(c, doc)


W = [174 * mm]
s = [Spacer(1, 62 * mm)]

# ---------------------------------------------------------------- 1. Resumo
s += [P("1. Resumo", "h1"),
      P("O app lê a caixa <b>prestacaocontasti@commcenter.com.br</b>, separa os anexos (NF, FT, XML, boleto e memória "
        "de cálculo), renomeia os arquivos no padrão do time, pré-preenche a linha da planilha, pede o “de acordo” ao "
        "Robson e controla PC, chamado e status até a NF ser lançada. O analista passa de <b>fazer</b> para "
        "<b>conferir e aprovar</b>."),
      tabela(["Parte", "Situação"], [
          ["App (fase 1): caixa, anexos, nomenclatura, planilha, sugestões, alertas, aprovação",
           "<font color='#1A7F37'><b>Pronto</b></font> · testado em modo demo"],
          ["Versão Azure: login Microsoft, SharePoint, carga pela web, publicação automática",
           "<font color='#B54708'><b>Código pronto</b></font> · falta criar os recursos e configurar"],
          ["Código no GitHub", "<font color='#1A7F37'><b>Na main</b></font> · pull request #1 aprovado; testes do GitHub Actions passando"],
          ["Testes automáticos", "13 testes passando (fluxo completo, regras, login, SharePoint, carga)"],
          ["Ambiente real (M365, Azure, SharePoint)", "<font color='#B54708'><b>Não configurado</b></font> · app ainda não está no ar"],
      ], [112 * mm, 62 * mm]),
      Spacer(1, 6),
      caixa("<b>Importante:</b> nada foi testado ainda com a caixa real, o Azure real ou o SharePoint real. "
            "Os testes usam simuladores. Os próximos passos (seção 4) são justamente ligar cada peça ao ambiente da Comm.",
            AMAR)]

# ---------------------------------------------------------------- 2. Processo
s += [P("2. Como era × como fica", "h1"),
      tabela(["#", "Hoje (manual)", "No app"], [
          ["1", "Verificar o e-mail procurando notas novas", "<b>Automático</b>: verificação a cada 5 min (ou botão “Verificar e-mails agora”)."],
          ["2", "Identificar se é nota, boleto ou memória de cálculo", "<b>Automático</b>: classifica cada anexo e junta NF, XML, boleto e MC da mesma nota."],
          ["3", "Salvar e renomear os arquivos", "<b>Automático</b>: PRESTADOR_NFouFT_NÚMERO_EMPRESA (+ _BOLETO / _MC) em &lt;EMPRESA&gt;/&lt;AAAA-MM&gt;/ e cópia no SharePoint."],
          ["4", "Preencher a linha da planilha", "<b>Semiautomático</b>: empresa/filial pelo CNPJ do tomador; prestador e código Protheus pelo CNPJ do prestador; despesa, produto, CC e conta pelo histórico. O analista confere."],
          ["5", "Enviar e-mail pedindo aprovação", "<b>Um clique</b>: e-mail ao Robson com anexos e botões “De acordo / Não de acordo” (ou ele responde “De acordo”)."],
          ["6", "Lançar no Protheus", "<b>Continua manual</b>: depois do “de acordo”, o analista lança no Protheus e registra no app PC, chamado, status e data. Com “NF LANÇADA”, a nota sai da fila."],
      ], [8 * mm, 58 * mm, 108 * mm]),
      P("Fluxo de etapas da nota", "h2"),
      P("Em conferência → Aguardando aprovação → Aprovada / Reprovada → NF lançada  (ou Ignorada, quando não é nota)", "code"),
      P("Alertas automáticos", "h2")]
s += B(["<b>Duplicidade</b>: mesma chave de acesso, ou mesma NFS do mesmo prestador no app ou na planilha antiga.",
        "<b>Fornecedor</b>: CNPJ sem cadastro ou sem código Protheus para aquela empresa.",
        "<b>Empresa/filial</b> não identificada pelo CNPJ do tomador.",
        "<b>Prazos e valores</b>: vencimento em até 3 dias, boleto com valor diferente da nota, campos não lidos."])

# ---------------------------------------------------------------- 3. O que foi feito
s += [Spacer(1, 6), P("3. O que já foi feito", "h1"),
      P("3.1 Aplicativo (fase 1)", "h2")]
s += B(["Leitura da caixa pelo <b>Microsoft Graph</b> (permissões de aplicativo, restritas à caixa da prestação de contas).",
        "Leitura dos dados: <b>XML</b> de NF-e/NFS-e › <b>PDF</b> (texto e linha digitável do boleto) › <b>IA opcional</b> para PDFs sem XML.",
        "Nomenclatura e pastas no padrão do time; agrupamento de anexos que chegam em e-mails diferentes.",
        "Sugestões a partir do histórico (cerca de 730 lançamentos de jul/25 a nov/26 da planilha atual).",
        "Pedido de “de acordo” com links assinados (o Safe Links do Outlook não aprova sozinho) e leitura das respostas por e-mail.",
        "<b>Planilha</b> com uma aba por mês nas mesmas 17 colunas de hoje + aba “Controle app”; cópia sempre atualizada."])
s += [P("3.2 Versão Azure", "h2")]
s += B(["<b>Login com a conta Microsoft da Comm</b>: o histórico registra o e-mail real de quem conferiu e aprovou; "
        "lista opcional de usuários permitidos.",
        "<b>SharePoint</b>: arquivos renomeados e a planilha CONTROLE_NOTAS.xlsx copiados para a biblioteca; reenvio automático se falhar.",
        "<b>Dados persistentes</b> em /home/data (banco, arquivos e carga), que não se perdem nas publicações.",
        "Tela <b>“Carga da planilha”</b>: importa a planilha atual pelo navegador.",
        "<b>Publicação automática</b>: GitHub Actions roda os testes e publica no App Service a cada alteração na main.",
        "Script <b>azure/provisionar.sh</b> cria tudo no Azure com um comando; passo a passo completo no README."])
s += [Spacer(1, 4), P("Arquitetura", "h2"),
      P("GitHub (main) ──▶ GitHub Actions: testes ──▶ Azure App Service (B1 Linux, Always On)<br/>"
        "&nbsp;&nbsp;├─ login Microsoft (Entra ID)<br/>"
        "&nbsp;&nbsp;├─ Microsoft Graph: caixa prestacaocontasti@ (ler e enviar)<br/>"
        "&nbsp;&nbsp;├─ Microsoft Graph: SharePoint (arquivos e planilha)<br/>"
        "&nbsp;&nbsp;└─ /home/data: banco SQLite + arquivos", "code")]

# ---------------------------------------------------------------- 4. O que precisamos fazer
CK = "☐"
s += [Spacer(1, 6), P("4. O que precisamos fazer", "h1"),
      P("Em ordem. Cada bloco indica quem faz. Os detalhes técnicos (comandos e telas) estão no README do repositório, "
        "seção “Publicar no Azure”.", "sub"), Spacer(1, 4)]


def bloco(titulo, quem, itens):
    linhas = [[P(CK, "celb"), P(i, "cel")] for i in itens]
    t = Table(linhas, colWidths=[7 * mm, 167 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINHA),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return KeepTogether([P(f"{titulo} <font color='#667085' size='8.5'>· {quem}</font>", "h2"), t])


s += [bloco("Passo 1 – Decidir os nomes e valores", "Renan / time administrativo", [
    "Nome do site no Azure (ex.: <b>central-notas-comm</b> → https://central-notas-comm.azurewebsites.net).",
    "Site e biblioteca do SharePoint para as notas (ex.: “Prestação de Contas TI” / “Documentos” / pasta “Notas”).",
    "Quem pode entrar no app (lista de e-mails ou grupo) e se a regra de aprovação continua só o Robson.",
    "<s>Juntar a branch na main</s> — <font color='#1A7F37'><b>feito</b></font> (pull request #1)."]),
      bloco("Passo 2 – Registro do app no Microsoft 365", "Admin do M365 / TI", [
    "Criar o registro “Central de Notas” (somente este diretório) e anotar <b>Tenant ID</b> e <b>Client ID</b>.",
    "Permissões de aplicativo do Graph: <b>Mail.ReadWrite</b>, <b>Mail.Send</b>, <b>Sites.Selected</b> + consentimento do administrador.",
    "Criar o <b>segredo do cliente</b> (anotar o valor e a data de expiração).",
    "Autenticação Web: URI <b>https://&lt;app&gt;.azurewebsites.net/.auth/login/aad/callback</b> e “Tokens de ID” marcado.",
    "PowerShell: restringir o app à caixa prestacaocontasti@ (ApplicationAccessPolicy).",
    "PowerShell: dar escrita só no site das notas (New-MgSitePermission).",
    "Opcional: “Atribuição necessária = Sim” e adicionar o time e o Robson ao app."]),
      bloco("Passo 3 – Criar os recursos no Azure", "TI (com acesso à assinatura Azure)", [
    "Confirmar se a Comm já tem assinatura do Azure (senão, criar com o admin do M365).",
    "No Azure Cloud Shell: <b>TENANT_ID=… CLIENT_ID=… APP=central-notas-comm bash azure/provisionar.sh</b>",
    "Em Configurações do App Service: <b>GRAPH_CLIENT_SECRET</b>, <b>MICROSOFT_PROVIDER_AUTHENTICATION_SECRET</b>, "
    "<b>SHAREPOINT_SITE</b> e, se quiser, <b>USUARIOS_PERMITIDOS</b> e <b>ANTHROPIC_API_KEY</b>.",
    "Conferir o valor mensal do plano B1 na página de preços do App Service."]),
      bloco("Passo 4 – Ligar o GitHub ao Azure", "Quem administra o GitHub da TecnologiaComm", [
    "Baixar o perfil de publicação do App Service.",
    "No GitHub (Settings → Secrets and variables → Actions): segredo <b>AZURE_WEBAPP_PUBLISH_PROFILE</b> e variável <b>AZURE_WEBAPP_NAME</b>.",
    "Rodar de novo o workflow (aba Actions → “Testar e publicar no Azure” → Run workflow) e conferir que a publicação ficou verde."]),
      bloco("Passo 5 – Primeiro uso", "Time administrativo", [
    "Entrar no site com a conta da Comm.",
    "Menu “Carga da planilha”: enviar a planilha atual (aba Infos + abas mensais).",
    "“Verificar e-mails agora” e conferir as primeiras notas (empresa, filial, fornecedor, CC, conta).",
    "Rodar <b>alguns dias só conferindo</b>, sem pedir “de acordo”, e anotar o que precisar ajustar.",
    "Depois, liberar o envio do “de acordo” ao Robson."])]

# ---------------------------------------------------------------- 5. Atenção
s += [P("5. Pontos de atenção", "h1"),
      tabela(["Ponto", "O que fazer"], [
          ["Valores de exemplo", "Nome do site SharePoint e da biblioteca são exemplos: confirmar antes de usar."],
          ["Uma instância só", "Não ligar escala horizontal no App Service: a verificação da caixa roda dentro do app."],
          ["Banco", "SQLite em /home/data atende o volume atual. Se crescer, migrar para Azure SQL ou PostgreSQL (DATABASE_URL)."],
          ["Segredo do cliente", "Tem validade: anotar a data e renovar antes de vencer (senão o app para de ler a caixa)."],
          ["Anexos grandes", "O envio de e-mail pelo Graph aceita anexos de até ~3 MB cada."],
          ["Backup", "Ativar Backups do App Service (cobre /home/data)."],
      ], [42 * mm, 132 * mm], destaque_col0=True)]

# ---------------------------------------------------------------- 6. Cronograma
s += [P("6. Cronograma sugerido", "h1"),
      tabela(["Quando", "O quê", "Quem"], [
          ["Semana 1", "Passos 1 a 4: decisões, registro no M365, Azure e GitHub", "TI + Renan"],
          ["Semana 2", "Passo 5: carga da planilha e alguns dias só conferindo a caixa real", "Time administrativo"],
          ["Semana 3", "Ajustes do que apareceu na conferência; liberar o “de acordo” ao Robson e usar no dia a dia", "Renan + Robson"],
      ], [26 * mm, 108 * mm, 40 * mm], destaque_col0=True)]

doc = SimpleDocTemplate(sys.argv[1], pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                        bottomMargin=18 * mm, title="Central de Notas – Status e próximos passos",
                        author="TecnologiaComm")
doc.build(s, onFirstPage=capa, onLaterPages=rodape)
