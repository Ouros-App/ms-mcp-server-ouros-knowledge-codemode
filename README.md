# ms-mcp-server-ouros-knowledge

Servidor FastAPI com transporte MCP via Streamable HTTP para consultar uma coleção Qdrant usando embeddings da NVIDIA NIM.

<!-- REPO-METADATA:START -->
<!-- Metadados automáticos do repositório são mantidos pelo workflow. -->
<!-- REPO-METADATA:END -->

## O que já existe

- `GET /` e `GET /health` para operação básica.
- Endpoint MCP em `http://localhost:8000/mcp`.
- Ferramenta MCP `search_knowledge(query, limit)` para busca semântica.
- Ferramenta MCP `qdrant_status()` para verificar a coleção configurada.
- Ferramenta MCP `postgres_status()` para verificar a conexão somente leitura do MIDAS.
- Ferramentas MCP `get_user_context(user_type, user_id)` e `get_user_farm_data(user_type, user_id, limit)` para contexto personalizado por usuário.
- CLI `ingest` para extrair, dividir, embeddar e enviar arquivos ao Qdrant.
- `QdrantVectorStore` e `NVIDIAEmbeddings` da stack LangChain.
- `.env` local ignorado pelo Git e `.env.example` como modelo de configuração.

## Configuração

Preencha o `.env` local:

```dotenv
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
QDRANT_COLLECTION_NAME=ouros_knowledge
NVIDIA_API_KEY=nvapi-...
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_EMBEDDING_MODEL=nvidia/llama-nemotron-embed-1b-v2
MIDAS_DATABASE_URL=postgresql://midas_ro:senha@host-neon/segundo_prod?sslmode=require&channel_binding=require
MIDAS_DB_CONNECT_TIMEOUT=10
MCP_AUTH_TOKEN=gere-um-token-secreto-com-pelo-menos-32-caracteres
MCP_RESOURCE_URL=http://localhost:8000/mcp
```

O mesmo modelo de embedding precisa ter sido usado para gravar os vetores na coleção Qdrant. A coleção também precisa existir antes da busca; a ferramenta `qdrant_status` mostra essa condição sem chamar a NVIDIA.

No deployment público, sobrescreva `MCP_RESOURCE_URL` com `https://ms-midas-mcp.discloud.app/mcp` no ambiente da aplicação.

`MIDAS_DATABASE_URL` deve usar a role `midas_ro` criada pela migration. A role acessa as views do schema `midas`, sem as colunas de senha, e não recebe uma ferramenta de SQL arbitrário. A senha real deve ficar somente no `.env`/secret manager.

O endpoint MCP aceita access tokens do Keycloak no header `Authorization: Bearer <token>`. `MCP_AUTH_TOKEN` permanece apenas como fallback legado durante o rollout. Use um valor aleatório com pelo menos 32 caracteres e mantenha-o somente no `.env`/secret manager. Nos tokens oficiais, a identidade MIDAS vem dos claims assinados `account_type` e `database_id`. Os argumentos `user_type` e `user_id` precisam corresponder aos claims do JWT.

## Execução local

```bash
python -m venv .venv

# Linux/macOS/WSL
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

URLs:

- API: `http://localhost:8000`
- Swagger/OpenAPI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- MCP local: `http://localhost:8000/mcp/`
- MCP público: `https://ms-midas-mcp.discloud.app/mcp/`

O Swagger documenta `GET /` e `GET /health`. O endpoint MCP é um transporte
Streamable HTTP montado em `/mcp/`, então suas tools aparecem e são descritas
no handshake/listagem do cliente MCP, não como operações REST no Swagger.

## Docker

O container não copia `.env` para a imagem. Injete os secrets em runtime:

```bash
docker build -t ouros-knowledge-mcp .
docker run --rm --env-file .env -p 8000:8000 ouros-knowledge-mcp
```

## CLI de ingestão

O CLI lê `./docs` por padrão. Ele processa PDF, DOCX, TXT, Markdown, CSV, JSON e HTML:

```bash
python -m app.cli ingest
python -m app.cli ingest ./docs
python -m app.cli ingest contrato.pdf manual.docx
```

Antes do upload, confira os chunks sem gastar chamada da NVIDIA:

```bash
python -m app.cli ingest --dry-run
```

Opções úteis:

```bash
python -m app.cli ingest \
  --chunk-size 1000 \
  --chunk-overlap 150 \
  --batch-size 32
```

O CLI mantém `docs/.qdrant-manifest.json` com o SHA-256, modelo, coleção, parâmetros de chunking e IDs dos chunks. Em execuções seguintes, arquivos sem alteração e com os mesmos parâmetros são ignorados; documentos modificados, renomeados ou removidos dentro dos diretórios processados são reconciliados no Qdrant. O mesmo modelo configurado no servidor (`NVIDIA_EMBEDDING_MODEL`) é usado no upload. PDFs escaneados sem camada de texto precisam de OCR, que ainda não está incluído.

## Autenticação MCP

Envie o mesmo valor configurado em `MCP_AUTH_TOKEN` como `Authorization: Bearer <token>` nas chamadas MCP. O token compartilhado autentica o cliente, enquanto `user_type` e `user_id` identificam o usuário consultado. Qualquer cliente que possua esse token pode solicitar outra identidade; para clientes não confiáveis, use tokens individuais com identidade embutida.

Tools disponíveis:

- `search_knowledge(query, limit=5)`: busca semântica no Qdrant; `limit` entre 1 e 20.
- `qdrant_status()`: verifica a coleção Qdrant sem chamar a NVIDIA.
- `postgres_status()`: verifica a conexão PostgreSQL somente leitura do MIDAS.
- `get_user_context(user_type, user_id)`: retorna perfil, empresas e farms do usuário.
- `get_user_farm_data(user_type, user_id, limit=20)`: retorna farms, metas, consumos, lotes e dicas; `limit` entre 1 e 100.

Os valores aceitos para `user_type` são `farm_owner`, `company_employee` e `admin`. Exemplos de argumentos para um cliente MCP:

```json
{
  "name": "get_user_context",
  "arguments": {
    "user_type": "farm_owner",
    "user_id": 42
  }
}
```

```json
{
  "name": "get_user_farm_data",
  "arguments": {
    "user_type": "farm_owner",
    "user_id": 42,
    "limit": 20
  }
}
```

## Estrutura

```text
app/
├── api/routes.py          # endpoints FastAPI
├── core/config.py         # configuração carregada do .env
├── cli.py                 # ingestão incremental a partir de ./docs
├── mcp_server.py          # ferramentas MCP e transporte HTTP
├── services/auth.py       # validação do token fixo e identidade do usuário
├── services/database.py   # conexão read-only e contexto por usuário
├── services/knowledge.py  # Qdrant + NVIDIA embeddings
└── main.py                # aplicação FastAPI e montagem do MCP

docs/
└── .qdrant-manifest.json  # estado local da sincronização
```

## Licença

MIT. Consulte [LICENSE](LICENSE).

## Principais contribuidores

<!-- CONTRIBUTORS:START -->
- [@Nicolas25vlad](https://github.com/Nicolas25vlad) — 14 contribuições
- [@Andre-Roger](https://github.com/Andre-Roger) — 1 contribuição
- [@juwata](https://github.com/juwata) — 1 contribuição
<!-- CONTRIBUTORS:END -->


## Keycloak JWT

Este serviço é um resource server separado do MCP principal e valida tokens com audience `ms-mcp-server-ouros-knowledge-codemode`. A assinatura RS256 é validada pelo JWKS do realm `ouros`, junto de issuer, audience, expiração e identidade de negócio. O token estático continua somente como compatibilidade temporária de rollout.
