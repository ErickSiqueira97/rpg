# Decisões quando o desenho deixava escolha

Estas escolhas valem até o Erick mudar o desenho. Os números continuam os de `docs/regras.md` e `docs/catalogo.md`.

- Níveis vão de 1 a 20. O teto 10 do plano antigo de missões não entra no motor.
- 20 natural e 1 natural só decidem jogada de ataque. Teste e salvaguarda usam o total contra a CD. Salvaguarda contra a morte mantém o 1 (duas falhas) e o 20 (volta com 1 PV).
- Ficha antiga: atributo + 4, depois +2 em Vigor e +1 em Força, teto 20. PV recalculados pela classe mapeada (Errante vira Sombra, Ocultista vira Exorcista).
- A IA pode propor `objetivoStatus: concluida`. O XP (300 na missão, 900 na saga) é escrito uma vez pelo motor. A IA não envia número de XP.
- Itens, PV, PE, condições e morte deixam de ser aceitos no JSON de estado da narração. Item só entra por saque do roteiro ou pela loja, nas fases seguintes.
- Dano dos rótulos de risco, proposta nossa: leve 1d4 + nível/4, médio 1d6 + nível/3, grave 1d8 + nível/2.
- Descanso longo recupera todos os PV e todos os dados de vida, como a frase adaptada da matriz, e só em saga num lugar marcado seguro.
- Na saga que não é Brutal, três falhas abrem o Julgamento uma vez e ainda não marcam morte permanente. No Brutal, sem o contrato ligar o Julgamento, a morte é imediata. Na missão, três falhas são derrota: volta com 1 PV e o objetivo falha.
- O Hóspede, se um dia assumir a ficha, fica uma cena. Não vira NPC para sempre enquanto essa pergunta estiver aberta.
- A origem dá um +2 e um +1 em dois atributos diferentes, ou +1 em três. O +2 da ficha sugerida cai no atributo do ataque, que nasce em 15. Se a origem antiga não tinha esse atributo, a sugestão troca a origem. A subclasse das duas ou três lâminas se chama Múltiplas Lâminas.
- O fluxo «quero ser» não grava nem mostra nome protegido. A tela não cita a obra. Um apelido conhecido casa na tabela e não passa pelo narrador, para um modelo errado não trocar o build. Pedido sem apelido vai ao narrador com os ids do catálogo; se o JSON vier inválido, tenta de novo uma vez e o log guarda o motivo. O último recurso é um caçador explorador, não um espadachim genérico.
- Cozinheiro de Batalha é uma das 15 classes, não só uma Via.
- Cada uma das duas chamadas (árbitro e narradora) tem o próprio teto de 45 segundos. A rolagem é gravada antes da segunda chamada; repetir o pedido com a mesma chave devolve a mesma rolagem.
- Efeito de raça ou classe que ainda só existe como texto na ficha não altera número nenhum. Quando ganha `efeito_motor`, o motor passa a aplicá-lo e a cortar no teto.
- O simulador usa o perfil de combate da classe (PV, CA, ataque, dado). Traço de raça que ainda é só texto não muda a taxa. A iniciativa é rolada, então o espelho fica perto de 50%. Amostra pequena (menos de 200 lutas) oscila e pode sair de 40–60% por acaso; o patch só lê combinações com pelo menos 200 lutas.
- Com um oponente só, a tabela do Professor ataca, e defende quando os PV caem à metade ou menos. Aprendiz reduz a CA do Professor em 2 e corta o dano dele pela metade.
- Sem testemunhas declaradas, um crime assume uma testemunha com Percepção passiva 12.
- Concluir a missão rende 50 Runas (80 na saga), além do XP. A loja gasta essas Runas.
