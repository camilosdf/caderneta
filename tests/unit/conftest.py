"""Configuração compartilhada de tests/unit/.

Bloqueia acesso a sockets durante toda a execução de tests/unit/ — proteção
em runtime que complementa a verificação estática
(infra/scripts/verificar_testes_hermeticos.py). Juntas, garantem que
tests/unit/ nunca dependa de infraestrutura externa (ADR 006).

SQLite em memória não usa sockets (é um motor local), então a suíte inteira
continua passando sem alterações com essa proteção ativa — é a prova de que
já éramos herméticos antes desta formalização.

tests/integration/ não importa este conftest — mantém acesso a rede livre,
pois depende de fato de Docker Compose (Postgres, Redis).
"""

import pytest
from pytest_socket import disable_socket


@pytest.fixture(autouse=True)
def bloquear_rede():
    """Desabilita qualquer chamada de socket de rede durante o teste.

    Se um teste em tests/unit/ tentar abrir uma conexão de rede real
    (Postgres, Redis, HTTP, etc.), falha imediatamente com SocketBlockedError
    em vez de travar esperando timeout ou depender de um serviço externo
    estar disponível.

    allow_unix_socket=True: ferramentas como o TestClient do FastAPI/Starlette
    usam socket.socketpair() internamente para a ponte de thread do event
    loop assíncrono — é IPC local (sem rede real), não infraestrutura
    externa, então não deveria ser bloqueado pela regra do ADR 006. Sockets
    de rede real (AF_INET/AF_INET6) continuam totalmente bloqueados.
    """
    disable_socket(allow_unix_socket=True)
