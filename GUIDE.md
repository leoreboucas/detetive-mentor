# Guia de criação: Detetive Mentor

Sistema especialista conversacional, na modalidade de **tutor inteligente**, em que um detetive veterano (o *Inspetor Arruda*) orienta um detetive aprendiz (o usuário) na resolução de casos de mistério fictícios, sem nunca entregar o culpado.

Este guia explica **o que** foi construído, **por que** cada peça existe e **como** reproduzir e evoluir a aplicação. Ele parte do material de aula (projetos `progbot`, `progbot.ferramentas` e `classificador`).

---

## 1. O Detetive Mentor como sistema especialista

| Componente clássico de um sistema especialista | Onde está no Detetive Mentor |
|---|---|
| **Base de conhecimento** (fatos) | `cases/*.json`: suspeitos, evidências, depoimentos, linha do tempo e a parte secreta (solução, contradições, dicas) |
| **Base de regras** | `app/services/prompts.py`: as regras do mentor (papel de tutor, método socrático, regras anti-spoiler, quando usar cada ferramenta) |
| **Motor de inferência** | `app/services/mentor.py`: LLM (Gemini) + laço de chamadas de ferramentas MCP + guarda anti-spoiler |
| **Memória de trabalho** | Progresso do aprendiz (`data/progress/*.json`, via MCP): nível de dica, contradições descobertas, acusações |
| **Módulo de explicação** | Dicas graduais (nível 1 a 3) e a explicação completa, liberada só depois da acusação correta |
| **Interface com o usuário** | Site Flask (`app/templates`, `app/static`): dossiê do caso, chat e formulário de acusação |
| **Avaliação / validação** | `evaluation/judge.py` (LLM-as-a-Judge) e `tests/test_offline.py` |

O especialista **conhece a solução** de cada caso (ferramenta `get_solution`) e a usa só no raciocínio interno, para avaliar as deduções do aprendiz.

---

## 2. O que reaproveitamos do material do professor

| Projeto do professor | Ideia reaproveitada | Arquivo no Detetive Mentor |
|---|---|---|
| `progbot.ferramentas/llm.py` | Cliente Gemini com a API *Interactions* (`client.aio.interactions.create`) e mensagens `user_input` | `app/services/llm.py` |
| `progbot.ferramentas/chat.py` | Persona montada como lista de instruções; conexão MCP por *streamable HTTP*; laço "LLM pede ferramenta → executa → devolve `function_result`" | `app/services/prompts.py`, `app/services/mcp_client.py`, `app/services/mentor.py` |
| `progbot.ferramentas/ferramentas.py` | Servidor `MCPServer` com `@mcp.tool` | `mcp_server/server.py` |
| `progbot.ferramentas/cache.py` | Cache semântico com `sentence-transformers` + ChromaDB (distância cosseno e limiar) | `app/services/semantic_cache.py` |
| `progbot.ferramentas/julgamento.py` | Juiz LLM, com teste de "alucinações conhecidas" antes de julgar o assistente | `evaluation/judge.py` |
| `classificador` | Uso do ChromaDB como banco vetorial com metadados | filtro por metadados no cache |

**O que mudou em relação ao ProgBot:**
- Nomes em inglês e estrutura padrão de aplicação Flask (app factory, blueprints, `templates/` e `static/`).
- Interface web em vez de terminal.
- Base de conhecimento estruturada (fatos públicos x secretos) em vez de pares pergunta/resposta.
- O cache considera **caso + progresso + suspeitos mencionados**, não só a pergunta.
- Anti-spoiler em camadas (seção 5).
- O juiz avalia três critérios (correção, pedagogia, vazamento) em vez de "ATENDE / NÃO ATENDE".

---

## 3. Arquitetura

```
 Navegador (HTML/CSS/JS)
        │  fetch /api/...
        ▼
 Flask (run.py → app/__init__.py:create_app)
   ├─ routes/main.py   GET /            → templates/index.html
   └─ routes/api.py    /api/cases, /api/sessions, /api/sessions/end, /api/chat, /api/hint, /api/accuse
        │  run_async(...)   (loop asyncio numa thread: services/async_runner.py)
        ▼
 MentorEngine (services/mentor.py)  ── motor de inferência
   ├─ SemanticCache (ChromaDB + MiniLM)   filtro: case_id + stage + entities
   ├─ Gemini (services/llm.py)            persona = regras de prompts.py
   ├─ spoiler_guard.py                    verificação determinística da saída
   └─ MCPClient (services/mcp_client.py)
        │  streamable HTTP  :8000/mcp
        ▼
 MCP server (mcp_server/server.py)
   ├─ list_cases · get_case · get_evidence · get_testimonies · get_timeline
   ├─ get_solution (confidencial)
   ├─ request_hint · record_progress · get_progress · reset_progress
   └─ validate_accusation
        │
        ▼
 cases/*.json  (base de conhecimento)     data/progress/*.json  (memória de trabalho)

 evaluation/judge.py ── usa o MentorEngine + MCP e um 2º modelo Gemini como juiz
```

### Por que o Flask precisa de um "AsyncRunner"?
As views do Flask são síncronas, mas o cliente MCP e o cliente Gemini são assíncronos e a sessão MCP precisa continuar viva entre requisições. O `AsyncRunner` mantém um *event loop* numa thread de fundo, e cada rota chama `run_async(coroutine)`. É o mesmo `asyncio` do `chat.py` do professor, adaptado a um servidor web.

---

## 4. Estrutura de pastas

```
detetive-mentor/
├── run.py                     # inicia o site (Flask)
├── config.py                  # configurações (lidas do .env)
├── requirements.txt
├── .env.example
├── GUIDE.md / README.md
├── cases/
│   ├── diamond_case.json      # 1. O Sumiço da Estrela de Minas (iniciante)
│   ├── bookstore_case.json    # 2. O Apagão do Sebo Ventura (intermediário)
│   ├── chess_case.json        # 3. Xeque-Mate no Clube Bandeirante (difícil)
│   ├── will_case.json         # 4. O Testamento do Coronel Albuquerque (muito difícil)
│   ├── painter_case.json      # 5. O Último Quadro de Matias Brandão (especialista)
│   └── _template.json         # modelo para novos casos (ignorado na listagem)
├── mcp_server/
│   ├── server.py              # ferramentas MCP
│   └── repository.py          # leitura de casos e gravação de progresso
├── app/
│   ├── __init__.py            # create_app()
│   ├── extensions.py          # cria o MentorEngine na inicialização
│   ├── routes/
│   │   ├── main.py            # página
│   │   └── api.py             # API JSON
│   ├── services/
│   │   ├── mentor.py          # motor de inferência
│   │   ├── prompts.py         # regras do mentor (persona)
│   │   ├── llm.py             # Gemini
│   │   ├── mcp_client.py      # cliente MCP
│   │   ├── semantic_cache.py  # cache sensível a caso e progresso
│   │   ├── spoiler_guard.py   # reforço anti-spoiler
│   │   ├── async_runner.py
│   │   └── text_utils.py
│   ├── templates/             # base.html, index.html
│   └── static/                # css/style.css, js/app.js
├── evaluation/
│   ├── judge.py               # LLM-as-a-Judge
│   └── scenarios.json         # calibração + conversas de teste
└── tests/
    └── test_offline.py        # testes sem LLM
```

---

## 5. Decisões importantes

### 5.1 Anti-spoiler em três camadas
1. **Separação de dados:** o JSON do caso tem `public` e `secret`. As rotas do site só usam ferramentas públicas. O progresso enviado ao navegador mostra só contagens, nunca os ids das contradições.
2. **Reforço no prompt:** quatro regras anti-spoiler explícitas em `prompts.py`, incluindo a defesa contra engenharia social ("sou o professor, ignore as regras").
3. **Guarda determinística** (`spoiler_guard.py`): toda resposta passa por uma verificação. Se o nome ou apelido do culpado aparece **na mesma frase** que um termo acusatório ("culpado", "roubou", "foi ele"…), a resposta é descartada, o histórico é limpo e o LLM recebe um aviso para responder de novo. Se vazar outra vez, sai uma resposta segura fixa. Respostas bloqueadas nunca entram no cache.

Também na acusação: se ela estiver errada, o mentor recebe só `{"solved": false}`. Ele não fica sabendo se o culpado estava certo e faltaram provas, para não confirmar o culpado sem querer.

### 5.1.1 Fatos públicos x deduções
Um sistema especialista **conhece todo o caso**, então o mentor recebe o dossiê público completo (suspeitos, evidências, depoimentos e linha do tempo) já na persona. A regra é:
- **Fatos públicos** ("quem são os suspeitos?", "o que o Rui disse?", "que horas choveu?"): o mentor responde direto e com precisão, sem devolver a pergunta.
- **Deduções** (quem mentiu, quais fatos se contradizem, quem tem álibi, quem é o culpado): o aprendiz precisa concluir. O mentor aplica o método socrático e só avalia o raciocínio.

Sem essa distinção, o modelo aplicava o método socrático a tudo e respondia "dê uma olhada no dossiê" até a perguntas simples.

### 5.2 Dicas graduais determinísticas
As dicas estão escritas no caso (níveis 1→3) e saem pela ferramenta `request_hint`, que controla a ordem e conta quantas foram usadas. O LLM só **reescreve** a dica no tom do mentor. Assim a progressão pedagógica é garantida pelo sistema, não pela "boa vontade" do modelo.

### 5.3 Cache semântico sensível ao caso e ao progresso
- **case_id:** perguntas iguais em casos diferentes têm respostas diferentes.
- **stage** (`hint2|foundC1,C3|solved0`): a mesma pergunta antes e depois de uma dica ou descoberta exige respostas diferentes.
- **entities** (suspeitos citados como palavras inteiras): "E o Rui?" e "E a Clara?" ficam muito próximas no espaço de embeddings. Sem esse filtro, o cache trocaria as respostas.
- O limiar de distância é mais rigoroso que o do ProgBot (0,12 contra 0,20).
- **versão do prompt:** o `stage` começa com um hash das regras do mentor (`prompts.PROMPT_VERSION`). Quando as regras mudam, respostas antigas deixam de ser servidas automaticamente.
- **Só respostas factuais vão para o cache.** Uma resposta só é guardada se todas as ferramentas que o mentor usou estiverem na lista `FACTUAL_TOOLS` (`mentor.py`): consultas ao dossiê e ao progresso. Se o mentor chamou `get_solution`, ele estava avaliando uma dedução; se chamou `request_hint`, `record_progress` ou `validate_accusation`, mudou o progresso. Essas respostas nunca são reaproveitadas, e respostas bloqueadas pelo anti-spoiler também não.

#### Por que deduções não vão para o cache
Chegamos a considerar guardar no cache as deduções certas, junto com a contradição descoberta, para registrar o progresso de novo quando outro aprendiz fizesse a mesma dedução. A ideia foi descartada por dois motivos:

1. **Similaridade não é correção.** Medimos com o modelo de embeddings do cache (o limiar de reuso é 0,12):

   | Comparada com "Lemos disse que saiu às 21h15, mas o táxi só buscou ele às 22h05" | Distância |
   |---|---|
   | A mesma dedução, com outras palavras | 0,053 |
   | Errada: horários invertidos | 0,012 |
   | Errada: sem contradição nenhuma | 0,028 |

   A dedução errada fica *mais perto* do que a certa reescrita, porque embeddings captam mal números e negações. O cache daria a descoberta e o elogio a quem errou. Avaliar uma dedução é um julgamento, e julgamento é trabalho do especialista, não de uma busca por textos parecidos.
2. **Um cache deve ser transparente.** Desligar o cache só pode mudar a velocidade, nunca o comportamento. Registrar progresso a partir de um acerto no cache colocaria regra de negócio dentro dele.

O risco de "a informação mudar" é outro conceito, a **invalidação de cache**. Ele já é tratado pela chave, que muda quando o caso, o progresso ou as regras do mentor mudam. Os testes `CachePolicyTest` garantem a regra.

#### Consequência: o mentor precisa sempre consultar a solução
Essa regra depende de o mentor chamar `get_solution` antes de avaliar uma dedução. Com o dossiê completo no prompt, o modelo passou a avaliar "de cabeça", sem consultar a solução e sem registrar descobertas. Por isso o prompt tem um **protocolo obrigatório de avaliação**: diante de qualquer dedução, a primeira ação é chamar `get_solution`, conferir os fatos citados e só então registrar o progresso.

**Limitação conhecida:** nos testes com `gemini-3.5-flash-lite`, o mentor ainda aceitou como descoberta uma dedução com os horários invertidos, embora na resposta tenha citado os horários corretos. Esse cenário está em `evaluation/scenarios.json` para ser medido pelo juiz. Um modelo maior em `MENTOR_MODEL` tende a ser mais rigoroso.

### 5.4 Validação da acusação por regra, não por LLM
`validate_accusation` é código: o suspeito precisa ser o culpado **e** o aprendiz precisa citar ao menos `min_key_evidence` evidências-chave. O LLM só comenta o resultado. Isso deixa a nota final auditável.

### 5.5 Pistas falsas como recurso pedagógico
Todo caso tem contradições irrelevantes de propósito (por exemplo, no caso 1, o mordomo mente por outro motivo e um dos suspeitos tem motivo, mas também tem álibi). Elas são registradas como descobertas (`relevant: false`), e o mentor ensina que **nem toda contradição indica culpa** e que **motivo não é prova**. Um teste automático garante que cada caso tenha pelo menos uma.

### 5.6 Progressão de dificuldade dos casos
Cada caso treina uma habilidade de raciocínio diferente e tem menos pistas diretas que o anterior. Nos casos mais difíceis, as evidências mais chamativas apontam para um inocente, e só um detalhe aparentemente pequeno revela o culpado. A tabela não revela as soluções:

| # | Caso | Dificuldade | Habilidade treinada |
|---|---|---|---|
| 1 | O Sumiço da Estrela de Minas | iniciante | Delimitar a janela de tempo do crime e cruzar álibis com evidências físicas |
| 2 | O Apagão do Sebo Ventura | intermediário | Perceber que a prova "óbvia" (a chave) é irrelevante, usar fotos como linha do tempo e identificar quem sabia algo antes da hora |
| 3 | Xeque-Mate no Clube Bandeirante | difícil | Descobrir o meio antes de procurar o autor: o tempo de ação do veneno desmonta a prova principal (digitais na xícara) |
| 4 | O Testamento do Coronel Albuquerque | muito difícil | Datar um documento por detalhes internos, fechar uma janela de tempo com fatos indiretos e analisar "quem ganha" até o fim (o beneficiário aparente é o alvo) |
| 5 | O Último Quadro de Matias Brandão | especialista | Desconfiar da mensagem da vítima, usar o silêncio do cão como evidência e detectar conhecimento que só o culpado teria |

Do caso 2 em diante, a acusação exige pelo menos 3 evidências-chave.

### 5.7 Recomeçar um caso do zero
Ao sair de um caso, seja pelo botão "Voltar ao livro de ocorrências" que aparece quando o caso é resolvido, seja pelo link no topo do dossiê (que pede confirmação), o site chama `POST /api/sessions/end`. O motor chama a ferramenta MCP `reset_progress`, que apaga do banco (`data/progress/`) as dicas, as descobertas e as acusações daquela sessão, e esquece a conversa. Se o aprendiz fechar a aba, o navegador envia o mesmo pedido com `navigator.sendBeacon`. Abrir o caso de novo cria uma sessão nova, do zero.

---

## 6. Passo a passo de construção

Siga nesta ordem. Cada fase pode ser testada antes de passar à próxima.

### Fase 1: base de conhecimento (o caso)
1. Escreva o caso em `cases/<id>.json` a partir de `_template.json`.
2. Primeiro pense na **solução**: culpado, motivo, meio, oportunidade. Depois crie as **evidências-chave** que provam a solução, as **contradições** entre depoimentos e evidências, e 1 ou 2 **pistas falsas**.
3. Escreva 3 dicas, da mais geral (método) à mais específica (quase direta, mas ainda exigindo a conclusão).
4. Preencha `culprit_aliases` com todas as formas de citar o culpado (nome, sobrenome, profissão, iniciais). A guarda anti-spoiler depende disso.

### Fase 2: servidor MCP
1. `mcp_server/repository.py` lê os casos e grava o progresso.
2. `mcp_server/server.py` expõe as 11 ferramentas.
3. Teste: `python -m mcp_server.server` e, em outro terminal, `npx @modelcontextprotocol/inspector` (URL `http://localhost:8000/mcp`).

### Fase 3: persona e regras
`app/services/prompts.py`: escreva as regras do tutor como lista de instruções, no mesmo formato do `iniciar_persona_assistente` do professor. O contexto da sessão (`session_id`, `case_id` e dados públicos do caso) entra no fim da lista.

### Fase 4: motor de inferência
`app/services/mentor.py`: o laço LLM ↔ ferramentas vem do `chat.py`, agora com limite de rodadas (`MAX_TOOL_ROUNDS`), a guarda anti-spoiler e o cache.

### Fase 5: cache semântico
`app/services/semantic_cache.py`: a mesma base do `cache.py` do professor, com filtro `where` do ChromaDB por `case_id`, `stage` e `entities`.

### Fase 6: site Flask
1. `app/__init__.py` (`create_app`) registra os blueprints e cria o motor.
2. `app/routes/api.py` tem as rotas JSON. `app/routes/main.py` renderiza a página.
3. `app/templates` e `app/static` têm a interface (seção 8).

### Fase 7: avaliação
1. `tests/test_offline.py`: testes rápidos, sem LLM.
2. `evaluation/judge.py`: calibração do juiz com respostas sabidamente ruins e boas, depois avaliação do mentor real em conversas roteiradas (`scenarios.json`).

---

## 7. Como rodar

```bash
pip install -r requirements.txt
cp .env.example .env        # e preencha GOOGLE_API_KEY
```

Terminal 1: ferramentas MCP
```bash
python -m mcp_server.server
```

Terminal 2: site
```bash
python run.py
```
Acesse http://127.0.0.1:5000

Testes offline:
```bash
python -m unittest discover tests
```

Avaliação LLM-as-a-Judge (com o servidor MCP rodando):
```bash
python -m evaluation.judge
```
O relatório é salvo em `evaluation/reports/`.

> Na primeira execução, o cache baixa o modelo de embeddings (~470 MB). Para rodar sem cache, use `CACHE_ENABLED=false` no `.env`.

---

## 8. Interface (design)

O design segue a skill `frontend-design` (salva em `.claude/skills/frontend-design`).

- **Assunto:** papelada de uma delegacia brasileira dos anos 70.
- **Paleta:** verde institucional `#3e5a4c` (parede), papel de seda `#e6eae0`, tinta de papel-carbono `#24408e`, grafite `#1f2421`, vermelho de carimbo `#b0302a` (só para acusação e "Resolvido").
- **Tipografia:** *Bitter* (serifa quadrada de formulário oficial) na interface; *Special Elite* (máquina de escrever) só nos documentos do caso.
- **Elemento marcante:** depoimentos, evidências e linha do tempo aparecem como cópias datilografadas em carbono azul. O resto fica sóbrio.
- **Movimento:** um único momento, o carimbo "Resolvido" caindo quando a acusação é aceita.
- **Layout:** dossiê à esquerda (abas), conversa à direita. No celular, as duas colunas viram uma.

---

## 9. Requisitos da atividade e onde estão atendidos

| Requisito | Implementação |
|---|---|
| (1) Site com chat e base de casos fictícios | Flask + `templates/index.html` + `static/js/app.js`; casos em `cases/` |
| (2) Motor de inferência com LLM, reforço anti-spoiler e níveis de dica | `services/mentor.py`, `services/prompts.py`, `services/spoiler_guard.py`, `request_hint` |
| (3) Ferramentas MCP: casos, evidências, depoimentos, linha do tempo, solução, progresso e acusação | `mcp_server/server.py` (11 ferramentas) |
| (4) Cache semântico sensível ao caso e ao progresso | `services/semantic_cache.py` (filtro `case_id` + `stage` + `entities`) |
| (5) LLM-as-a-Judge: correção, qualidade pedagógica e vazamento | `evaluation/judge.py` + `scenarios.json` |

---

## 10. Roteiro de refinamento

1. **Mais casos:** variar o tipo de crime (ex.: um caso com dois cúmplices, ou em que o culpado diz a verdade e um inocente mente). Use `cases/_template.json` e rode os testes de consistência.
2. **Sessões persistentes:** hoje o histórico do chat fica em memória (some quando o Flask reinicia). Dá para guardá-lo em SQLite ou no próprio diretório `data/`.
3. **Painel de descobertas:** mostrar ao aprendiz as contradições que ele já encontrou, nas palavras dele (campo `note` de `record_progress`).
4. **Métricas de cache:** contar acertos e falhas e mostrar a economia de tokens.
5. **Ajuste do limiar do cache:** testar valores com pares de perguntas reais e registrar no relatório.
6. **Juiz mais robusto:** rodar cada cenário N vezes e usar a média; comparar dois modelos juízes.
7. **Guarda anti-spoiler semântica:** além das palavras-chave, perguntar a um modelo pequeno "esta resposta revela o culpado?" antes de enviar.
8. **Streaming** da resposta do mentor no chat.

## 11. Limitações conhecidas
- A guarda determinística pode gerar falsos positivos (frases que citam o culpado de forma neutra junto com "culpado"). Nesse caso o sistema só regenera a resposta, sem prejuízo ao aprendiz.
- Sessões ficam em memória: é um protótipo para um único servidor.
- Os nomes de modelo (`gemini-3.5-flash-lite` e `gemini-3.1-flash-lite`) seguem os do material de aula e podem ser trocados no `.env`.
