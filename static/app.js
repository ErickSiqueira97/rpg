const statusEl = document.querySelector("#status");
const authEl = document.querySelector("#auth");
const lobbyEl = document.querySelector("#lobby");
const jogoEl = document.querySelector("#jogo");
const logEl = document.querySelector("#log");
const fichaDialog = document.querySelector("#ficha-dialog");
let token = localStorage.getItem("token") || "";
let sagaId = "";
let fichaAtual = null;
let jogadorId = "";
let ultimoTextoQuero = "";

function say(text) {
  statusEl.textContent = text || "";
}

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch(path, Object.assign({}, options, { headers }));
  const type = response.headers.get("content-type") || "";
  if (type.includes("text/event-stream")) return response;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.mensagem || "Falha na requisição.");
    error.data = data;
    error.status = response.status;
    throw error;
  }
  return data;
}

function atributos() {
  const names = ["forca", "agilidade", "vigor", "percepcao", "intelecto", "essencia"];
  const values = {};
  names.forEach((name) => {
    values[name] = Number(document.getElementById(name).value);
  });
  return values;
}

const CUSTO = { 8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9 };
let bonusOrigem = { forca: 2, agilidade: 1 };

function custoCompra() {
  return Object.values(atributos()).reduce((sum, value) => sum + (CUSTO[value] || 0), 0);
}

function atualizarPontos() {
  document.querySelector("#pontos").textContent = "Pontos usados: " + custoCompra() + " / 27";
  document.querySelectorAll("[data-bonus]").forEach((button) => {
    button.textContent = "+" + (bonusOrigem[button.dataset.bonus] || 0);
  });
}

document.querySelectorAll("[data-attr]").forEach((input) => {
  input.addEventListener("input", atualizarPontos);
});

let catalogo = null;

function preencherSelecao(select, items, label) {
  select.replaceChildren();
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = typeof item === "string" ? item : item.id;
    option.textContent = label(item);
    select.append(option);
  });
}

async function prepararCatalogo() {
  if (!catalogo) catalogo = await api("/api/catalogo");
  preencherSelecao(document.querySelector("#raca"), catalogo.racas, (item) => item.nome);
  preencherSelecao(document.querySelector("#origem-id"), catalogo.origens, (item) => item.nome);
  preencherSelecao(document.querySelector("#classe"), catalogo.classes, (item) => item.nome);
  preencherSelecao(document.querySelector("#via"), [{ id: "", nome: "Sem Via (opcional: escolha uma)" }, ...catalogo.vias], (item) => item.nome);
  preencherSelecao(document.querySelector("#traco"), [{ id: "", nome: "Nenhum" }, ...catalogo.tracos], (item) => item.nome);
  sincronizarClasse();
  sincronizarOrigem();
  sincronizarRaca();
  atualizarPontos();
}

function sincronizarClasse() {
  const classe = catalogo.classes.find((item) => item.id === document.querySelector("#classe").value);
  preencherSelecao(document.querySelector("#subclasse"), (classe.subclasses || []).map((nome) => ({ id: nome, nome })), (item) => item.nome);
}

function sincronizarOrigem(manterBonus) {
  const origem = catalogo.origens.find((item) => item.id === document.querySelector("#origem-id").value);
  document.querySelector("#origem").value = origem.nome;
  if (!manterBonus) {
    bonusOrigem = {};
    bonusOrigem[origem.atributos[0]] = 2;
    bonusOrigem[origem.atributos[1]] = 1;
  }
  document.querySelectorAll("[data-bonus]").forEach((button) => {
    button.disabled = !origem.atributos.includes(button.dataset.bonus);
  });
  atualizarPontos();
  atualizarDicaVia();
}

function sincronizarRaca() {
  const raca = catalogo.racas.find((item) => item.id === document.querySelector("#raca").value);
  const select = document.querySelector("#variante");
  select.replaceChildren();
  (raca.variantes || ["—"]).forEach((nome) => {
    const option = document.createElement("option");
    option.value = nome;
    option.textContent = nome;
    select.append(option);
  });
  select.hidden = !raca.variantes;
  select.previousElementSibling.hidden = !raca.variantes;
}

document.querySelector("#classe").addEventListener("change", sincronizarClasse);
document.querySelector("#origem-id").addEventListener("change", sincronizarOrigem);
document.querySelector("#raca").addEventListener("change", sincronizarRaca);

function moverBonus(attr) {
  const origem = catalogo.origens.find((item) => item.id === document.querySelector("#origem-id").value);
  if (!origem.atributos.includes(attr)) return;
  const plus2 = Object.keys(bonusOrigem).find((name) => bonusOrigem[name] === 2);
  const plus1 = Object.keys(bonusOrigem).find((name) => bonusOrigem[name] === 1);
  if (attr === plus2) return;
  const next = {};
  if (attr === plus1 && plus2) {
    next[attr] = 2;
    next[plus2] = 1;
  } else {
    next[attr] = 2;
    const keep = plus1 || plus2;
    if (keep && keep !== attr) next[keep] = 1;
  }
  bonusOrigem = next;
  atualizarPontos();
}

function atualizarDicaVia(data) {
  const dica = document.querySelector("#via-dica");
  const vazia = !document.querySelector("#via").value;
  dica.hidden = !vazia;
  if (!vazia) return;
  let texto = "Classes marciais podem escolher uma Via para ganhar Pontos de Energia.";
  const sugerida = data && data.viaSugerida;
  if (sugerida) {
    const via = catalogo.vias.find((item) => item.id === sugerida);
    if (via) texto += " Para esta ficha, " + via.nome + " combina, mas Sem Via também vale.";
  }
  dica.textContent = texto;
}

document.querySelector("#via").addEventListener("change", () => atualizarDicaVia(window.sugestaoAtual));

document.querySelectorAll("[data-bonus]").forEach((button) => {
  button.addEventListener("click", () => moverBonus(button.dataset.bonus));
});

function mostrarOpcoesArquetipo(opcoes) {
  const container = document.querySelector("#arquetipo-opcoes");
  container.replaceChildren();
  opcoes.forEach((opcao) => {
    const button = document.createElement("button");
    button.type = "button";
    const name = document.createElement("strong");
    name.textContent = opcao.nome;
    const description = document.createElement("span");
    description.textContent = opcao.descricao;
    button.append(name, description);
    button.addEventListener("click", () => resolverQuero({ arquetipo_id: opcao.id }).catch((error) => say(error.message)));
    container.append(button);
  });
  container.hidden = false;
}

function preencherFichaSugerida(data) {
  document.querySelector("#nome").value = data.nome;
  document.querySelector("#conceito").value = data.conceito || "";
  document.querySelector("#raca").value = data.raca;
  sincronizarRaca();
  if (data.variante) document.querySelector("#variante").value = data.variante;
  document.querySelector("#classe").value = data.classe;
  sincronizarClasse();
  document.querySelector("#subclasse").value = data.subclasse;
  if (data.origemId) document.querySelector("#origem-id").value = data.origemId;
  if (data.atributos) {
    Object.entries(data.atributos).forEach(([name, value]) => {
      const input = document.getElementById(name);
      if (input) input.value = value;
    });
  }
  if (data.bonusOrigem) bonusOrigem = Object.assign({}, data.bonusOrigem);
  sincronizarOrigem(Boolean(data.bonusOrigem));
  document.querySelector("#via").value = data.via || "";
  document.querySelector("#traco").value = data.traco || "";
  window.sugestaoAtual = data;
  atualizarDicaVia(data);
  document.querySelector("#arquetipo-opcoes").hidden = true;
  document.querySelector("#nao-e-isso").hidden = !data.podeCorrigir;
  const stages = {
    apelido: "Arquétipo reconhecido pelo apelido.",
    aprendido: "Sugestão baseada na sua escolha anterior.",
    llm: "Arquétipo sugerido para o conceito.",
    botoes: "Arquétipo escolhido.",
  };
  document.querySelector("#quero-resultado").textContent =
    "Sugestão: " + data.nome + ". " + (stages[data.fonte] || "") + " O nome pedido não entra na ficha.";
}

async function resolverQuero(extra = {}) {
  if (!catalogo) await prepararCatalogo();
  const input = document.querySelector("#quero-texto").value.trim();
  ultimoTextoQuero = "quero ser " + input;
  const data = await api("/api/quero", {
    method: "POST",
    body: JSON.stringify(Object.assign({ texto: ultimoTextoQuero }, extra)),
  });
  if (data.precisaEscolha) {
    document.querySelector("#arquetipo-opcoes").hidden = true;
    mostrarOpcoesArquetipo(data.opcoes || []);
    document.querySelector("#nao-e-isso").hidden = true;
    document.querySelector("#quero-resultado").textContent =
      "Não encontramos uma correspondência confiável. Escolha um arquétipo; nenhum atributo será gerado pela IA.";
    return;
  }
  preencherFichaSugerida(data);
}

document.querySelector("#quero").addEventListener("click", () => {
  resolverQuero().catch((error) => say(error.message));
});

document.querySelector("#nao-e-isso").addEventListener("click", async () => {
  try {
    const data = await api("/api/quero", {
      method: "POST",
      body: JSON.stringify({ texto: ultimoTextoQuero, nao_e_isso: true }),
    });
    mostrarOpcoesArquetipo(data.opcoes || []);
    document.querySelector("#nao-e-isso").hidden = true;
    document.querySelector("#quero-resultado").textContent = "Aprendizado removido. Escolha o arquétipo correto.";
  } catch (error) {
    say(error.message);
  }
});

document.querySelectorAll("[data-step]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.step);
    const next = Number(input.value) + Number(button.dataset.dir);
    if (next < 8 || next > 15) return;
    input.value = String(next);
    atualizarPontos();
  });
});

async function entrar(path) {
  const data = await api(path, {
    method: "POST",
    body: JSON.stringify({
      usuario: document.querySelector("#usuario").value.trim(),
      senha: document.querySelector("#senha").value,
    }),
  });
  token = data.token;
  localStorage.setItem("token", token);
  say("");
  await abrirJogo(data.jogador);
}

document.querySelector("#auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  entrar("/api/entrar").catch((error) => say(error.message));
});

document.querySelector("#cadastrar").addEventListener("click", () => {
  entrar("/api/cadastro").catch((error) => say(error.message));
});

document.querySelector("#sair").addEventListener("click", () => {
  token = "";
  sagaId = "";
  jogadorId = "";
  localStorage.removeItem("token");
  localStorage.removeItem("sagaId");
  jogoEl.hidden = true;
  lobbyEl.hidden = true;
  authEl.hidden = false;
  say("Você saiu.");
});

function mostrarJogador(jogador) {
  jogadorId = jogador.id;
  const limite = jogador.turnosLimite == null ? "sem teto" : jogador.turnosUsados + "/" + jogador.turnosLimite;
  const teste = jogador.plano === "trial" ? " · teste: " + jogador.diasDeTeste + " dia(s)" : "";
  const texto = "Plano " + jogador.plano + " · turnos hoje " + limite + teste;
  document.querySelector("#meta").textContent = texto;
  document.querySelector("#meta-jogo").textContent = texto;
}

function mostrarLobby() {
  authEl.hidden = true;
  jogoEl.hidden = true;
  lobbyEl.hidden = false;
}

async function abrirJogo(jogador) {
  authEl.hidden = true;
  if (!jogador) jogador = await api("/api/eu");
  mostrarJogador(jogador);
  await carregarFichas();
  const sagas = await carregarSagas();
  const escolhida = escolherSaga(sagas, localStorage.getItem("sagaId"));
  const salva = localStorage.getItem("sagaId");
  if (salva && escolhida && escolhida.id === salva) {
    await abrirSaga(escolhida.id);
    return;
  }
  mostrarLobby();
}

async function carregarFichas() {
  const fichas = await api("/api/personagens");
  const select = document.querySelector("#personagem-escolha");
  const grade = document.querySelector("#personagens");
  if (select) select.replaceChildren();
  grade.replaceChildren();
  const treino = document.querySelector("#treino-personagem");
  if (treino) treino.replaceChildren();
  fichas.forEach((ficha) => {
    if (select) {
      const option = document.createElement("option");
      option.value = ficha.id;
      option.textContent = ficha.nome + " · " + ficha.arquetipo;
      select.append(option);
    }
    const card = document.createElement("article");
    card.className = "card";
    const titulo = document.createElement("h3");
    titulo.textContent = ficha.nome;
    const arq = document.createElement("p");
    arq.textContent = ficha.arquetipo;
    const vida = document.createElement("p");
    vida.textContent = "Vida " + ficha.vida + "/" + ficha.vidaMax;
    const jogar = document.createElement("button");
    jogar.type = "button";
    jogar.textContent = "Nova missão";
    jogar.addEventListener("click", () => criarMissao(ficha.id).catch((error) => say(error.message)));
    card.append(titulo, arq, vida, jogar);
    card.dataset.id = ficha.id;
    grade.append(card);
    const option = document.createElement("option");
    option.value = ficha.id;
    option.textContent = ficha.nome;
    document.querySelector("#treino-personagem").append(option);
  });
  return fichas;
}

function escolherSaga(sagas, salvaId) {
  if (!sagas || !sagas.length) return null;
  const unicas = [];
  const vistas = new Set();
  sagas.forEach((saga) => {
    if (vistas.has(saga.id)) return;
    vistas.add(saga.id);
    unicas.push(saga);
  });
  return unicas.find((saga) => saga.id === salvaId) || unicas[0];
}

function cartaoAventura(saga, arquivar) {
  const card = document.createElement("article");
  card.className = "card";
  const titulo = document.createElement("h3");
  titulo.textContent = saga.titulo;
  const quem = document.createElement("p");
  quem.textContent = saga.personagemNome || "Personagem";
  const quando = document.createElement("p");
  const data = saga.atualizadaEm ? new Date(saga.atualizadaEm * 1000).toLocaleString("pt-BR") : "";
  quando.textContent = (saga.objetivoStatus || "ativa") + (data ? " · " + data : "");
  card.append(titulo, quem, quando);
  if (!arquivar) {
    const abrir = document.createElement("button");
    abrir.type = "button";
    abrir.dataset.id = saga.id;
    abrir.textContent = "Continuar";
    abrir.addEventListener("click", () => abrirSaga(saga.id).catch((error) => say(error.message)));
    card.append(abrir);
  } else {
    const guardar = document.createElement("button");
    guardar.type = "button";
    guardar.textContent = "Arquivar";
    guardar.addEventListener("click", () => arquivarSaga(saga.id).catch((error) => say(error.message)));
    card.append(guardar);
  }
  return card;
}

async function carregarSagas() {
  const sagas = await api("/api/sagas");
  const ativas = document.querySelector("#aventuras");
  const vazias = document.querySelector("#aventuras-vazias");
  ativas.replaceChildren();
  vazias.replaceChildren();
  const vistas = new Set();
  sagas.forEach((saga) => {
    if (vistas.has(saga.id)) return;
    vistas.add(saga.id);
    if (saga.vazia) vazias.append(cartaoAventura(saga, true));
    else ativas.append(cartaoAventura(saga, false));
  });
  document.querySelector("#vazias").hidden = vazias.childElementCount === 0;
  return sagas;
}

async function criarMissao(personagemId) {
  const saga = await api("/api/sagas", {
    method: "POST",
    body: JSON.stringify({ personagemId: personagemId }),
  });
  await carregarSagas();
  await abrirSaga(saga.id);
  if (!saga.mensagens || saga.mensagens.length === 0) {
    await enviarTurno({ abertura: true });
  }
}

async function arquivarSaga(id) {
  await api("/api/sagas/" + id + "/arquivar", { method: "POST", body: "{}" });
  if (sagaId === id) {
    sagaId = "";
    localStorage.removeItem("sagaId");
  }
  await carregarSagas();
  say("Missão arquivada.");
}

document.querySelector("#abrir-ficha").addEventListener("click", () => {
  prepararCatalogo().then(() => {
    fichaDialog.showModal();
    document.querySelector("#nome").focus();
  }).catch((error) => say(error.message));
});
document.querySelector("#fechar-ficha").addEventListener("click", () => fichaDialog.close());

document.querySelector("#ficha").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await api("/api/personagens", {
      method: "POST",
      body: JSON.stringify({
        nome: document.querySelector("#nome").value,
        origem: document.querySelector("#origem").value,
        origemId: document.querySelector("#origem-id").value,
        arquetipo: document.querySelector("#classe").selectedOptions[0].textContent,
        classe: document.querySelector("#classe").value,
        subclasse: document.querySelector("#subclasse").value,
        raca: document.querySelector("#raca").value,
        via: document.querySelector("#traco").value === "nulo" ? "" : document.querySelector("#via").value,
        traco: document.querySelector("#traco").value,
        conceito: document.querySelector("#conceito").value,
        atributos: atributos(),
        bonusOrigem: bonusOrigem,
      }),
    });
    fichaDialog.close();
    say("Ficha criada.");
    await carregarFichas();
  } catch (error) {
    say(error.message);
  } finally {
    button.disabled = false;
  }
});

async function lutar(path) {
  const personagem = document.querySelector("#treino-personagem").value;
  if (!personagem) {
    say("Crie um personagem antes de treinar.");
    return;
  }
  const aulaKey = "treino-aula-vista:" + jogadorId;
  const aula = path.endsWith("professor") && localStorage.getItem(aulaKey) !== "true";
  const data = await api(path, {
    method: "POST",
    body: JSON.stringify({
      personagemId: personagem,
      nivel: Number(document.querySelector("#treino-nivel").value),
      dificuldade: document.querySelector("#treino-dif").value,
      oponente: document.querySelector("#treino-tipo").value,
      aula: aula,
    }),
  });
  if (aula) localStorage.setItem(aulaKey, "true");
  document.querySelector("#treino-log").textContent = data.resultado + "\n" + (data.linhas || []).join("\n");
  say(data.resultado);
}

document.querySelector("#treinar").addEventListener("click", () => {
  lutar("/api/professor").catch((error) => say(error.message));
});
document.querySelector("#arena").addEventListener("click", () => {
  lutar("/api/arena").catch((error) => say(error.message));
});

document.querySelector("#comprar").addEventListener("click", async () => {
  if (!sagaId) return;
  try {
    const data = await api("/api/sagas/" + sagaId + "/loja", {
      method: "POST",
      body: JSON.stringify({ item: document.querySelector("#loja-item").value }),
    });
    say((data.linhas || []).join(" "));
    if (data.mundo) document.querySelector("#mundo").textContent = resumoMundo(data.mundo);
  } catch (error) {
    say(error.message);
  }
});

document.querySelector("#subir").addEventListener("click", async () => {
  if (!fichaAtual) return;
  try {
    fichaAtual = await api("/api/personagens/" + fichaAtual.id + "/subir", {
      method: "POST",
      body: JSON.stringify({ modo: "um", atributo: document.querySelector("#asi").value }),
    });
    say("Nível atualizado.");
    const saga = await api("/api/sagas/" + sagaId);
    preencherPainel(saga.mundo, saga.resumo, fichaAtual);
  } catch (error) {
    say(error.message);
  }
});

document.querySelector("#rito").addEventListener("click", async () => {
  if (!fichaAtual) return;
  try {
    fichaAtual = await api("/api/personagens/" + fichaAtual.id + "/rito", { method: "POST", body: "{}" });
    say("Estágio " + (fichaAtual.estagio || (fichaAtual.ficha && fichaAtual.ficha.estagio)));
  } catch (error) {
    say(error.message);
  }
});

document.querySelector("#inicio").addEventListener("click", async () => {
  mostrarLobby();
  await carregarSagas();
  await carregarFichas();
});

function mostrarErro(node, message) {
  node.className = "erro-chat";
  node.textContent = message;
  say(message);
}

function erroNoLog(message) {
  const node = paragrafo("erro-chat", message);
  logEl.append(node);
  say(message);
}

function paragrafo(className, text) {
  const el = document.createElement("p");
  el.className = className;
  el.textContent = text;
  return el;
}

async function abrirSaga(id) {
  const saga = await api("/api/sagas/" + id);
  sagaId = saga.id;
  localStorage.setItem("sagaId", saga.id);
  fichaAtual = (await api("/api/personagens")).find((item) => item.id === saga.personagemId) || null;
  authEl.hidden = true;
  lobbyEl.hidden = true;
  jogoEl.hidden = false;
  document.querySelector("#saga-titulo").textContent = saga.titulo;
  logEl.replaceChildren();
  saga.mensagens.forEach((mensagem) => {
    const mine = mensagem.papel === "player";
    logEl.append(paragrafo(mine ? "jogador" : "narrador", (mine ? "Você: " : "") + mensagem.texto));
  });
  document.querySelector("#objetivo").textContent = textoObjetivo(saga);
  document.querySelector("#mundo").textContent = resumoMundo(saga.mundo);
  preencherPainel(saga.mundo, saga.resumo, fichaAtual);
  document.querySelector("#comecar").hidden = saga.mensagens.length > 0;
  say("");
  logEl.focus();
}

function textoObjetivo(data) {
  if (!data || !data.objetivo) return "";
  const status = data.objetivoStatus && data.objetivoStatus !== "ativa" ? data.objetivoStatus + " — " : "";
  let line = "Objetivo: " + status + data.objetivo;
  if (data.objetivoOriginal && data.objetivoOriginal !== data.objetivo) {
    line += " (fim do roteiro: " + data.objetivoOriginal + ")";
  }
  return line;
}

function resumoMundo(mundo) {
  const stars = mundo.procurado ? " · procurado " + mundo.procurado : "";
  const runas = mundo.runas ? " · " + mundo.runas + " runas" : "";
  return "Lugar: " + (mundo.lugar || "—") + " · " + (mundo.quando || "—") + stars + runas;
}

function preencherPainel(mundo, resumo, ficha) {
  const npcs = document.querySelector("#npcs");
  npcs.replaceChildren();
  (mundo.npcs || []).forEach((npc) => {
    const item = document.createElement("li");
    item.textContent = npc.nome + (npc.notas ? " — " + npc.notas : "");
    npcs.append(item);
  });
  if (!npcs.childElementCount) {
    const item = document.createElement("li");
    item.textContent = "Nenhum NPC conhecido.";
    npcs.append(item);
  }
  const itens = document.querySelector("#inventario");
  itens.replaceChildren();
  (mundo.inventario || []).forEach((nome) => {
    const item = document.createElement("li");
    item.textContent = nome;
    itens.append(item);
  });
  document.querySelector("#inventario-vazio").hidden = itens.childElementCount > 0;
  const diario = document.querySelector("#diario");
  diario.replaceChildren();
  String(resumo || "").split("\n").map((linha) => linha.replace(/^\s*-\s*/, "").trim()).filter(Boolean).forEach((linha) => {
    const item = document.createElement("li");
    item.textContent = linha;
    diario.append(item);
  });
  document.querySelector("#diario-vazio").hidden = diario.childElementCount > 0;
  if (!ficha) return;
  const extra = ficha.ficha || {};
  document.querySelector("#ficha-resumo").textContent = ficha.nome + " · " + ficha.arquetipo + " · nível " + (ficha.nivel || 1);
  document.querySelector("#ficha-extra").textContent = [
    "PE " + (mundo.pe != null ? mundo.pe : extra.peMax || 0) + "/" + (mundo.peMax || extra.peMax || 0),
    extra.subclasse || "",
    "estágio " + (extra.estagio || 0),
    (mundo.formas || []).map((forma) => forma.nome).join(", "),
  ].filter(Boolean).join(" · ");
  const pendente = Boolean(ficha.pendente);
  document.querySelector("#subir").hidden = !pendente;
  document.querySelector("#asi").hidden = !pendente;
  document.querySelector("#asi-rotulo").hidden = !pendente;
  document.querySelector("#rito").hidden = !(extra.ritoPronto);
  const vida = mundo.vida != null ? mundo.vida : ficha.vida;
  const maximo = mundo.vidaMax || ficha.vidaMax || vida;
  document.querySelector("#vida-rotulo").textContent = "Vida " + vida + "/" + maximo;
  document.querySelector("#vida-barra").style.width = Math.max(0, Math.min(100, (vida / maximo) * 100)) + "%";
  const lista = document.querySelector("#atributos-lista");
  lista.replaceChildren();
  Object.entries(ficha.atributos || {}).forEach(([nome, valor]) => {
    const item = document.createElement("li");
    item.textContent = nome + " " + valor;
    lista.append(item);
  });
}

function ativarAba(id) {
  document.querySelectorAll("[role=tab]").forEach((tab) => {
    const selected = tab.id === id;
    tab.setAttribute("aria-selected", selected ? "true" : "false");
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !selected;
  });
}

document.querySelectorAll("[role=tab]").forEach((tab) => {
  tab.addEventListener("click", () => ativarAba(tab.id));
});

async function enviarTurno(payload) {
  if (!sagaId) {
    say("Abra ou crie uma saga.");
    return;
  }
  const button = document.querySelector("#acao button[type=submit]");
  const comecar = document.querySelector("#comecar");
  button.disabled = true;
  comecar.disabled = true;
  logEl.querySelectorAll(".erro-chat").forEach((node) => node.remove());
  const atual = paragrafo("narrando", "Narrando…");
  logEl.append(atual);
  say("Narrando…");
  try {
    const response = await api("/api/sagas/" + sagaId + "/turnos", {
      method: "POST",
      headers: { Accept: "text/event-stream" },
      signal: AbortSignal.timeout(70000),
      body: JSON.stringify(payload),
    });
    await lerEventos(response, atual, payload.texto);
  } catch (error) {
    const interrompido = error.name === "TimeoutError" || error.name === "AbortError";
    mostrarErro(atual, interrompido ? "A narração demorou demais e foi interrompida. Tente de novo." : error.message);
  } finally {
    button.disabled = false;
    comecar.disabled = false;
  }
}

async function lerEventos(response, atual, acao) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let playerNode = null;
  let settled = false;
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const event = (part.match(/^event: (.+)$/m) || [])[1];
      const dataLine = part.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
      const data = dataLine ? JSON.parse(dataLine) : {};
      if (event === "token") {
        if (atual.className !== "narrador") {
          atual.className = "narrador";
          atual.textContent = "";
        }
        if (acao && !playerNode) {
          playerNode = paragrafo("jogador", "Você: " + acao);
          logEl.insertBefore(playerNode, atual);
        }
        atual.textContent += data.texto || "";
      } else if (event === "done") {
        atual.textContent = data.narrativa || atual.textContent;
        document.querySelector("#objetivo").textContent = textoObjetivo(data);
        document.querySelector("#mundo").textContent = resumoMundo(data.mundo);
        document.querySelector("#saga-titulo").textContent = data.titulo || document.querySelector("#saga-titulo").textContent;
        preencherPainel(data.mundo, data.resumo, fichaAtual);
        if (data.cota) {
          const limite = data.cota.limite == null ? "sem teto" : data.cota.usados + "/" + data.cota.limite;
          const texto = "Plano " + data.cota.plano + " · turnos hoje " + limite;
          document.querySelector("#meta").textContent = texto;
          document.querySelector("#meta-jogo").textContent = texto;
        }
        document.querySelector("#comecar").hidden = true;
        document.querySelector("#texto").value = "";
        say("");
        settled = true;
        await carregarSagas();
      } else if (event === "troca") {
        atual.textContent = data.texto || "";
      } else if (event === "erro" || event === "cota") {
        if (playerNode) playerNode.remove();
        mostrarErro(atual, data.mensagem || "Não foi possível narrar.");
        settled = true;
      }
    }
  }
  if (!settled) mostrarErro(atual, "A narração parou antes de terminar. Tente de novo.");
}

function textoObjetivo(data) {
  if (!data || !data.objetivo) return "";
  const status = data.objetivoStatus && data.objetivoStatus !== "ativa" ? data.objetivoStatus + " — " : "";
  let line = "Objetivo: " + status + data.objetivo;
  if (data.objetivoOriginal && data.objetivoOriginal !== data.objetivo) {
    line += " (fim do roteiro: " + data.objetivoOriginal + ")";
  }
  return line;
}

document.querySelector("#acao").addEventListener("submit", (event) => {
  event.preventDefault();
  const texto = document.querySelector("#texto").value.trim();
  if (!texto) {
    say("Escreva o que você faz.");
    return;
  }
  enviarTurno({ texto });
});

document.querySelector("#texto").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey) return;
  event.preventDefault();
  if (event.isComposing || event.keyCode === 229) return;
  document.querySelector("#acao").requestSubmit();
});

document.querySelector("#comecar").addEventListener("click", () => {
  enviarTurno({ abertura: true });
});

if (token) {
  abrirJogo().catch(() => {
    token = "";
    localStorage.removeItem("token");
    say("Entre de novo.");
  });
}
