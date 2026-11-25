const statusEl = document.querySelector("#status");
const authEl = document.querySelector("#auth");
const lobbyEl = document.querySelector("#lobby");
const jogoEl = document.querySelector("#jogo");
const logEl = document.querySelector("#log");
const fichaDialog = document.querySelector("#ficha-dialog");
let token = localStorage.getItem("token") || "";
let sagaId = "";
let fichaAtual = null;

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

function atualizarPontos() {
  const total = Object.values(atributos()).reduce((sum, value) => sum + value, 0);
  document.querySelector("#pontos").textContent = "Pontos usados: " + (total - 24) + " / 12";
}

document.querySelectorAll("[data-attr]").forEach((input) => {
  input.addEventListener("input", atualizarPontos);
});

document.querySelectorAll("[data-step]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.step);
    const next = Number(input.value) + Number(button.dataset.dir);
    if (next < 4 || next > 10) return;
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
  localStorage.removeItem("token");
  localStorage.removeItem("sagaId");
  jogoEl.hidden = true;
  lobbyEl.hidden = true;
  authEl.hidden = false;
  say("Você saiu.");
});

function mostrarJogador(jogador) {
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
    grade.append(card);
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
  fichaDialog.showModal();
  document.querySelector("#nome").focus();
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
        arquetipo: document.querySelector("#arquetipo").value,
        conceito: document.querySelector("#conceito").value,
        atributos: atributos(),
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
  return "Lugar: " + (mundo.lugar || "—") + " · " + (mundo.quando || "—");
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
  document.querySelector("#ficha-resumo").textContent = ficha.nome + " · " + ficha.arquetipo;
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
