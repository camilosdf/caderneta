# ADR 007 — Política de Versionamento Sequencial

**Status:** Aceito  
**Data:** 2026-07  
**Decisores:** Equipe + Proprietário do Produto

---

## Contexto

O projeto Caderneta possui duas fases bem distintas:

- **Pré-produção:** desenvolvimento ativo, arquitetura evoluindo, não apto
  para uso contábil real. Erros não impactam balanços reais.
- **Pós-produção:** sistema homologado pelo Contador CRC responsável, em uso
  com documentos e lançamentos reais. Erros têm consequência fiscal.

Essa distinção precisa ser visível imediatamente no número de versão —
tanto para a equipe técnica quanto para o contador e auditores.

---

## Decisão

O Caderneta adota versionamento sequencial com três dígitos separados
por ponto, no formato:

```
FASE.ETAPA.REVISÃO
```

### Fase (primeiro dígito)

| Valor | Significado |
|-------|-------------|
| `0`   | Pré-produção — desenvolvimento, testes, homologação |
| `1`   | Produção — homologado pelo CRC, dados reais |
| `2+`  | Versão maior de produção — mudança arquitetural significativa |

**A transição de `0.x.x` para `1.0.0` é um marco formal**, não técnico.
Requer aprovação do Contador CRC responsável e do Especialista em
Controles Internos, documentada no audit log como evento
`VERSAO_HOMOLOGADA`.

### Etapa (segundo dígito)

Mapeia diretamente às 10 etapas de maturidade do projeto:

| Etapa | Versão | Conteúdo principal |
|-------|--------|--------------------|
| 0 — Fundação | `0.0.x` | Monorepo, ADRs, infraestrutura |
| 1 — Domínio | `0.1.x` | Entidades, Value Objects, invariantes |
| 2 — Pipeline | `0.2.x` | Fluxo com mocks, ports, eventos |
| 3 — Parsers | `0.3.x` | OFX, XML NF-e, CSV determinísticos |
| 4 — Motor Contábil | `0.4.x` | Regras, Tax Engine, estorno, CLI |
| 5 — Auditoria | `0.5.x` | Hash chain, versionamento, snapshots |
| 6 — Interface | `0.6.x` | FastAPI + HTMX, fila de aprovação |
| 7 — IA | `0.7.x` | Embeddings, LLM, OCR como plugins |
| 8 — Conciliação | `0.8.x` | OFX, Open Finance, Motor de diferenças |
| 9 — Integrações | `0.9.x` | GnuCash, ERPNext, adaptadores |
| Homologação | `0.999` | Candidato a produção — congelado para auditoria |
| **Produção** | **`1.0.0`** | **Aprovado pelo CRC — dados reais** |

### Revisão (terceiro dígito)

Incremento sequencial simples dentro de uma etapa:
- `0.3.0` → primeira entrega da Etapa 3
- `0.3.1` → correção ou melhoria incremental
- `0.3.2` → próxima iteração
- `0.4.0` → início da Etapa 4

### Formato de exibição

Para clareza máxima, o sistema exibe sempre três casas em cada dígito
nas interfaces voltadas ao usuário e nos nomes de arquivo:

```
v0.003.001   ← pré-produção, Etapa 3, revisão 1
v1.000.000   ← produção, versão inicial
v1.000.012   ← produção, décima segunda revisão
v2.000.000   ← segunda geração do sistema
```

O `pyproject.toml` e PyPI usam o formato padrão PEP 440 (`0.3.1`).
A exibição formatada com zeros à esquerda é responsabilidade da CLI e
dos nomes de arquivo de pacote.

---

## Exemplos práticos

```bash
# Nome do pacote gerado pelo CI
caderneta-v0.003.001.tar.gz    # Etapa 3, revisão 1
caderneta-v0.999.000.tar.gz    # Candidato a produção
caderneta-v1.000.000.tar.gz    # Produção — marco histórico

# Exibição na CLI
caderneta status
# → Caderneta v0.003.001 (pré-produção)
# → Caderneta v1.000.000 (produção)

# Audit log
# → versao_sistema: "0.3.1"
# → versao_exibicao: "v0.003.001"
```

---

## Marco de homologação (`0.999`)

Antes de liberar `1.0.0`, o sistema passa por `0.999.x`:
- Código congelado (apenas correções críticas)
- Contador CRC valida lançamentos gerados contra lançamentos manuais
- Especialista em Controles verifica a hash chain de auditoria
- Relatório de homologação assinado e arquivado
- Evento `VERSAO_HOMOLOGADA` gravado na hash chain

Somente após esse processo o segundo dígito sobe de `999` para `000`
e o primeiro dígito sobe de `0` para `1`.

---

## Histórico de versões

| Versão | Data | Conteúdo |
|--------|------|----------|
| v0.000.001 | 2026-07 | Estrutura inicial monorepo (retroativo) |
| v0.001.001 | 2026-07 | Modelo de domínio, Value Objects |
| v0.002.001 | 2026-07 | Pipeline, ports, eventos tipados |
| v0.003.001 | 2026-07 | Parsers OFX/CSV, CLI, pyproject corrigido |

---

## Alternativas consideradas

**SemVer padrão (MAJOR.MINOR.PATCH):** Rejeitado. Não comunica a
distinção pré/pós-produção de forma imediata para não-técnicos.

**CalVer (2026.07.01):** Rejeitado. Não mapeia às etapas de maturidade
e não distingue pré de pós-produção.

**Sufixo alpha/beta:** Rejeitado como sufixo adicional por criar versões
longas (`0.3.0b2`). A distinção pelo primeiro dígito (`0` vs `1`) é
mais limpa e legível.

## Consequências

**Positivas:**
- Qualquer stakeholder vê imediatamente se o sistema está em produção
- O número de versão comunica em qual etapa de maturidade o projeto está
- A transição `0→1` é um evento formal e auditável
- Nomes de pacote ordenam-se corretamente por string (`v0.003` < `v0.999` < `v1.000`)

**Negativas:**
- Requer disciplina para não avançar o segundo dígito sem entregar
  o conteúdo da etapa correspondente
- A versão `0.999` pode causar estranheza — documentar bem nos releases
