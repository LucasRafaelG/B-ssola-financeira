# Configuração completa: do zero aos seus dados

Atualizado em 2026-11-17.

Este guia leva você do repositório clonado até a Bússola lendo o seu banco, primeiro rodando à mão e depois, se quiser, todo dia sozinha pelo GitHub Actions. Nenhum passo exige guardar chave do Google em arquivo.

Tudo entre `<` e `>` é para trocar pelos seus valores. Guarde-os conforme for anotando; eles vão para o `.env` e para o GitHub, nunca para o código.

| valor | exemplo de formato | onde aparece |
|---|---|---|
| `<id-do-projeto>` | `bussola-123456` | Google Cloud |
| `<numero-do-projeto>` | `123456789012` | Google Cloud |
| `<e-mail-da-conta-de-servico>` | `bussola@<id-do-projeto>.iam.gserviceaccount.com` | Google Cloud |
| `<seu-e-mail-google>` | a conta Google com que você entra no gcloud | Google Cloud |
| `<id-da-planilha>` | o trecho do endereço da planilha entre `/d/` e `/edit` | Google Sheets |
| `<seu-usuario>/<seu-repositorio>` | o dono e o nome do seu repositório no GitHub | GitHub |

Antes de começar, siga a seção "Experimente sem nenhuma conta" do [README](../README.md) para instalar o projeto e ver o modo demo funcionando.

## 1. Pluggy: o acesso ao banco

A Pluggy é a intermediária do Open Finance. Você precisa de duas coisas dela: as credenciais de uma aplicação (`PLUGGY_CLIENT_ID` e `PLUGGY_CLIENT_SECRET`) e o id da conexão com o seu banco (`PLUGGY_ITEM_ID`).

1. Em [meu.pluggy.ai](https://meu.pluggy.ai), crie a sua conta e conecte o seu banco pelo Open Finance. É lá que você dá, e depois renova, o consentimento para ler as transações.
2. Em [dashboard.pluggy.ai](https://dashboard.pluggy.ai), crie uma conta de desenvolvedor e uma aplicação. Na página da aplicação ficam o **Client ID** e o **Client Secret**.
3. Ainda no painel, conecte a aplicação ao conector **Meu Pluggy**, entrando com a conta do passo 1. A conexão criada é um *item*, e o id dela é o `PLUGGY_ITEM_ID`.

O passo a passo atualizado, com telas, fica na [documentação da Pluggy](https://docs.pluggy.ai), na parte sobre o Meu Pluggy. Se o painel mudar, vale o que estiver lá.

A Bússola só lê. Nenhuma chamada do código movimenta dinheiro.

## 2. Google Sheets: a planilha

1. Crie uma planilha nova no Google Sheets.
2. Crie estas quatro abas, com os nomes exatos e os cabeçalhos na linha 1, um por coluna, nesta ordem:

   | aba | cabeçalho |
   |---|---|
   | `transacoes` | `id`, `data`, `descricao`, `valor`, `tipo`, `conta`, `categoria`, `prioridade`, `categorizado_por`, `parcela`, `total_parcelas`, `importado_em` |
   | `regras` | `palavra_chave`, `categoria`, `prioridade` |
   | `contas_fixas` | `nome`, `valor_estimado`, `dia_vencimento`, `categoria`, `prioridade`, `parcelas_restantes` e, opcional, `referencia` |
   | `metas` | `meta`, `valor_alvo`, `prazo`, `observacao` |

3. Copie o id da planilha do endereço: `https://docs.google.com/spreadsheets/d/<id-da-planilha>/edit`.

As abas `resumo_mensal`, `projecao` e `config` o código cria sozinho na primeira execução.

As regras podem começar vazias e ser criadas depois pelo aplicativo. Em `metas`, uma linha como `Guardar no fim do mês | 300 | | ` já liga a comparação com a meta.

## 3. Google Cloud: a conta de serviço

A planilha é aberta por uma conta de serviço, uma identidade do Google só para o robô. Você não baixa chave nenhuma dela: no computador, o seu login a "empresta" (impersonação); no GitHub Actions, o GitHub prova quem é com um token próprio.

1. Instale o [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) e entre com a sua conta:

   ```bash
   gcloud auth login
   ```

2. Crie um projeto (ou use um que já tenha) e deixe-o como padrão:

   ```bash
   gcloud projects create <id-do-projeto>
   gcloud config set project <id-do-projeto>
   ```

3. Ative as APIs usadas: Sheets para a planilha, IAM Credentials para a impersonação e STS para o login do GitHub Actions.

   ```bash
   gcloud services enable sheets.googleapis.com iamcredentials.googleapis.com sts.googleapis.com
   ```

4. Crie a conta de serviço:

   ```bash
   gcloud iam service-accounts create bussola --display-name="Bussola"
   ```

   O e-mail dela é `bussola@<id-do-projeto>.iam.gserviceaccount.com`.

5. Permita que **você** use a conta de serviço no computador. Sem este passo, a impersonação falha com erro de permissão.

   ```bash
   gcloud iam service-accounts add-iam-policy-binding <e-mail-da-conta-de-servico> \
     --member="user:<seu-e-mail-google>" \
     --role="roles/iam.serviceAccountTokenCreator"
   ```

6. **Compartilhe a planilha com a conta de serviço.** No Google Sheets, botão "Compartilhar", cole o `<e-mail-da-conta-de-servico>` e dê acesso de **Editor**. Esquecer este passo é a causa mais comum do erro "Planilha não encontrada ou sem permissão".

No Windows (PowerShell), troque o `\` do fim das linhas por uma crase `` ` ``, ou escreva o comando numa linha só.

## 4. Rodar no computador

1. Copie `.env.example` para `.env` e preencha:

   ```
   PLUGGY_CLIENT_ID=<client id da Pluggy>
   PLUGGY_CLIENT_SECRET=<client secret da Pluggy>
   PLUGGY_ITEM_ID=<id do item>
   SHEET_ID=<id-da-planilha>
   ```

   Deixe `DATA_MODE` vazio para usar os dados reais. `DIAS_HISTORICO` controla quantos dias são buscados na primeira vez (em branco, 90).

2. Faça o login do Google que o código usa, emprestando a conta de serviço:

   ```bash
   gcloud auth application-default login --impersonate-service-account=<e-mail-da-conta-de-servico>
   ```

3. Rode a primeira atualização:

   ```bash
   python -m bussola.main
   ```

   O log mostra só contagens, como "14 transações novas". Abra a planilha: a aba `transacoes` deve estar preenchida e as abas `resumo_mensal` e `projecao` criadas.

4. Abra o aplicativo:

   ```bash
   streamlit run app/Bussola.py
   ```

   No Windows, dá para abrir com dois cliques em `abrir_bussola.bat`.

### O uso manual do dia a dia

| quero | onde |
|---|---|
| buscar transações novas agora | botão "Atualizar agora", na barra lateral do app, ou `python -m bussola.main` |
| trazer mais histórico | `python -m bussola.main --dias 180` (de 1 a 365) |
| registrar um gasto em dinheiro ou outra entrada que não passa pelo banco | tela **Lançar** |
| criar, editar ou apagar uma regra de categoria | tela **Regras** |
| corrigir a categoria de uma transação só | tela **Regras**, parte de correção. Essa correção nunca é sobrescrita |
| ver quais descrições ainda não têm regra | tela **Regras**, ou `python -m bussola.sugestoes` |
| cadastrar contas fixas, parcelas e a meta | direto nas abas `contas_fixas` e `metas` da planilha |

Não lance à mão algo que também passa pelo banco: a transação contaria duas vezes.

## 5. Atualização automática todo dia (opcional)

O workflow `.github/workflows/atualizar.yml` roda todo dia às 07:00 (horário de Brasília) e faz o mesmo que `python -m bussola.main`. Ele entra no Google por Workload Identity Federation: o Google confia em tokens emitidos pelo GitHub, mas só para o seu repositório.

Use um repositório **privado** para isso. O código não grava dados no repositório, mas um repositório privado não mostra para ninguém o histórico de execuções.

### 5.1. No Google Cloud

1. Descubra o número do projeto (diferente do id):

   ```bash
   gcloud projects describe <id-do-projeto> --format="value(projectNumber)"
   ```

2. Crie o pool de identidades:

   ```bash
   gcloud iam workload-identity-pools create github \
     --location="global" \
     --display-name="GitHub Actions"
   ```

3. Crie o provedor OIDC do GitHub. A `attribute-condition` é o que restringe o acesso ao seu repositório; sem ela, qualquer repositório do GitHub poderia tentar entrar.

   ```bash
   gcloud iam workload-identity-pools providers create-oidc bussola \
     --location="global" \
     --workload-identity-pool="github" \
     --display-name="Bussola" \
     --issuer-uri="https://token.actions.githubusercontent.com" \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
     --attribute-condition="assertion.repository=='<seu-usuario>/<seu-repositorio>'"
   ```

4. Permita que o seu repositório use a conta de serviço:

   ```bash
   gcloud iam service-accounts add-iam-policy-binding <e-mail-da-conta-de-servico> \
     --role="roles/iam.workloadIdentityUser" \
     --member="principalSet://iam.googleapis.com/projects/<numero-do-projeto>/locations/global/workloadIdentityPools/github/attribute.repository/<seu-usuario>/<seu-repositorio>"
   ```

5. O nome completo do provedor, usado no próximo passo, é:

   ```
   projects/<numero-do-projeto>/locations/global/workloadIdentityPools/github/providers/bussola
   ```

### 5.2. No GitHub

No repositório, em **Settings > Secrets and variables > Actions**, cadastre:

| tipo | nome | valor |
|---|---|---|
| Secret | `PLUGGY_CLIENT_ID` | o mesmo do `.env` |
| Secret | `PLUGGY_CLIENT_SECRET` | o mesmo do `.env` |
| Secret | `PLUGGY_ITEM_ID` | o mesmo do `.env` |
| Secret | `SHEET_ID` | o mesmo do `.env` |
| Variable | `GCP_PROJECT_ID` | `<id-do-projeto>` |
| Variable | `GCP_WORKLOAD_IDENTITY_PROVIDER` | o nome completo do passo 5.1.5 |
| Variable | `GCP_SERVICE_ACCOUNT` | `<e-mail-da-conta-de-servico>` |

Com o [GitHub CLI](https://cli.github.com), dá para fazer o mesmo pelo terminal, dentro da pasta do repositório. Cada `gh secret set` pede o valor sem mostrá-lo na tela:

```bash
gh secret set PLUGGY_CLIENT_ID
gh secret set PLUGGY_CLIENT_SECRET
gh secret set PLUGGY_ITEM_ID
gh secret set SHEET_ID
gh variable set GCP_PROJECT_ID --body "<id-do-projeto>"
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --body "projects/<numero-do-projeto>/locations/global/workloadIdentityPools/github/providers/bussola"
gh variable set GCP_SERVICE_ACCOUNT --body "<e-mail-da-conta-de-servico>"
```

Enquanto a Variable `GCP_SERVICE_ACCOUNT` não existir, o workflow fica parado e não gasta nada.

### 5.3. Testar e ligar

1. Na aba **Actions** do repositório, abra "Atualizar planilha" e use **Run workflow**. Essa execução manual roda sempre, mesmo com o interruptor desligado. No campo de dias, dá para pedir mais histórico.
2. Se ela terminar verde e a planilha tiver mudado, a execução diária está pronta.
3. O interruptor "atualização automática", na barra lateral do app, decide se a execução agendada roda. Sem a aba `config`, vale ligado. Desligado, o robô termina antes de abrir a conexão com o banco.

Duas regras do GitHub que podem parar o agendamento:

- Num **fork**, os workflows agendados começam desligados. Ative-os na aba Actions.
- Num repositório **público** sem nenhuma atividade por 60 dias, o GitHub desliga os agendamentos e avisa por e-mail. Basta reativar na aba Actions.

## 6. Manutenção

- **Consentimento do Open Finance.** Ele expira (o prazo é definido pelo banco). Faltando 30 dias ou menos, o log avisa. Quando expira, a execução termina com erro, o GitHub manda e-mail e a mensagem diz para renovar. Renove em [meu.pluggy.ai](https://meu.pluggy.ai); o `PLUGGY_ITEM_ID` continua o mesmo, salvo se você apagar a conexão e criar outra.
- **Conexão com problema.** Se o status da conexão não for saudável (por exemplo, erro de login no banco), a execução termina com erro dizendo o status. Reconecte o banco no Meu Pluggy.
- **Login do Google expirado no computador.** Se aparecer "Credencial do Google não encontrada ou recusada", rode de novo o `gcloud auth application-default login --impersonate-service-account=...` do passo 4.2.

## Problemas comuns

| mensagem | causa provável | o que fazer |
|---|---|---|
| Planilha não encontrada ou sem permissão | planilha não compartilhada com a conta de serviço, ou `SHEET_ID` errado | passo 3.6 e o id do passo 2.3 |
| Credencial do Google não encontrada ou recusada | sem o login do gcloud, ou sem `serviceAccountTokenCreator` | passos 3.5 e 4.2 |
| A aba "..." não existe na planilha | nome de aba diferente, com acento ou espaço | passo 2.2, nomes exatos |
| A Pluggy respondeu com erro 401 ou 403 | Client ID ou Secret errados | painel da Pluggy, passo 1.2 |
| Variáveis de ambiente faltando ou vazias: ... | variável vazia no `.env` ou nos Secrets | passo 4.1 ou 5.2 |
| No Actions: erro de permissão ao pegar o token do Google | `attribute-condition` ou `principalSet` com o nome do repositório errado | passos 5.1.3 e 5.1.4, dono e nome exatos, sem `.git` |
