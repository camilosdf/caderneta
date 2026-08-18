# CLAUDE.md — Caderneta

## 1. Finalidade

Este arquivo define instruções permanentes para análise, planejamento e implementação no projeto Caderneta.

O Caderneta é um sistema financeiro/contábil orientado a rastreabilidade, partidas dobradas, importação de documentos, classificação, conciliação e exportação.

Estas instruções devem ser consideradas em conjunto com os ADRs, o Plano Completo, a Matriz de Prontidão, a Pauta de Deliberação do Gate 0 e o código efetivamente existente.

> Regra fundamental: o código real e os artefatos de governança têm precedência sobre suposições.

---

## 2. Regra de segurança de alteração

Não implementar uma mudança arquitetural relevante imediatamente após receber uma solicitação.

Antes de alterar código:

1. inspecionar o estado real do repositório;
2. localizar componentes relacionados;
3. ler os ADRs pertinentes;
4. verificar o estado de testes;
5. verificar migrations;
6. verificar contratos/interfaces existentes;
7. verificar a documentação de governança;
8. produzir uma análise de lacunas;
9. propor o desenho técnico;
10. aguardar autorização explícita quando a tarefa exigir planejamento prévio.

Não criar componentes que já existam com outro nome.

Não substituir arquitetura existente sem justificar tecnicamente a mudança.

---

## 3. Governança e homologação

O Caderneta possui processo formal de Gate 0/pré-homologação.

Antes de modificar o escopo da versão em homologação:

- verificar a versão declarada;
- verificar a Matriz de Prontidão;
- verificar a Pauta de Deliberação;
- verificar os bloqueadores;
- verificar decisões pendentes;
- verificar ADRs vigentes.

Não misturar uma nova funcionalidade relevante com o congelamento/homologação de uma versão sem decisão explícita.

Quando uma funcionalidade já estiver prevista no Plano Completo, não classificá-la automaticamente como "nova funcionalidade": primeiro determinar se ela está implementada, parcialmente implementada ou ausente.

---

## 4. Princípios arquiteturais

### 4.1 Reutilização antes de criação

Antes de criar qualquer componente, procurar:

- domínio existente;
- interfaces existentes;
- services;
- repositories;
- parsers;
- pipeline;
- motores;
- classificação;
- auditoria;
- conciliação;
- persistência;
- CLI;
- exportadores.

Preferir extensão de componentes existentes.

Não criar:

- novo motor sem necessidade;
- novo classificador paralelo;
- novo mecanismo de partidas dobradas;
- novo mecanismo de conciliação;
- novo mecanismo de auditoria;
- novo mecanismo de parcelas;
- nova infraestrutura OCR sem justificativa;
- nova camada arquitetural apenas por preferência.

### 4.2 Separação de responsabilidades

Preservar a separação entre:

- domínio;
- aplicação;
- infraestrutura;
- API/interface;
- parsing;
- classificação;
- persistência;
- auditoria;
- integração externa.

Parsers não devem assumir responsabilidades contábeis que pertençam ao domínio/aplicação.

---

## 5. IA e classificação

IA é auxiliar.

LLM, embeddings e modelos de classificação:

- não aprovam lançamentos;
- não substituem regras determinísticas;
- não decidem isoladamente a natureza contábil;
- não devem corrigir silenciosamente divergências;
- devem fornecer método/confiança quando aplicável.

Regras determinísticas têm precedência.

Baixa confiança deve resultar em revisão humana conforme os thresholds existentes.

Não criar um segundo classificador paralelo quando já existir a infraestrutura de classificação.

---

## 6. Contabilidade

O Caderneta deve preservar partidas dobradas.

Utilizar as entidades contábeis já existentes, especialmente `Lancamento`, `Split` e `ContaContabil`, quando forem adequadas.

Nunca contornar as validações de equilíbrio.

Para cartão de crédito, a regra fundamental é:

### Compra

    D — Despesa/Ativo apropriado
    C — Conta do Cartão de Crédito

### Pagamento da fatura

    D — Conta do Cartão de Crédito
    C — Conta Bancária

A compra não deve ser lançada diretamente contra o banco.

O pagamento da fatura não deve gerar uma nova despesa.

---

## 7. Suporte a faturas PDF de cartão de crédito

O Caderneta deve considerar suporte completo a:

1. identificação de fatura de cartão;
2. extração de PDF texto;
3. OCR de PDF imagem quando necessário;
4. identificação do emissor;
5. identificação do cartão;
6. criação/localização do cartão;
7. criação/localização da conta contábil;
8. extração dos itens;
9. classificação;
10. parcelamento;
11. encargos;
12. estornos/créditos;
13. validação do total;
14. contabilização;
15. aprovação;
16. exportação;
17. conciliação do pagamento;
18. auditoria e rastreabilidade;
19. idempotência.

O Plano Completo já contempla faturas de cartão em PDF, OCR e tratamento de parcelas. Portanto, ao trabalhar nessa funcionalidade, verificar primeiro o que já existe.

---

## 8. Tipo de documento

Avaliar a necessidade de um tipo explícito equivalente a:

    FATURA_CARTAO_PDF

Não assumir que todo PDF é apenas `PDF_TEXTO`.

Fluxo conceitual:

    PDF
     |
     v
    detecção
     |
     +--> PDF comum
     |
     +--> FATURA_CARTAO_PDF
              |
              v
          extração/OCR
              |
              v
            parser

A identificação deve usar evidências determinísticas sempre que possível.

---

## 9. Modelo conceitual de cartão

Avaliar, antes de implementar, se são necessárias entidades específicas como:

    CartaoCredito
    FaturaCartao
    CompraCartao

Proposta conceitual:

    CartaoCredito
    - id
    - empresa_id
    - emissor
    - bandeira
    - final_cartao
    - nome
    - conta_contabil_id
    - ativo

    FaturaCartao
    - id
    - documento_id
    - cartao_id
    - periodo_inicio
    - periodo_fim
    - vencimento
    - valor_total
    - pagamento_minimo
    - hash_documento
    - status
    - confidence

    CompraCartao
    - id
    - fatura_id
    - data_compra
    - descricao
    - valor
    - parcela_atual
    - total_parcelas
    - fornecedor_id
    - lancamento_id
    - confidence

Esses modelos são propostas, não contratos. Comparar sempre com o domínio existente antes de criar novas entidades.

---

## 10. Conta contábil do cartão

O cartão é o instrumento financeiro; a conta contábil representa a obrigação.

Não criar uma conta contábil para cada fatura.

Exemplo:

    Passivo Circulante
    └── Cartões de Crédito
        └── Nubank Mastercard ****1234

A conta deve ser permanente para aquele cartão.

A criação deve ser:

- idempotente;
- auditada;
- vinculada ao cartão;
- impedida de gerar duplicidade.

Nunca hardcodar códigos de plano de contas se o sistema possuir plano parametrizável.

---

## 11. Parser de cartão

Não assumir um layout universal.

Projetar uma interface comum, caso o código atual não forneça uma:

    CartaoPDFParser

Podem existir implementações específicas por emissor:

    Nubank
    Itaú
    Inter
    Bradesco
    Santander
    ...

e/ou um parser genérico.

Não implementar vários parsers antes de validar o contrato com um caso real.

Começar pelo emissor disponível para homologação.

---

## 12. PDF texto e OCR

Suportar:

    PDF com camada de texto
        -> extração direta

e:

    PDF imagem
        -> OCR
        -> texto estruturado

Reutilizar a infraestrutura existente.

Não adicionar nova biblioteca sem verificar as dependências atuais e justificar a necessidade.

---

## 13. Fatura como documento agregador

Uma fatura não deve ser tratada como uma única despesa.

Ela agrega itens.

Exemplo:

    Amazon          300
    Supermercado    500
    Combustível     250
    Internet        200

Os itens devem ser classificados individualmente.

Os lançamentos devem preservar o vínculo com a fatura.

Não duplicar despesas lançando novamente o total da fatura.

---

## 14. Tipos de item da fatura

Avaliar uma classificação equivalente a:

    COMPRA
    PARCELA
    ESTORNO
    JUROS
    MULTA
    IOF
    ANUIDADE
    CREDITO
    OUTRO

Cada tipo deve ter tratamento contábil apropriado.

Exemplo:

    COMPRA
    D Despesa
    C Cartão

    JUROS
    D Despesa Financeira
    C Cartão

    ESTORNO/CREDITO
    tratamento inverso/apropriado

Nunca apagar o lançamento original para representar um estorno.

---

## 15. Parcelamento

Reutilizar o mecanismo de parcelamento já existente.

Antes de criar qualquer novo modelo, procurar por:

- `e_parcelado`;
- `parcela_atual`;
- `total_parcelas`;
- `lancamento_pai_id`;
- mecanismos existentes de agrupamento/normalização.

Preservar a capacidade de:

- identificar parcela atual;
- identificar total de parcelas;
- relacionar parcelas;
- conciliar parcelas;
- rastrear a compra original;
- tratar estorno/cancelamento.

---

## 16. Validação do total da fatura

Não contabilizar automaticamente uma fatura quando os valores extraídos não fecharem.

Validar conceitualmente:

    soma dos itens
    + encargos
    - créditos/estornos
    = total da fatura

Em caso de divergência:

    STATUS = DIVERGENTE

ou estado equivalente já existente.

A divergência deve ser apresentada para revisão.

Não usar IA para inventar uma correção silenciosa.

---

## 17. Idempotência

Reprocessar o mesmo PDF não pode duplicar:

- cartão;
- conta;
- fatura;
- compras;
- lançamentos;
- vínculos;
- eventos de negócio.

Usar hash do documento e/ou identificadores estáveis.

Aplicar o mesmo princípio ao pagamento identificado via OFX.

---

## 18. Rastreabilidade

Preservar o caminho:

    PDF
     |
     +-- SHA-256
     |
     v
    Documento
     |
     v
    FaturaCartao
     |
     v
    CompraCartao
     |
     v
    Lancamento
     |
     v
    Split
     |
     v
    ContaCartao
     |
     v
    GnuCash

Também deve ser possível fazer o caminho inverso:

    Lancamento
     |
     v
    Fatura de origem
     |
     v
    PDF original

Nenhum dado de origem relevante deve ser descartado.

---

## 19. Auditoria

Reutilizar a infraestrutura de auditoria existente.

Se forem necessários novos eventos, avaliar primeiro o catálogo atual.

Possíveis eventos conceituais:

    FATURA_CARTAO_DETECTADA
    CARTAO_CRIADO
    FATURA_CARTAO_EXTRAIDA
    FATURA_CARTAO_VALIDADA
    FATURA_CARTAO_DIVERGENTE
    FATURA_CARTAO_CONTABILIZADA
    PAGAMENTO_CARTAO_IDENTIFICADO
    FATURA_CARTAO_PAGA

Não criar eventos duplicados semanticamente.

---

## 20. Integração com OFX/conciliação

Reutilizar o mecanismo existente de:

- `TransacaoBancaria`;
- FITID;
- conciliação;
- idempotência;
- regras de correspondência.

Quando o extrato indicar o pagamento da fatura, o objetivo é:

    D — Conta do Cartão
    C — Conta Bancária

Não criar uma despesa adicional.

Se o pagamento não puder ser identificado com confiança suficiente, encaminhar para conciliação/revisão.

---

## 21. GnuCash

Não criar integração paralela específica para cartão.

O cartão deve produzir lançamentos normais do Caderneta.

Fluxo:

    Documento
     -> Fatura
     -> Compra
     -> Lancamento
     -> Aprovação
     -> GnuCash

A conta do cartão deve possuir o vínculo/GUID necessário para exportação quando aplicável.

---

## 22. Testes obrigatórios

Criar/ampliar testes para:

### Detecção
- PDF normal;
- PDF cartão;
- PDF não cartão;
- PDF texto;
- PDF imagem.

### Extração
- emissor;
- final;
- período;
- vencimento;
- total;
- itens;
- parcelas;
- créditos;
- encargos.

### Contabilidade
- compra;
- parcela;
- juros;
- IOF;
- anuidade;
- estorno;
- crédito;
- múltiplos itens;
- equilíbrio de débitos/créditos.

### Conta
- criar cartão;
- reutilizar cartão;
- impedir duplicidade;
- criar conta;
- reutilizar conta;
- vincular cartão à conta.

### Idempotência
- mesmo PDF duas vezes;
- reprocessamento após restart;
- mesmo pagamento OFX duas vezes.

### Conciliação
- pagamento correto;
- pagamento divergente;
- pagamento duplicado;
- pagamento sem fatura;
- fatura sem pagamento.

### Auditoria
- origem preservada;
- hash preservado;
- eventos registrados;
- rastreabilidade PDF → lançamento.

### Regressão
Executar toda a suíte existente.

Nunca declarar uma alteração concluída apenas porque testes novos passaram.

---

## 23. Critérios de aceite

A funcionalidade de cartão somente será considerada pronta quando:

1. uma fatura PDF real for detectada;
2. o cartão for identificado;
3. a conta correspondente for localizada/criada sem duplicidade;
4. os itens forem extraídos;
5. o total for validado;
6. parcelas forem preservadas;
7. itens forem classificados;
8. baixa confiança for encaminhada para revisão;
9. partidas dobradas forem respeitadas;
10. compras forem lançadas contra o cartão;
11. pagamento baixar o passivo;
12. OFX puder ser conciliado;
13. reprocessamento não duplicar dados;
14. auditoria permitir rastreabilidade;
15. testes novos passarem;
16. regressão passar;
17. migrations funcionarem;
18. nenhuma regra existente for quebrada.

---

## 24. Processo obrigatório para novas implementações

Para qualquer alteração relevante relacionada a cartão ou a outra evolução arquitetural:

### Fase A — Descoberta

- inspecionar repositório;
- localizar componentes;
- ler ADRs;
- ler documentação relevante;
- localizar testes;
- localizar migrations.

### Fase B — Gap Analysis

Produzir:

| Requisito | Já existe | Parcial | Ausente | Componente atual | Alteração |
|---|---|---|---|---|---|

### Fase C — Arquitetura

Definir:

- domínio;
- persistência;
- interfaces;
- parser;
- pipeline;
- contabilização;
- conciliação;
- auditoria;
- CLI;
- migrations;
- testes.

### Fase D — ADR

Se houver nova decisão arquitetural, propor ADR ou alteração de ADR existente antes da implementação.

### Fase E — Plano

Para cada incremento informar:

- arquivos;
- objetivo;
- risco;
- testes;
- migration;
- impacto em ADR;
- critério de aceite.

### Fase F — Implementação

Implementar somente após autorização quando a tarefa exigir planejamento prévio.

---

## 25. Regra contra suposições

Não presumir:

- layout de banco;
- formato universal de fatura;
- que todo PDF possui texto;
- que toda compra é parcelada;
- que a soma dos itens sempre equivale diretamente ao total;
- que o pagamento possui texto padronizado no OFX;
- que existe determinada conta no plano de contas.

Se não houver evidência:

> Não há evidência suficiente nas fontes disponíveis.

Depois indicar como verificar.

---

## 26. Regra de evidência

Ao apresentar uma decisão técnica, distinguir:

1. o que está comprovado pelo código;
2. o que está definido pelos ADRs;
3. o que está definido pelos documentos de governança;
4. o que é inferência técnica;
5. o que é proposta nova.

Nunca apresentar uma proposta como se já fosse uma decisão do projeto.

---

## 27. Primeira entrega quando solicitado a "considerar" cartão

Quando receber uma solicitação para implementar suporte a cartão e ainda não houver autorização de implementação:

NÃO alterar código.

Entregar primeiro:

1. estado atual;
2. componentes já existentes;
3. lacunas;
4. componentes reutilizáveis;
5. novos componentes necessários;
6. impacto no banco;
7. impacto contábil;
8. impacto na conciliação;
9. impacto na auditoria;
10. impacto no GnuCash;
11. testes necessários;
12. ADRs afetados;
13. classificação de escopo;
14. plano de implementação;
15. riscos.

Depois aguardar autorização explícita.

---

## 28. Regra final

O objetivo não é simplesmente "fazer o Caderneta ler um PDF".

O objetivo é implementar um ciclo financeiro íntegro:

    FATURA PDF
        ↓
    IDENTIFICAÇÃO
        ↓
    CARTÃO
        ↓
    CONTA DE PASSIVO
        ↓
    ITENS
        ↓
    CLASSIFICAÇÃO
        ↓
    LANÇAMENTOS
        ↓
    APROVAÇÃO
        ↓
    GNUCASH
        ↓
    PAGAMENTO
        ↓
    OFX
        ↓
    CONCILIAÇÃO
        ↓
    BAIXA DO PASSIVO

Toda implementação deve preservar:

- partidas dobradas;
- rastreabilidade;
- idempotência;
- auditabilidade;
- revisão humana;
- separação de responsabilidades;
- compatibilidade com o domínio existente;
- compatibilidade com os ADRs;
- compatibilidade com os testes;
- governança de versão.

Quando houver conflito entre uma solução rápida e uma solução que preserve esses princípios, preservar os princípios e apresentar a decisão necessária antes de prosseguir.
