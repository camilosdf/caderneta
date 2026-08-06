# ADR 002 — Auditoria com Hash Chain Imutável

**Status:** Aceito  
**Data:** 2026-07  
**Decisores:** Equipe

---

## Contexto

Todo sistema contábil precisa de rastreabilidade. A questão é o nível de garantia:
- Log simples: registra o que aconteceu, mas pode ser adulterado
- Log append-only via regra de banco: impede UPDATE/DELETE na aplicação, mas DBA pode alterar
- Hash chain: cada evento contém o hash do evento anterior — adulteração é detectável matematicamente

Para um sistema sujeito a auditoria fiscal, o nível de garantia importa.

## Decisão

O audit log implementa uma **hash chain**:

```python
@dataclass
class EventoAuditoria:
    id: UUID
    tipo: TipoEvento
    timestamp: datetime
    payload: dict
    hash_anterior: str          # hash do evento imediatamente anterior
    hash_proprio: str           # SHA-256(id + tipo + timestamp + payload + hash_anterior)
```

Regras:
1. O primeiro evento da chain tem `hash_anterior = "GENESIS"`
2. Cada novo evento lê o `hash_proprio` do evento mais recente e o usa como `hash_anterior`
3. Uma função `verificar_integridade()` percorre a chain e valida cada hash
4. O banco aplica `RULE ... DO INSTEAD NOTHING` em UPDATE e DELETE
5. Documentos originais são gravados em storage write-once (Etapa 5)

Adicionalmente, o audit log versiona:
- Regras de classificação (qual versão da regra foi aplicada em cada lançamento)
- Plano de contas (qual versão do plano estava ativa no momento do lançamento)
- Finance Knowledge Base (qual versão dos embeddings foi usada)

## Alternativas consideradas

**Alternativa 1:** Log simples com timestamp  
Rejeitada. Não detecta adulteração. Insuficiente para auditoria fiscal.

**Alternativa 2:** Blockchain externo (ex: Hyperledger)  
Rejeitada. Overhead operacional desproporcional. A hash chain interna oferece as mesmas garantias para o caso de uso.

**Alternativa 3:** Assinatura digital por evento  
Complementar, não substituta. Pode ser adicionada na Etapa 5 sem alterar a estrutura da chain.

## Consequências

**Positivas:**
- Qualquer adulteração histórica é detectável matematicamente
- Auditores externos podem verificar a integridade sem acesso ao código
- Versionamento de regras permite reproduzir exatamente qual lógica gerou cada lançamento

**Negativas:**
- Inserção de eventos é levemente mais lenta (requer leitura do último hash)
- Não é possível inserir eventos retroativos (o que é uma feature, não um bug)
