const statusEl = document.querySelector("#status");
const authEl = document.querySelector("#auth");
const jogoEl = document.querySelector("#jogo");
const logEl = document.querySelector("#log");
let token = localStorage.getItem("token") || "";
let sagaId = "";

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
  jogoEl.hidden = true;
  authEl.hidden = false;
  say("Você saiu.");
});

function mostrarJogador(jogador) {
  const limite = jogador.turnosLimite == null ? "sem teto" : jogador.turnosUsados + "/" + jogador.turnosLimite;
  const teste = jogador.plano === "trial" ? " · teste: " + jogador.diasDeTeste + " dia(s)" : "";
  document.querySelector("#meta").textContent = "Plano " + jogador.plano + " · turnos hoje " + limite + teste;
}

async function abrirJogo(jogador) {
  authEl.hidden = true;
  jogoEl.hidden = false;
  if (!jogador) jogador = await api("/api/eu");
  mostrarJogador(jogador);
  await carregarFichas();
  await carregarSagas();
}

async function carregarFichas() {
  const fichas = await api("/api/personagens");
  const select = document.querySelector("#personagem");
  select.replaceChildren();
  fichas.forEach((ficha) => {
    const option = document.createElement("option");
    option.value = ficha.id;
    option.textContent = ficha.nome + " · " + ficha.arquetipo;
    select.append(option);
  });
}

async function carregarSagas() {
  const sagas = await api("/api/sagas");
  const list = document.querySelector("#sagas");
  list.replaceChildren();
  sagas.forEach((saga) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = saga.titulo;
    button.addEventListener("click", () => abrirSaga(saga.id).catch((error) => say(error.message)));
    item.append(button);
    list.append(item);
  });
}

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
    say("Ficha criada.");
    await carregarFichas();
  } catch (error) {
    say(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#nova-saga").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const saga = await api("/api/sagas", {
      method: "POST",
      body: JSON.stringify({ personagemId: document.querySelector("#personagem").value }),
    });
    await carregarSagas();
    await abrirSaga(saga.id);
  } catch (error) {
    say(error.message);
  }
});

function paragrafo(className, text) {
  const el = document.createElement("p");
  el.className = className;
  el.textContent = text;
  return el;
}

async function abrirSaga(id) {
  const saga = await api("/api/sagas/" + id);
  sagaId = saga.id;
  document.querySelector("#saga-titulo").textContent = saga.titulo;
  logEl.replaceChildren();
  saga.mensagens.forEach((mensagem) => {
    const mine = mensagem.papel === "player";
    logEl.append(paragrafo(mine ? "jogador" : "narrador", (mine ? "Você: " : "") + mensagem.texto));
  });
  document.querySelector("#memoria").textContent = saga.resumo ? "Memória: " + saga.resumo : "Memória: (vazia)";
  document.querySelector("#mundo").textContent = resumoMundo(saga.mundo);
  document.querySelector("#comecar").hidden = saga.mensagens.length > 0;
  say("");
}

function resumoMundo(mundo) {
  const npcs = (mundo.npcs || []).map((npc) => npc.nome).join(", ") || "nenhum";
  return (
    "Lugar: " + mundo.lugar +
    " · " + mundo.quando +
    " · vida " + mundo.vida + "/" + mundo.vidaMax +
    " · NPCs: " + npcs
  );
}

async function enviarTurno(payload) {
  if (!sagaId) {
    say("Abra ou crie uma saga.");
    return;
  }
  const button = document.querySelector("#acao button[type=submit]");
  const comecar = document.querySelector("#comecar");
  button.disabled = true;
  comecar.disabled = true;
  const atual = paragrafo("narrador", "");
  logEl.append(atual);
  try {
    const response = await api("/api/sagas/" + sagaId + "/turnos", {
      method: "POST",
      headers: { Accept: "text/event-stream" },
      body: JSON.stringify(payload),
    });
    await lerEventos(response, atual, payload.texto);
  } catch (error) {
    atual.remove();
    say(error.message);
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
        if (acao && !playerNode) {
          playerNode = paragrafo("jogador", "Você: " + acao);
          logEl.insertBefore(playerNode, atual);
        }
        atual.textContent += data.texto || "";
      } else if (event === "done") {
        atual.textContent = data.narrativa || atual.textContent;
        document.querySelector("#memoria").textContent = "Memória: " + (data.resumo || "");
        document.querySelector("#mundo").textContent = resumoMundo(data.mundo);
        document.querySelector("#saga-titulo").textContent = data.titulo || document.querySelector("#saga-titulo").textContent;
        if (data.cota) {
          const limite = data.cota.limite == null ? "sem teto" : data.cota.usados + "/" + data.cota.limite;
          document.querySelector("#meta").textContent = "Plano " + data.cota.plano + " · turnos hoje " + limite;
        }
        document.querySelector("#comecar").hidden = true;
        document.querySelector("#texto").value = "";
        say("");
        await carregarSagas();
      } else if (event === "troca") {
        atual.textContent = data.texto || "";
      } else if (event === "erro" || event === "cota") {
        atual.remove();
        if (playerNode) playerNode.remove();
        say(data.mensagem || "Não foi possível narrar.");
        if (data.assinaturaUrl) {
          const link = document.createElement("a");
          link.href = data.assinaturaUrl;
          link.textContent = " Assinar";
          statusEl.append(link);
        }
      }
    }
  }
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
