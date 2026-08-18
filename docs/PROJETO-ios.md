# PROJETO-ios: Especificação Técnica e Plano de Execução do App iOS Baixável (PWA)

## Visão Geral
Este documento estabelece o plano de implementação para disponibilizar o **ia-chat-app** como um aplicativo baixável e instalável em dispositivos iOS (iPhone/iPad) com suporte a operação offline quando o Mac estiver desligado.

---

## 1. Diagnóstico do Repositório

### 1.1 O que já existe:
- [ui/manifest.webmanifest](file:///Users/bauervieiracesarfilhovieira/Projetos/ia-chat-app/ui/manifest.webmanifest): Configurado com `display: standalone`, temas de cor e manifesto PWA.
- [ui/index.html](file:///Users/bauervieiracesarfilhovieira/Projetos/ia-chat-app/ui/index.html#L18-L22): Metas de iOS Safari ativas (`apple-mobile-web-app-capable="yes"`, `apple-touch-icon`, status bar `black-translucent`).
- Ícones em formato PNG: `icone-192.png`, `icone-512.png`, `apple-touch-icon.png`.

### 1.2 O que está faltando ou quebrado:
1. **Bloqueio HTTP 401 no Manifest**:
   - O servidor [ui/servir.py](file:///Users/bauervieiracesarfilhovieira/Projetos/ia-chat-app/ui/servir.py#L550-L560) exige token de autenticação em **todas** as rotas GET.
   - O iOS Safari faz requisições uncredentialed para `/manifest.webmanifest` ao clicar em "Adicionar à Tela de Início", recebendo **401 Unauthorized**.
2. **Ausência de Service Worker**:
   - Zero código de Service Worker (`sw.js`) ou registro (`navigator.serviceWorker.register`) no repositório.
3. **Ausência de Cache Local de Histórico**:
   - O [ui/sala.js](file:///Users/bauervieiracesarfilhovieira/Projetos/ia-chat-app/ui/sala.js#L1144) não armazena o histórico em IndexedDB.

---

## 2. Decisão Arquitetural: PWA Instalável vs. App Nativo

- **Rota Escolhida**: **PWA Instalável (Adicionar à Tela de Início)**.
- **Custo Financeiro**: **$0.00**.
- **Autorizações Externas**: Nenhuma (não exige conta Apple Developer de $99/ano).
- **Inviabilidade do App Nativo/TestFlight**: Exige assinatura anual de conta Apple Developer ($99/ano), aceite de termos e certificados de código no Mac.

---

## 3. Desenho da Arquitetura Offline

### 3.1 Escopo do Cache no iPhone
- **App Shell (CacheStorage em `sw.js`)**:
  - `index.html`, `estilo.css`, `sala.js`, `manifest.webmanifest`, ícones e favicon.
- **Dados do Usuário e Enxame (IndexedDB `iachat-db`)**:
  - `mensagens`: Histórico das conversas dos últimos 2 dias.
  - `iaswarm_runs`: Histórico de execuções do IASWARM dos últimos 2 dias.
  - `telemetria`: Contexto e reatores do groupchat.

### 3.2 Teto e Limpeza Automática (Eviction FIFO)
- **Janela de Retenção**: 48 horas (2 dias) de histórico.
- **Teto de Tamanho**: **15 MB** max.
- **Despejo (FIFO)**:
  1. Purga logs brutos de reatores > 24h.
  2. Purga runs do IASWARM > 48h.
  3. Purga mensagens da sala > 48h.
  4. Preserva preferências do usuário (`ia-chat-tema`, tokens, sino).

### 3.3 Degradação Elegante (Mac Desligado)
- **Status da Conexão (`#elo`)**: Transiciona para `data-estado="offline"` com o texto `"● offline · Mac desligado"`.
- **Banner Informativo**: Exibe aviso de que a aplicação está operando sobre o cache dos últimos 2 dias.
- **Compositor (`#compositor`)**: Fica desabilitado com feedback visual claro.
- **Navegação**: Fio, Decisões, Dia, Arquivos, Mapa e IASWARM mantêm busca e navegação ativas no IndexedDB local.

---

## 4. Plano de Implementação em Ordem de Prioridade

1. **Passo 1 — Liberar Ativos do PWA no Backend**:
   - Alterar `servir.py` para permitir GET não autenticado em `/manifest.webmanifest`, `/sw.js`, `/favicon.ico` e ícones PNG.
2. **Passo 2 — Criar Service Worker (`ui/sw.js`)**:
   - Implementar CacheFirst para ativos estáticos da UI.
3. **Passo 3 — Registrar Service Worker em `ui/sala.js`**:
   - Adicionar `navigator.serviceWorker.register('/sw.js')`.
4. **Passo 4 — Persistência no IndexedDB em `ui/sala.js`**:
   - Implementar classe `OfflineStore` para salvar mensagens do SSE/REST e runs do IASWARM.
5. **Passo 5 — Degradação e Fallback Offline na UI**:
   - Tratar falhas de rede no evento `onerror` do EventSource / fetch para alternar para modo offline no IndexedDB.
6. **Passo 6 — Atualizar Script de Montagem (`montar.sh`)**:
   - Incluir `sw.js` no bundle macOS.

---

## 5. Critérios Verificáveis de Sucesso

1. `curl -i http://127.0.0.1:8801/manifest.webmanifest` deve retornar `HTTP 200 OK` sem parâmetro de token `?t=`.
2. Abertura do app em modo avião (offline) exibe o aplicativo instantaneamente com o badge `"● offline · Mac desligado"`.
3. Histórico das conversas dos últimos 2 dias é totalmente pesquisável offline.
