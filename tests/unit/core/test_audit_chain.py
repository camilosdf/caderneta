"""Testes da Hash Chain de Auditoria.

Verifica que:
- Eventos são gravados em sequência com hashes válidos
- Adulteração é detectada pela verificação de integridade
- Deduplicação por hash de documento funciona
"""

import json
from pathlib import Path

import pytest

from core.audit.chain import AuditChain, EventoAuditoria, GENESIS_HASH, TipoEvento


@pytest.fixture
def chain(tmp_path) -> AuditChain:
    return AuditChain(tmp_path / "audit.jsonl")


class TestAuditChain:
    def test_primeiro_evento_tem_genesis_como_anterior(self, chain):
        ev = chain.registrar(
            tipo=TipoEvento.DOCUMENTO_RECEBIDO,
            payload={"nome": "extrato.ofx"},
        )
        assert ev.hash_anterior == GENESIS_HASH

    def test_segundo_evento_aponta_para_primeiro(self, chain):
        ev1 = chain.registrar(
            tipo=TipoEvento.DOCUMENTO_RECEBIDO,
            payload={"nome": "extrato.ofx"},
        )
        ev2 = chain.registrar(
            tipo=TipoEvento.DOCUMENTO_PROCESSADO,
            payload={"lancamentos": 5},
        )
        assert ev2.hash_anterior == ev1.hash_proprio

    def test_hash_proprio_e_deterministico(self, chain):
        ev = chain.registrar(
            tipo=TipoEvento.DOCUMENTO_RECEBIDO,
            payload={"nome": "extrato.ofx"},
        )
        # O hash gravado deve ser o mesmo que recalcular manualmente
        assert ev.hash_proprio == ev.calcular_hash()

    def test_chain_integra_apos_multiplos_eventos(self, chain):
        for i in range(10):
            chain.registrar(
                tipo=TipoEvento.LANCAMENTO_GERADO,
                payload={"index": i},
            )
        integra, erros = chain.verificar_integridade()
        assert integra is True
        assert erros == []

    def test_adulteracao_detectada(self, chain, tmp_path):
        arquivo = tmp_path / "audit.jsonl"
        chain2 = AuditChain(arquivo)

        chain2.registrar(TipoEvento.DOCUMENTO_RECEBIDO, {"nome": "a.ofx"})
        chain2.registrar(TipoEvento.DOCUMENTO_PROCESSADO, {"ok": True})

        # Adulterar o primeiro evento
        linhas = arquivo.read_text().splitlines()
        evento = json.loads(linhas[0])
        evento["payload"]["nome"] = "ADULTERADO.ofx"  # alterar conteúdo
        linhas[0] = json.dumps(evento)
        arquivo.write_text("\n".join(linhas) + "\n")

        chain3 = AuditChain(arquivo)
        integra, erros = chain3.verificar_integridade()
        assert integra is False
        assert len(erros) > 0

    def test_deduplicacao_por_hash(self, chain):
        hash_doc = "abc123" * 10  # 60 chars
        chain.registrar(
            tipo=TipoEvento.DOCUMENTO_PROCESSADO,
            payload={"nome": "extrato.ofx"},
            documento_hash=hash_doc,
        )
        resultado = chain.buscar_por_hash_documento(hash_doc)
        assert resultado is not None
        assert resultado["documento_hash"] == hash_doc

    def test_hash_nao_existente_retorna_none(self, chain):
        resultado = chain.buscar_por_hash_documento("hash_inexistente")
        assert resultado is None

    def test_chain_vazia_e_integra(self, tmp_path):
        chain = AuditChain(tmp_path / "vazio.jsonl")
        integra, erros = chain.verificar_integridade()
        assert integra is True
        assert erros == []

    def test_chain_persiste_entre_instancias(self, tmp_path):
        """Novo AuditChain lendo o mesmo arquivo continua a chain corretamente."""
        arquivo = tmp_path / "audit.jsonl"

        c1 = AuditChain(arquivo)
        ev1 = c1.registrar(TipoEvento.DOCUMENTO_RECEBIDO, {"nome": "a.ofx"})

        # Nova instância — deve continuar de onde parou
        c2 = AuditChain(arquivo)
        ev2 = c2.registrar(TipoEvento.DOCUMENTO_PROCESSADO, {"ok": True})

        assert ev2.hash_anterior == ev1.hash_proprio

        # Verificar integridade com terceira instância
        c3 = AuditChain(arquivo)
        integra, erros = c3.verificar_integridade()
        assert integra is True
