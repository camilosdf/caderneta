-- =============================================================
-- Caderneta — Migration 001: Schema Inicial (Fase 1)
-- =============================================================

-- Extensões
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================
-- FORNECEDORES
-- =============================================================
CREATE TABLE fornecedores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome_canonico   TEXT NOT NULL UNIQUE,
    cnpj            VARCHAR(14),
    categoria       VARCHAR(50),
    conta_debito_padrao  TEXT,
    conta_credito_padrao TEXT,
    centro_custo    TEXT,
    embedding       vector(768),
    total_lancamentos INT DEFAULT 0,
    ultima_ocorrencia DATE,
    criado_em       TIMESTAMPTZ DEFAULT NOW(),
    atualizado_em   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE fornecedor_aliases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fornecedor_id   UUID NOT NULL REFERENCES fornecedores(id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,
    UNIQUE(alias)
);

-- =============================================================
-- PLANO DE CONTAS
-- =============================================================
CREATE TABLE plano_contas (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo                  VARCHAR(20) NOT NULL UNIQUE,
    nome                    TEXT NOT NULL,
    tipo                    VARCHAR(20) NOT NULL
                            CHECK (tipo IN ('ativo','passivo','receita','despesa','patrimonio')),
    natureza                VARCHAR(10) NOT NULL
                            CHECK (natureza IN ('devedora','credora')),
    guid_gnucash            VARCHAR(36),
    permite_lancamento      BOOLEAN DEFAULT TRUE,
    centro_custo_obrigatorio BOOLEAN DEFAULT FALSE,
    conta_pai_id            UUID REFERENCES plano_contas(id)
);

-- =============================================================
-- REGRAS DE CLASSIFICAÇÃO
-- =============================================================
CREATE TABLE regras_classificacao (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome            TEXT NOT NULL,
    condicao_json   JSONB NOT NULL,
    categoria       TEXT,
    conta_debito    TEXT NOT NULL,
    conta_credito   TEXT NOT NULL,
    centro_custo    TEXT,
    prioridade      INT DEFAULT 100,
    ativa           BOOLEAN DEFAULT TRUE,
    criada_por      TEXT,
    criada_em       TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- DOCUMENTOS
-- =============================================================
CREATE TABLE documentos (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hash_sha256         VARCHAR(64) UNIQUE NOT NULL,
    nome_arquivo        TEXT NOT NULL,
    tipo_documento      VARCHAR(50) NOT NULL,
    fonte_extracao      VARCHAR(20) NOT NULL,
    dados_json          JSONB NOT NULL,
    ocr_texto           TEXT,
    ocr_confidence      NUMERIC(4,3),
    data_processamento  TIMESTAMPTZ DEFAULT NOW(),
    status              VARCHAR(20) DEFAULT 'processado'
);

-- =============================================================
-- LANÇAMENTOS
-- =============================================================
CREATE TABLE lancamentos (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    documento_id            UUID REFERENCES documentos(id),
    fornecedor_id           UUID REFERENCES fornecedores(id),

    data_lancamento         DATE NOT NULL,
    data_vencimento         DATE,
    descricao               TEXT NOT NULL,
    historico_padronizado   TEXT,
    valor                   NUMERIC(15,2) NOT NULL,

    conta_debito            TEXT NOT NULL,
    conta_credito           TEXT NOT NULL,
    categoria               TEXT,
    centro_custo            TEXT,

    -- Parcelamento
    e_parcelado             BOOLEAN DEFAULT FALSE,
    parcela_atual           INT,
    total_parcelas          INT,
    lancamento_pai_id       UUID REFERENCES lancamentos(id),

    -- IA e regras
    confidence              NUMERIC(4,3),
    metodo_classificacao    VARCHAR(30),
    regra_aplicada_id       UUID REFERENCES regras_classificacao(id),
    pre_aprovado            BOOLEAN DEFAULT FALSE,

    -- Aprovação
    nivel_aprovacao         VARCHAR(20),
    status                  VARCHAR(20) DEFAULT 'pendente'
                            CHECK (status IN ('pendente','aprovado','rejeitado','exportado')),
    aprovado_por_1          TEXT,
    aprovado_em_1           TIMESTAMPTZ,
    aprovado_por_2          TEXT,
    aprovado_em_2           TIMESTAMPTZ,

    -- GnuCash (Fase 3)
    guid_gnucash            TEXT,
    enviado_gnucash_em      TIMESTAMPTZ,

    criado_em               TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================
-- PERÍODOS CONTÁBEIS
-- =============================================================
CREATE TABLE periodos_contabeis (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ano         INT NOT NULL,
    mes         INT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    status      VARCHAR(10) DEFAULT 'aberto' CHECK (status IN ('aberto','fechado')),
    fechado_por TEXT,
    fechado_em  TIMESTAMPTZ,
    UNIQUE(ano, mes)
);

-- =============================================================
-- AUDIT LOG (IMUTÁVEL — append-only)
-- =============================================================
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo            VARCHAR(50) NOT NULL,
    timestamp       TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    usuario         TEXT,
    lancamento_id   UUID,
    documento_id    UUID,
    documento_hash  VARCHAR(64),
    campo_alterado  TEXT,
    valor_anterior  TEXT,
    valor_novo      TEXT,
    payload_json    JSONB NOT NULL,
    versao_sistema  VARCHAR(20)
);

-- Impede qualquer UPDATE ou DELETE no audit_log
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;

-- =============================================================
-- ÍNDICES
-- =============================================================
CREATE INDEX idx_lancamentos_status       ON lancamentos(status);
CREATE INDEX idx_lancamentos_data         ON lancamentos(data_lancamento);
CREATE INDEX idx_lancamentos_documento    ON lancamentos(documento_id);
CREATE INDEX idx_lancamentos_fornecedor   ON lancamentos(fornecedor_id);
CREATE INDEX idx_documentos_hash          ON documentos(hash_sha256);
CREATE INDEX idx_audit_log_timestamp      ON audit_log(timestamp);
CREATE INDEX idx_audit_log_lancamento     ON audit_log(lancamento_id);
CREATE INDEX idx_fornecedor_aliases       ON fornecedor_aliases(alias);
