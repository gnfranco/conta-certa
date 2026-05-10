# Conta Certa

Aplicativo local em Python/Streamlit para controlar títulos a receber, recebimentos parciais, atualização monetária por **IPCA + Taxa Legal** e emissão de demonstrativos.

O Conta Certa nasceu para organizar valores devidos, acompanhar atrasos, registrar pagamentos/recebimentos e manter um histórico claro para cobrança administrativa, negociação ou conferência documental.

> Este projeto não substitui orientação jurídica, contábil ou financeira. Ele organiza cálculos e registros locais para apoio ao controle pessoal ou profissional.

---

## Estado atual do projeto

Esta versão representa a primeira etapa mais estruturada do Conta Certa:

- Interface reorganizada em módulos dentro de `ui/`.
- Aplicativo principal (`app.py`) simplificado como roteador da interface.
- Cadastro de devedores.
- Cadastro de títulos a receber.
- Registro de recebimentos.
- Baixa automática por título mais antigo.
- Baixa automática por grupo.
- Baixa direcionada para título específico.
- Correção por IPCA + Taxa Legal.
- Uso de índices oficiais ou provisórios.
- Exportação de demonstrativos em Excel e PDF.
- Banco local SQLite.
- Referências públicas profissionais para títulos, recebimentos, lotes, baixas e movimentos.
- Camada monetária com armazenamento auxiliar em centavos.
- Base arquitetural inspirada em sistemas contábeis para evolução futura.

---

## Principais conceitos

### Devedor

Pessoa ou empresa que deve valores.

Exemplos:

- Cliente
- Empresa contratante
- Pessoa física
- Contraparte de acordo
- Responsável por reembolso

### Título

Valor que deveria ter sido recebido em determinada data.

Exemplos:

- Mensalidade
- Décimo terceiro
- Férias
- Reembolso
- Empréstimo
- Serviço prestado
- Acordo antigo

Cada título possui:

- Devedor
- Grupo
- Tipo
- Competência
- Descrição
- Valor original
- Data de vencimento
- Status administrativo
- Referência pública

### Recebimento

Valor recebido do devedor.

O recebimento pode ser aplicado de três formas:

1. **Automático**
   O sistema aplica o valor nos títulos vencidos mais antigos do devedor.

2. **Automático por grupo**
   O sistema aplica o valor nos títulos vencidos mais antigos dentro de um grupo específico.

3. **Título específico**
   O recebimento é aplicado diretamente no título escolhido.

### Grupo

Organização lógica dos títulos.

Exemplos:

- Geral
- Mensalidades
- Décimo terceiro
- Férias
- Reembolsos
- Empréstimos
- Acordo antigo
- Outros

O grupo ajuda a separar dívidas por origem, contrato, período ou contexto.

### Índices

O sistema usa índices mensais para atualizar valores vencidos:

- IPCA
- Taxa Legal

Quando o índice oficial ainda não está disponível, é possível usar valores provisórios configurados localmente.

---

## Referências públicas

O sistema usa referências públicas para evitar expor IDs internos do banco na interface.

Exemplos:

- `TIT-2026-000001` para títulos
- `REC-2026-000001` para recebimentos
- `LOT-2026-000001` para lotes de título
- `BXA-2026-000001` para baixas
- `MOV-2026-000001` para movimentos

Os IDs internos continuam existindo no SQLite, mas a interface prioriza referências legíveis e estáveis para o usuário.

---

## Estrutura do projeto

```text
conta-certa/
├── app.py
├── bcb.py
├── calculos.py
├── database.py
├── money.py
├── reports.py
├── requirements.txt
├── README.md
├── data/
│   └── .gitkeep
└── ui/
    ├── __init__.py
    ├── components.py
    ├── dashboard.py
    ├── demonstrativos.py
    ├── devedor_workspace.py
    ├── formatters.py
    ├── indices.py
    └── lancamentos.py
