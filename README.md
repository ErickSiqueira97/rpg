# RPG Multiverso

RPG de texto em português. Você cria a ficha e escreve o que o personagem faz. O narrador (um modelo de linguagem) conduz a saga, a época e os NPCs. Não há mestre humano.

A interface desta versão é simples de propósito: cadastro, ficha, lista de sagas e um chat.

## O que havia neste repositório

O histórico do git tinha dois commits, ambos de 25/11/2026:

- uma página estática (`index.html`) com a campanha ilustrada de Véspera e respostas sorteadas no navegador;
- um workflow de GitHub Pages para publicar essa página.

Não havia servidor, banco, conta de jogador nem chamada de modelo. A página dizia que a ligação com o mestre de IA ficaria para depois. Este clone não contém código de 2022.

## O que este MVP faz

- Cadastro e login (usuário e senha). O token fica no navegador.
- Ficha com atributos (base 4, 12 pontos, máximo 10).
- Várias sagas por jogador. Dá para sair e continuar: histórico, ficha, estado do mundo e o resumo da saga ficam no SQLite.
- Narrador via [LiteLLM](https://docs.litellm.ai/) (MIT), no mesmo processo. Cada provedor entra com **um modelo fixo** e **uma chave**.
- Pool grátis, nesta ordem, só com as chaves que existirem:
  1. **Gemini Flash-Lite** (`gemini/gemini-3.5-flash-lite`)
  2. **OpenRouter**, um id fixo terminado em `:free` (não o roteador `openrouter/free`, que troca de modelo)
  3. **Cloudflare Workers AI**, Llama 3.1 8B na variante `@cf/meta/llama-3.1-8b-instruct-fast`
- Se o provedor da vez falha ou está indisponível, o LiteLLM tenta o próximo com **o mesmo pacote de contexto**. Não há segunda conta do mesmo provedor: o processo recusa chave duplicada e recusa uma rota paga com outra chave do provedor que já está no pool.
- Pacote de cada turno: prompt fixo do narrador + resumo vivo da saga + ficha + mundo/NPCs + últimas N mensagens + a ação. O resumo ganha uma frase por turno e descarta as frases antigas quando passa do teto. Isso é o que o modelo novo recebe se o fallback entrar.
- Cada turno grava uma estimativa de tokens (`tamanho do texto / 4`) e, quando o provedor devolve uso, os números dele.
- Cota diária por jogador. Conta nova fica 7 dias em `trial` (teto maior). Depois passa a `free`. Plano `paid` usa a rota paga, com outro modelo fixo (por padrão `groq/openai/gpt-oss-20b`; dá para trocar por `deepseek/deepseek-chat`).
- Ao estourar a cota grátis, a resposta pede para assinar ou esperar o reset. O reset segue o fuso `PLAYER_UTC_OFFSET_HOURS` (padrão −3).
- Pagamento **não** está implementado. `POST /api/billing/webhook` responde 501 e descreve o contrato. Quem for ligar um gateway deve chamar `app.billing.apply_billing_event`.
- Moderação básica na ação e na narração (bloqueia conteúdo sexual envolvendo menor, mais termos extras). Dá para desligar ou apontar um webhook.
- Pensado para cerca de 100 jogadores ao mesmo tempo **neste processo**: o estado está no banco, cada jogador só tem um turno em voo, e no máximo 20 narrações correm juntas. Quem não pega vaga em poucos segundos recebe um aviso, sem gastar o turno.

## Rodar localmente com um provedor grátis

Requisito: Python 3.12. Os comandos abaixo partem da pasta do repositório.

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Se a execução de scripts estiver bloqueada, use `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` e ative de novo. Coloque a chave no `.env`:

```powershell
notepad .env
```

```text
GEMINI_API_KEY=sua-chave
LLM_GEMINI_MODEL=gemini/gemini-3.5-flash-lite
```

```powershell
python -m app.main
```

Sem chave, só para ver o fluxo (o narrador é falso):

```powershell
$env:RPG_LLM_FAKE = "1"
python -m app.main
```

Para atualizar esta branch:

```powershell
git fetch origin
git checkout cursor/rpg-textual-mvp-ece9
git pull origin cursor/rpg-textual-mvp-ece9
```

### Linux e macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

O caminho mais simples no pool grátis é uma chave do [Google AI Studio](https://aistudio.google.com/apikey). No `.env`:

```bash
GEMINI_API_KEY=sua-chave
LLM_GEMINI_MODEL=gemini/gemini-3.5-flash-lite
```

```bash
python -m app.main
```

Sem chave:

```bash
RPG_LLM_FAKE=1 python -m app.main
```

Abra `http://127.0.0.1:8000`. Cadastre um usuário, crie a ficha (os atributos já vêm com os 12 pontos) e clique em **Nova missão**. A cena de abertura é pedida sozinha. A resposta chega em streaming. Se o modelo recusar a chave, o motivo aparece em vermelho no chat e o erro completo (sem a chave) sai no terminal.

Em novembro de 2026, `gemini-2.5-flash-lite` ainda existe na API, mas a Google só o oferece a contas que já o usavam. Conta nova deve usar `gemini-3.5-flash-lite`, que é o padrão daqui. Se o id mudar de novo, troque só `LLM_GEMINI_MODEL`. Com `RPG_DEBUG=1` (ou com o servidor em `127.0.0.1`, que já é o padrão), a mensagem no chat inclui um motivo curto: chave inválida, modelo não encontrado ou limite atingido.

## Trocar de provedor

O app lê o ambiente na subida (e um arquivo `.env` na pasta do projeto, sem sobrescrever variável já exportada). Chaves não ficam no código.

| Variável | Função |
| --- | --- |
| `GEMINI_API_KEY`, `LLM_GEMINI_MODEL` | Principal do pool grátis |
| `OPENROUTER_API_KEY`, `LLM_OPENROUTER_MODEL` | Segundo. O id tem de terminar em `:free` |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `LLM_CLOUDFLARE_MODEL` | Transbordo. Os dois segredos precisam existir juntos |
| `LLM_PAID_API_KEY`, `LLM_PAID_MODEL`, `LLM_PAID_API_BASE` | Rota dos jogadores `paid`. `API_BASE` só se o provedor exigir URL própria |

Provedor sem chave fica de fora. Se o Gemini não estiver configurado, o OpenRouter vira o primeiro e o Cloudflare o fallback, e assim por diante. Reinicie o processo depois de editar o `.env`.

A rota paga é outro modelo, fixo, de outro provedor. Exemplo com DeepSeek em vez de Groq:

```bash
LLM_PAID_MODEL=deepseek/deepseek-chat
LLM_PAID_API_KEY=sua-chave-deepseek
```

Não coloque duas chaves no mesmo campo (`chave1,chave2`). Isso é recusado de propósito.

O arquivo `deploy/litellm.proxy.example.yaml` repete o mesmo desenho para quem quiser subir o proxy do LiteLLM separado. O servidor do jogo **não** usa esse arquivo: ele chama o SDK no processo, para um comando só e streaming direto.

## Cota, teste e pagamento

- `TRIAL_DAYS=7`, `TRIAL_TURNS_PER_DAY=40`, `FREE_TURNS_PER_DAY=20`.
- `PAID_TURNS_PER_DAY=0` significa sem teto diário na rota paga. Um número positivo liga o teto.
- `BILLING_CHECKOUT_URL`, se existir, aparece no aviso de cota. Não abre checkout nenhum por si.
- `POST /api/billing/webhook` está de propósito sem gateway. O contrato esperado é `{ "type": "subscription.activated" | "subscription.canceled", "userId": "...", "plan": "paid" | "free" }`. A função que grava o plano é `apply_billing_event` em `app/billing.py`.
- Para experimentar a rota paga na sua máquina, `ALLOW_DEV_PLAN_TOGGLE=1` liga `POST /api/dev/plano` com `{ "plano": "paid" }` ou `"free"`. Não use isso num servidor exposto.

## Testes e carga

```bash
pytest -q
python scripts/carga.py 100
```

Os testes não chamam provedor de verdade. O de carga sobe o app com o narrador falso e simula 100 jogadores ao mesmo tempo (cadastro, ficha, saga, dois turnos e leitura da memória). A suíte inclui esse cenário.

`GET /api/saude` lista os provedores configurados, sem as chaves.

## Limitações

- A cota do jogador não multiplica a cota do provedor. Gemini, OpenRouter `:free` (hoje, na casa de dezenas de pedidos por dia na conta sem créditos) e o saldo de neurons do Cloudflare acabam bem antes de 100 pessoas jogarem o dia inteiro. Quando todos falham, o jogador vê um aviso e a saga não perde o que já foi gravado.
- Um processo e um arquivo SQLite. Serve a meta de ~100 jogadores concorrentes neste desenho. Vários processos no mesmo arquivo não são o alvo; aí o banco precisaria ser outro.
- O resumo vivo guarda os fatos recentes que cabem no teto de tokens, não a saga inteira. NPCs, missões e sinais ficam no estado do mundo, se o modelo os devolver no bloco `<estado>`.
- Modelos pequenos às vezes ignoram o formato. Se não vier prosa, o turno não é gravado e a cota daquele pedido é devolvida.
- A moderação local é um gancho, não um filtro completo.
- Não há recuperação de senha, e-mail, nem gateway de pagamento.
- AI Horde ficou de fora: a rede escolhe o worker e entra numa fila. O pedido era um modelo fixo e resposta em streaming, sem fila quando houver vaga.
- GitHub Models foi encerrado em 30/07/2026, então não entra no pool.
- Os ids de modelo e os tetos grátis mudam. Os valores do `.env.example` são ponto de partida (o id `:free` do OpenRouter foi visto na lista pública em 25/11/2026), não um contrato com o provedor.
- A variante `@cf/meta/llama-3.1-8b-instruct` (sem `-fast`) foi descontinuada no Workers AI. O padrão é a variante `-fast`, que continua sendo Llama 3.1 8B. Confira o catálogo se a Cloudflare aposentar essa também.
- A tela é funcional e crua. A primeira partida é uma missão curta pronta, «O sinal do farol», em Porto de Véspera. Sagas longas, com capítulos, ficam só reservadas no banco (`tipo`, `roteiroId`, `nivelSugerido`); a economia disso não existe ainda.
- `gemini-2.5-flash-lite` não é mais o padrão: em novembro de 2026 a Google limita essa família a quem já usava. O padrão passou a `gemini-3.5-flash-lite`.
