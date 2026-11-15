# Detetive Mentor

Tutor inteligente de investigação: um detetive veterano guia o aprendiz até o culpado de um caso de mistério, sem revelar a solução.

Veja o [guia de criação](GUIDE.md) para a arquitetura, as decisões de projeto e o roteiro de refinamento.

## Rodando

```bash
pip install -r requirements.txt
cp .env.example .env    # preencha GOOGLE_API_KEY
```

```bash
python -m mcp_server.server   # terminal 1: ferramentas MCP (porta 8000)
```

```bash
python run.py                 # terminal 2: site em http://127.0.0.1:5000
```

## Testes

```bash
python -m unittest discover tests     # offline, sem LLM
```

```bash
python -m evaluation.judge            # LLM-as-a-Judge (precisa do servidor MCP e da chave)
```
