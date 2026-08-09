"""Audit Log com Hash Chain Imutável — Etapa 5.

Cada evento contém o hash do evento anterior.
Adulteração de qualquer evento invalida toda a cadeia subsequente.
Verificável matematicamente por auditores externos.

Baseado no ADR 002: docs/adr/002-auditoria-hash-chain.md
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64  # hash do "bloco gênese" — sem evento anterior


class TipoEvento(StrEnum):
    DOCUMENTO_RECEBIDO       = "DOCUMENTO_RECEBIDO"
    DOCUMENTO_DUPLICADO      = "DOCUMENTO_DUPLICADO"
    DOCUMENTO_PROCESSADO     = "DOCUMENTO_PROCESSADO"
    DOCUMENTO_ERRO           = "DOCUMENTO_ERRO"
    LANCAMENTO_GERADO        = "LANCAMENTO_GERADO"
    LANCAMENTO_APROVADO      = "LANCAMENTO_APROVADO"
    LANCAMENTO_REJEITADO     = "LANCAMENTO_REJEITADO"
    CORRECAO_HUMANA          = "CORRECAO_HUMANA"
    REGRA_ALTERADA           = "REGRA_ALTERADA"
    PLANO_CONTAS_ALTERADO    = "PLANO_CONTAS_ALTERADO"
    PERIODO_FECHADO          = "PERIODO_FECHADO"
    CSV_GERADO               = "CSV_GERADO"
    CSV_IMPORTADO            = "CSV_IMPORTADO"
    EXPORTACAO_GNUCASH       = "EXPORTACAO_GNUCASH"
    ERRO_SISTEMA             = "ERRO_SISTEMA"
    USUARIO_LOGIN            = "USUARIO_LOGIN"
    USUARIO_LOGOUT           = "USUARIO_LOGOUT"
    # Etapa 8 — Motor de Conciliação Bancária
    CONCILIACAO_INICIADA     = "CONCILIACAO_INICIADA"
    MATCH_IDENTIFICADO       = "MATCH_IDENTIFICADO"
    CONCILIACAO_AMBIGUA      = "CONCILIACAO_AMBIGUA"
    DIVERGENCIA_IDENTIFICADA = "DIVERGENCIA_IDENTIFICADA"
    CONCILIACAO_APROVADA     = "CONCILIACAO_APROVADA"
    CONCILIACAO_REJEITADA    = "CONCILIACAO_REJEITADA"
    EXTRATO_IMPORTADO        = "EXTRATO_IMPORTADO"


@dataclass
class EventoAuditoria:
    """Um evento imutável na hash chain."""
    id: str
    tipo: TipoEvento
    timestamp: str
    versao_sistema: str
    payload: dict[str, Any]
    hash_anterior: str          # hash do evento imediatamente anterior (ou GENESIS)
    hash_proprio: str = ""      # calculado no momento da criação

    # Campos opcionais de contexto
    usuario: str | None = None
    empresa_id: str | None = None
    lancamento_id: str | None = None
    documento_id: str | None = None
    documento_hash: str | None = None
    campo_alterado: str | None = None
    valor_anterior: str | None = None
    valor_novo: str | None = None
    versao_regra: int | None = None

    def calcular_hash(self) -> str:
        """Calcula SHA-256 determinístico deste evento."""
        conteudo = json.dumps({
            "id": self.id,
            "tipo": self.tipo,
            "timestamp": self.timestamp,
            "versao_sistema": self.versao_sistema,
            "payload": self.payload,
            "hash_anterior": self.hash_anterior,
            "usuario": self.usuario,
            "empresa_id": self.empresa_id,
            "lancamento_id": self.lancamento_id,
            "documento_id": self.documento_id,
            "documento_hash": self.documento_hash,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(conteudo.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tipo": self.tipo.value,
            "timestamp": self.timestamp,
            "versao_sistema": self.versao_sistema,
            "hash_anterior": self.hash_anterior,
            "hash_proprio": self.hash_proprio,
            "usuario": self.usuario,
            "empresa_id": self.empresa_id,
            "lancamento_id": self.lancamento_id,
            "documento_id": self.documento_id,
            "documento_hash": self.documento_hash,
            "campo_alterado": self.campo_alterado,
            "valor_anterior": self.valor_anterior,
            "valor_novo": self.valor_novo,
            "versao_regra": self.versao_regra,
            "payload": self.payload,
        }


class AuditChain:
    """
    Hash chain de auditoria — append-only.

    Fase atual: JSONL local (sem dependência de banco).
    Fase futura: PostgreSQL com coluna hash_chain indexada.
    """

    @property
    def VERSAO_SISTEMA(self) -> str:  # type: ignore[override]  # noqa: N802
        from core.versao import VERSAO
        return VERSAO.pep440

    def __init__(self, arquivo_log: Path):
        self._arquivo = arquivo_log
        self._arquivo.parent.mkdir(parents=True, exist_ok=True)
        self._ultimo_hash: str = self._carregar_ultimo_hash()

    def registrar(
        self,
        tipo: TipoEvento,
        payload: dict[str, Any],
        usuario: str | None = None,
        empresa_id: str | None = None,
        lancamento_id: str | None = None,
        documento_id: str | None = None,
        documento_hash: str | None = None,
        campo_alterado: str | None = None,
        valor_anterior: str | None = None,
        valor_novo: str | None = None,
        versao_regra: int | None = None,
    ) -> EventoAuditoria:
        """Registra um evento e retorna o evento gravado com seu hash."""

        evento = EventoAuditoria(
            id=str(uuid.uuid4()),
            tipo=tipo,
            timestamp=datetime.now(UTC).isoformat() + "Z",
            versao_sistema=self.VERSAO_SISTEMA,
            payload=payload,
            hash_anterior=self._ultimo_hash,
            usuario=usuario,
            empresa_id=empresa_id,
            lancamento_id=lancamento_id,
            documento_id=documento_id,
            documento_hash=documento_hash,
            campo_alterado=campo_alterado,
            valor_anterior=valor_anterior,
            valor_novo=valor_novo,
            versao_regra=versao_regra,
        )

        evento.hash_proprio = evento.calcular_hash()

        # Gravação atômica — append-only
        with open(self._arquivo, "a", encoding="utf-8") as f:
            f.write(json.dumps(evento.to_dict(), ensure_ascii=False) + "\n")

        self._ultimo_hash = evento.hash_proprio
        return evento

    def verificar_integridade(self) -> tuple[bool, list[str]]:
        """
        Verifica a integridade da chain percorrendo todos os eventos.
        Retorna (integra, lista_de_erros).
        """
        if not self._arquivo.exists():
            return True, []

        erros: list[str] = []
        hash_esperado = GENESIS_HASH

        with open(self._arquivo, encoding="utf-8") as f:
            for i, linha in enumerate(f, 1):
                try:
                    dado = json.loads(linha)
                except json.JSONDecodeError:
                    erros.append(f"Linha {i}: JSON inválido")
                    continue

                # Verificar hash_anterior
                if dado.get("hash_anterior") != hash_esperado:
                    erros.append(
                        f"Linha {i} (evento {dado.get('id', '?')}): "
                        f"hash_anterior inválido — possível adulteração"
                    )

                # Recalcular hash_proprio
                evento = EventoAuditoria(
                    id=dado["id"],
                    tipo=TipoEvento(dado["tipo"]),
                    timestamp=dado["timestamp"],
                    versao_sistema=dado["versao_sistema"],
                    payload=dado["payload"],
                    hash_anterior=dado["hash_anterior"],
                    usuario=dado.get("usuario"),
                    empresa_id=dado.get("empresa_id"),
                    lancamento_id=dado.get("lancamento_id"),
                    documento_id=dado.get("documento_id"),
                    documento_hash=dado.get("documento_hash"),
                )
                hash_recalculado = evento.calcular_hash()

                if hash_recalculado != dado.get("hash_proprio"):
                    erros.append(
                        f"Linha {i} (evento {dado.get('id', '?')}): "
                        f"hash_proprio inválido — conteúdo adulterado"
                    )

                hash_esperado = dado.get("hash_proprio", "")

        return len(erros) == 0, erros

    def buscar_por_hash_documento(self, hash_doc: str) -> dict | None:
        """Verifica se um documento já foi processado (deduplicação)."""
        if not self._arquivo.exists():
            return None

        with open(self._arquivo, encoding="utf-8") as f:
            for linha in f:
                try:
                    evento = json.loads(linha)
                    if (evento.get("documento_hash") == hash_doc and
                            evento.get("tipo") == TipoEvento.DOCUMENTO_PROCESSADO.value):
                        return evento
                except json.JSONDecodeError:
                    continue
        return None

    def _carregar_ultimo_hash(self) -> str:
        """Lê o hash do último evento para continuar a chain."""
        if not self._arquivo.exists():
            return GENESIS_HASH

        ultimo: str | None = None
        with open(self._arquivo, encoding="utf-8") as f:
            for linha in f:
                try:
                    evento = json.loads(linha)
                    ultimo = evento.get("hash_proprio")
                except json.JSONDecodeError:
                    continue

        return ultimo or GENESIS_HASH
