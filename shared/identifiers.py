"""Identificadores compartilhados entre core e ai.

empresa_id_from_string() resolve a inconsistência entre a CLI (que trata
empresa como string legível, ex.: "acme") e o domínio (que usa UUID em
Documento.empresa_id, Lancamento.empresa_id, PeriodoContabil.empresa_id).

A conversão é determinística: a mesma string sempre gera o mesmo UUID,
então "acme" na CLI, no pipeline e nos comandos de período resultam
sempre na mesma identidade — sem precisar de um cadastro de empresas
para o estágio atual do projeto (pré-multi-tenant real).
"""

from uuid import NAMESPACE_DNS, UUID, uuid5


def empresa_id_from_string(identificador: str) -> UUID:
    """Converte um identificador legível de empresa em UUID determinístico.

    Uso: empresa_id_from_string("acme") -> sempre o mesmo UUID.
    Já é um UUID válido? Ainda assim passa por uuid5 para normalizar
    o tipo de retorno e manter uma única fonte de verdade na conversão.
    """
    return uuid5(NAMESPACE_DNS, identificador)
