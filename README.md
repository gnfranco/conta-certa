# Cobrança IPCA + Taxa Legal

Aplicativo local em Python/Streamlit para controlar dívidas, pagamentos parciais e atualização por **IPCA + Taxa Legal**.

## O que ele faz

- Cadastra devedores.
- Cadastra dívidas com vencimento, tipo e valor.
- Registra pagamentos parciais.
- Atualiza taxas oficiais via API SGS/BCB:
  - IPCA mensal: série 433.
  - Taxa Legal mensal: série 29543.
- Calcula saldo atualizado até uma data-base.
- Aloca pagamentos gerais automaticamente pela dívida mais antiga.
- Exporta relatório em Excel e PDF.
- Mantém tudo em um banco SQLite local: `data/cobrancas.db`.

## Como instalar

### 1. Instale Python

Use Python 3.10 ou superior.

### 2. Crie uma pasta e descompacte o projeto

Exemplo:

```bash
mkdir cobranca_app
cd cobranca_app
```

Descompacte o ZIP dentro dessa pasta.

### 3. Crie ambiente virtual

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Instale dependências

```bash
pip install -r requirements.txt
```

### 5. Rode o app

```bash
streamlit run app.py
```

O navegador vai abrir automaticamente.

## Como usar no dia a dia

1. Aba **Taxas**: clique em **Atualizar via BCB**.
2. Aba **Devedores**: cadastre a pessoa.
3. Aba **Dívidas**: lance cada valor devido.
4. Aba **Pagamentos**: registre pagamentos parciais.
5. Aba **Dashboard**: veja saldo atualizado até a data-base.
6. Aba **Relatórios**: gere Excel/PDF para cobrança.

## Observações importantes

- O app não substitui orientação jurídica.
- Para dívidas antigas, confira se o critério de correção faz sentido no caso concreto.
- Se uma taxa oficial ainda não saiu, o app pode usar taxa provisória marcada como tal.
- Pagamentos sem dívida específica são alocados automaticamente da dívida vencida mais antiga para a mais nova.
