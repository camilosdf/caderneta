-- =============================================================
-- Caderneta — Migration 002: Dados Iniciais
-- Plano de contas básico e regras de classificação padrão
-- =============================================================

-- =============================================================
-- PLANO DE CONTAS BÁSICO
-- (Adaptar ao plano real da empresa antes de ir para produção)
-- =============================================================
INSERT INTO plano_contas (codigo, nome, tipo, natureza, permite_lancamento) VALUES
-- ATIVO
('1',         'Ativo',                        'ativo',    'devedora',  FALSE),
('1.1',       'Ativo Circulante',             'ativo',    'devedora',  FALSE),
('1.1.01',    'Caixa e Equivalentes',         'ativo',    'devedora',  FALSE),
('1.1.01.001','Caixa',                        'ativo',    'devedora',  TRUE),
('1.1.01.002','Banco Inter CC',               'ativo',    'devedora',  TRUE),
('1.1.01.003','Banco Itaú CC',                'ativo',    'devedora',  TRUE),
('1.1.01.004','Banco Nubank CC',              'ativo',    'devedora',  TRUE),
('1.1.02',    'Contas a Receber',             'ativo',    'devedora',  FALSE),
('1.1.02.001','Clientes',                     'ativo',    'devedora',  TRUE),

-- PASSIVO
('2',         'Passivo',                      'passivo',  'credora',   FALSE),
('2.1',       'Passivo Circulante',           'passivo',  'credora',   FALSE),
('2.1.01',    'Contas a Pagar',               'passivo',  'credora',   FALSE),
('2.1.01.001','Fornecedores a Pagar',         'passivo',  'credora',   TRUE),
('2.1.02',    'Cartões de Crédito',           'passivo',  'credora',   FALSE),
('2.1.02.001','Cartão de Crédito Nubank',     'passivo',  'credora',   TRUE),
('2.1.02.002','Cartão de Crédito Inter',      'passivo',  'credora',   TRUE),

-- RECEITAS
('3',         'Receitas',                     'receita',  'credora',   FALSE),
('3.1',       'Receitas Operacionais',        'receita',  'credora',   FALSE),
('3.1.01.001','Receita de Serviços',          'receita',  'credora',   TRUE),
('3.1.01.002','Receita de Vendas',            'receita',  'credora',   TRUE),
('3.2',       'Outras Receitas',              'receita',  'credora',   FALSE),
('3.2.01.001','Receitas Diversas',            'receita',  'credora',   TRUE),

-- DESPESAS
('4',         'Despesas',                     'despesa',  'devedora',  FALSE),
('4.1',       'Despesas Operacionais',        'despesa',  'devedora',  FALSE),
('4.1.01.001','Alimentação',                  'despesa',  'devedora',  TRUE),
('4.1.01.002','Transporte',                   'despesa',  'devedora',  TRUE),
('4.1.01.003','Combustível',                  'despesa',  'devedora',  TRUE),
('4.1.01.004','Saúde',                        'despesa',  'devedora',  TRUE),
('4.1.01.005','Educação',                     'despesa',  'devedora',  TRUE),
('4.1.01.006','Serviços de Software / SaaS',  'despesa',  'devedora',  TRUE),
('4.1.01.007','Material de Escritório',       'despesa',  'devedora',  TRUE),
('4.1.01.008','Utilidades (Água/Luz/Tel)',     'despesa',  'devedora',  TRUE),
('4.1.01.009','Aluguel',                      'despesa',  'devedora',  TRUE),
('4.1.01.010','Despesas Bancárias',           'despesa',  'devedora',  TRUE),
('4.1.01.099','Outras Despesas',              'despesa',  'devedora',  TRUE);

-- =============================================================
-- REGRAS DE CLASSIFICAÇÃO PADRÃO
-- Prioridade: menor número = maior prioridade
-- =============================================================
INSERT INTO regras_classificacao (nome, condicao_json, categoria, conta_debito, conta_credito, prioridade, criada_por) VALUES

-- Prioridade máxima: tipo de lançamento bancário
('PIX recebido',
 '{"descricao_contains_any": ["PIX RECEBIDO", "RECEBIMENTO PIX", "TED RECEBIDA", "DOC RECEBIDO"]}',
 'Receitas Diversas', '1.1.01.002', '3.2.01.001', 1, 'sistema'),

('Tarifa bancária',
 '{"descricao_contains_any": ["TARIFA", "TAR ", "MANUT CONTA", "PACOTE SERVICOS"]}',
 'Despesas Bancárias', '4.1.01.010', '1.1.01.002', 2, 'sistema'),

('IOF',
 '{"descricao_contains_any": ["IOF", "I.O.F"]}',
 'Despesas Bancárias', '4.1.01.010', '1.1.01.002', 2, 'sistema'),

-- Combustível
('Posto de combustível',
 '{"descricao_contains_any": ["POSTO", "PETROBRAS", "SHELL", "IPIRANGA", "BR DIST", "COMBUSTIVEL", "GASOLINA", "ETANOL"]}',
 'Combustível', '4.1.01.003', '1.1.01.002', 10, 'sistema'),

-- Saúde
('Farmácia / Drogaria',
 '{"descricao_contains_any": ["DROGASIL", "DROGA RAIA", "ULTRAFARMA", "PACHECO", "DROGARIA", "FARMACIA", "FARMA"]}',
 'Saúde', '4.1.01.004', '1.1.01.002', 10, 'sistema'),

('Plano de saúde',
 '{"descricao_contains_any": ["UNIMED", "AMIL", "BRADESCO SAUDE", "SULAMERICA SAUDE", "HAPVIDA", "NOTREDAME"]}',
 'Saúde', '4.1.01.004', '1.1.01.002', 10, 'sistema'),

-- Alimentação
('Supermercado',
 '{"descricao_contains_any": ["SUPERMERCADO", "SUPERMERC", "MERCADO", "CARREFOUR", "EXTRA", "ATACADAO", "ASSAI", "WALMART", "BIG", "PREZUNIC", "GUANABARA", "BOMPRECO", "BOM PRECO"]}',
 'Alimentação', '4.1.01.001', '1.1.01.002', 10, 'sistema'),

('Restaurante / Delivery',
 '{"descricao_contains_any": ["IFOOD", "RAPPI", "UBER EATS", "RESTAURANTE", "LANCHONETE", "PADARIA", "PIZZARIA", "HAMBURGER"]}',
 'Alimentação', '4.1.01.001', '1.1.01.002', 10, 'sistema'),

-- Transporte
('Uber / 99 / Taxi',
 '{"descricao_contains_any": ["UBER", "99APP", "99 TAXI", "CABIFY", "TAXI"]}',
 'Transporte', '4.1.01.002', '1.1.01.002', 10, 'sistema'),

('Transporte público',
 '{"descricao_contains_any": ["BILHETE UNICO", "METRÔ", "METRO SP", "CARTAO BOM", "RIOCARD", "VEM"]}',
 'Transporte', '4.1.01.002', '1.1.01.002', 10, 'sistema'),

-- Software / SaaS
('Software e assinaturas digitais',
 '{"descricao_contains_any": ["AMAZON", "AWS", "GOOGLE", "MICROSOFT", "APPLE", "NETFLIX", "SPOTIFY", "GITHUB", "OPENAI", "ANTHROPIC", "DIGITALOCEAN", "VERCEL"]}',
 'Serviços de Software / SaaS', '4.1.01.006', '1.1.01.002', 10, 'sistema'),

-- Educação
('Educação',
 '{"descricao_contains_any": ["UDEMY", "COURSERA", "ALURA", "ROCKETSEAT", "ESCOLA", "FACULDADE", "UNIVERSIDADE", "MENSALIDADE"]}',
 'Educação', '4.1.01.005', '1.1.01.002', 10, 'sistema'),

-- Utilidades
('Energia elétrica',
 '{"descricao_contains_any": ["CPFL", "CEMIG", "LIGHT ", "ENEL", "ELEKTRO", "ENERGIA ELETRICA", "COPEL"]}',
 'Utilidades (Água/Luz/Tel)', '4.1.01.008', '1.1.01.002', 10, 'sistema'),

('Telefone / Internet',
 '{"descricao_contains_any": ["CLARO", "VIVO", "TIM ", "OI ", "NET ", "NEXTEL", "VIRTUA", "SKY "]}',
 'Utilidades (Água/Luz/Tel)', '4.1.01.008', '1.1.01.002', 10, 'sistema');


-- =============================================================
-- PERÍODO CONTÁBIL INICIAL
-- Abrir os 12 meses do ano corrente
-- =============================================================
INSERT INTO periodos_contabeis (ano, mes, status)
SELECT
    EXTRACT(YEAR FROM CURRENT_DATE)::INT,
    mes,
    'aberto'
FROM generate_series(1, 12) AS mes
ON CONFLICT (ano, mes) DO NOTHING;
