"""Testes do módulo de versionamento — ADR 007."""

import pytest
from core.versao import Versao, VERSAO, VERSAO_ATUAL


class TestVersaoParse:
    def test_parse_formato_pep440(self):
        v = Versao.parse("0.3.1")
        assert v.fase == 0
        assert v.etapa == 3
        assert v.revisao == 1

    def test_parse_formato_exibicao(self):
        v = Versao.parse("v0.003.001")
        assert v.fase == 0
        assert v.etapa == 3
        assert v.revisao == 1

    def test_parse_producao(self):
        v = Versao.parse("1.0.0")
        assert v.e_producao is True
        assert v.fase == 1

    def test_parse_candidato(self):
        v = Versao.parse("0.999.0")
        assert v.e_candidato is True

    def test_parse_invalido(self):
        with pytest.raises(ValueError):
            Versao.parse("1.2")

    def test_parse_invalido_letras(self):
        with pytest.raises((ValueError, AttributeError)):
            Versao.parse("abc")


class TestVersaoFormatos:
    def test_pep440(self):
        v = Versao(0, 3, 1)
        assert v.pep440 == "0.3.1"

    def test_exibicao_zeros_a_esquerda(self):
        v = Versao(0, 3, 1)
        assert v.exibicao == "v0.003.001"

    def test_exibicao_producao(self):
        v = Versao(1, 0, 0)
        assert v.exibicao == "v1.000.000"

    def test_nome_pacote(self):
        v = Versao(0, 3, 1)
        assert v.nome_pacote == "caderneta-v0.003.001"

    def test_str_contem_etapa_e_status(self):
        v = Versao(0, 3, 1)
        s = str(v)
        assert "Parsers" in s
        assert "pré-produção" in s

    def test_str_producao(self):
        v = Versao(1, 0, 0)
        assert "produção" in str(v)


class TestVersaoStatus:
    def test_pre_producao(self):
        assert Versao(0, 3, 1).e_producao is False

    def test_producao(self):
        assert Versao(1, 0, 0).e_producao is True

    def test_segunda_geracao_producao(self):
        assert Versao(2, 0, 0).e_producao is True

    def test_candidato_nao_e_producao(self):
        v = Versao(0, 999, 0)
        assert v.e_candidato is True
        assert v.e_producao is False


class TestVersaoOrdenacao:
    def test_revisao_menor_que_proxima(self):
        assert Versao(0, 3, 0) < Versao(0, 3, 1)

    def test_etapa_menor_que_proxima(self):
        assert Versao(0, 3, 5) < Versao(0, 4, 0)

    def test_pre_producao_menor_que_producao(self):
        assert Versao(0, 9, 99) < Versao(1, 0, 0)

    def test_candidato_menor_que_producao(self):
        assert Versao(0, 999, 5) < Versao(1, 0, 0)


class TestVersaoNavegacao:
    def test_proxima_revisao(self):
        v = Versao(0, 3, 1)
        assert v.proxima_revisao() == Versao(0, 3, 2)

    def test_proxima_etapa_zera_revisao(self):
        v = Versao(0, 3, 5)
        assert v.proxima_etapa() == Versao(0, 4, 0)

    def test_etapa_9_vai_para_999(self):
        v = Versao(0, 9, 2)
        assert v.proxima_etapa() == Versao(0, 999, 0)

    def test_promover_candidato_para_producao(self):
        v = Versao(0, 999, 3)
        assert v.promover_producao() == Versao(1, 0, 0)

    def test_promover_nao_candidato_falha(self):
        v = Versao(0, 3, 1)
        with pytest.raises(ValueError, match="candidatos"):
            v.promover_producao()


class TestVersaoAtual:
    def test_versao_atual_existe(self):
        assert VERSAO is not None

    def test_versao_atual_consistente_com_constante(self):
        v = Versao.parse(VERSAO_ATUAL)
        assert v == VERSAO

    def test_versao_atual_e_pre_producao(self):
        """O sistema ainda está em pré-produção."""
        assert VERSAO.e_producao is False

    def test_versao_para_audit_tem_campos_obrigatorios(self):
        from core.versao import versao_para_audit
        d = versao_para_audit()
        assert "versao_pep440" in d
        assert "versao_exibicao" in d
        assert "etapa" in d
        assert "status" in d
        assert "e_producao" in d

    def test_exibicao_formato_correto(self):
        import re
        assert re.match(r"^v\d+\.\d{3}\.\d{3}$", VERSAO.exibicao), \
            f"Formato inválido: {VERSAO.exibicao}"
