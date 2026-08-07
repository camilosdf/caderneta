"""Testes de api/auth/security.py — hash e verificação Argon2id (ADR 008).

Cobre: hash produz valores diferentes por chamada (salt), verificação
correta de senha certa/errada, hash malformado não levanta exceção.
"""

from api.auth.security import hash_senha, verificar_senha


class TestHashSenha:
    def test_hash_nao_e_texto_puro(self) -> None:
        h = hash_senha("minhasenha123")
        assert h != "minhasenha123"

    def test_hash_comeca_com_prefixo_argon2id(self) -> None:
        h = hash_senha("minhasenha123")
        assert h.startswith("$argon2id$")

    def test_hashes_diferentes_para_mesma_senha(self) -> None:
        """Salt aleatório garante hashes diferentes mesmo para senha igual."""
        h1 = hash_senha("mesmasenha")
        h2 = hash_senha("mesmasenha")
        assert h1 != h2


class TestVerificarSenha:
    def test_senha_correta_verifica_true(self) -> None:
        h = hash_senha("senhaCorreta123")
        assert verificar_senha("senhaCorreta123", h) is True

    def test_senha_incorreta_verifica_false(self) -> None:
        h = hash_senha("senhaCorreta123")
        assert verificar_senha("senhaErrada456", h) is False

    def test_senha_vazia_nao_verifica(self) -> None:
        h = hash_senha("senhaCorreta123")
        assert verificar_senha("", h) is False

    def test_hash_malformado_nao_levanta_excecao(self) -> None:
        assert verificar_senha("qualquer", "hash-nao-e-argon2-valido") is False

    def test_hash_vazio_nao_levanta_excecao(self) -> None:
        assert verificar_senha("qualquer", "") is False

    def test_case_sensitive(self) -> None:
        h = hash_senha("SenhaComMaiuscula")
        assert verificar_senha("senhacomminuscula", h) is False
        assert verificar_senha("SenhaComMaiuscula", h) is True
