# J.A.R.V.I.S com Gemini

Este projeto cria um assistente para Windows capaz de:

- Entender pedidos em linguagem natural usando Gemini.
- Abrir aplicativos e jogos cadastrados em `config/apps.json`.
- Pesquisar direto no Chrome ou no navegador padrão.
- Controlar mídia do sistema, como pausar, tocar, avançar e voltar.
- Executar comandos por texto ou por voz com palavra de ativação.
- Lembrar o contexto recente da conversa para pedidos de continuação, como `toque essa música`.

## Setup rápido

1. Crie um ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Instale as dependências:

```powershell
pip install -r requirements.txt
```

3. Opcional, mas recomendado, instale o projeto localmente:

```powershell
pip install -e .
```

4. Edite `config/settings.json` e preencha sua chave Gemini.

5. Ajuste os caminhos dos seus apps e jogos em `config/apps.json`.

## Spotify (API)

Para a Friday conseguir **tocar** uma música específica no Spotify (com precisão), use a Spotify Web API.

Ela também pode tocar uma playlist sua do Spotify pelo nome, desde que a autenticação esteja configurada com os escopos de playlist.

1. Crie um app em https://developer.spotify.com/dashboard
2. Em *Redirect URIs*, adicione: `http://127.0.0.1:8765/callback`
3. No `config/settings.json`, adicione/preencha o bloco `spotify` (use como base o `config/settings.example.json`).

Observacoes importantes:

- O Spotify nao aceita mais `localhost` como redirect URI; use `127.0.0.1`.
- Em geral, controle de playback via Web API requer Spotify Premium.
- Para tocar playlists suas, mantenha os escopos `playlist-read-private` e `playlist-read-collaborative` no bloco `spotify.scopes`.
- Deixe o Spotify aberto em algum dispositivo (PC/celular) para existir um device ativo.
- Na primeira vez que você pedir para tocar uma música, vai abrir o navegador para autorizar e vai criar o token em `config/spotify_token.json`.
- Se você já autenticou antes de adicionar novos escopos, apague `config/spotify_token.json` e autorize de novo.

## Uso

Modo texto interativo:

```powershell
python friday.py
```

Por padrao, sem argumentos, ele abre a interface grafica e inicia o modo de voz.

Executar uma única ordem:

```powershell
python friday.py --once "pesquise sobre basquete no chrome"
```

Modo voz (com wake word):

```powershell
python friday.py --voice
```

Modo interface grafica (esfera de particulas) + voz:

```powershell
python friday.py --gui --voice
```

Wake word atual: `friday`.

Voce pode configurar UMA wake word em `config/settings.json` com `friday_name`, ou MULTIPLAS com `wake_words` (recomendado), por exemplo:

```json
{
	"wake_words": ["friday", "sexta feira", "sexta-feira"]
}
```

Descobrir o indice do microfone:

```powershell
python friday.py --list-mics
```

Depois coloque o numero em `config/settings.json` em `voice.microphone_device_index`.

## Exemplos

- `friday, abra o spotify`
- `sexta-feira, pesquise sobre basquete no chrome`
- `friday, pause a musica`
- `friday, pule para a proxima musica`
- `friday, toque a musica Monster do Skillet no spotify`
- `friday, toque minha playlist treino`
- `friday, toque a playlist favoritas`
- `sexta-feira, pesquise no YouTube a música Monster da banda Skillet`
- `friday, toque essa música`
- `sexta feira, abra o valorant`

## Memória de contexto

A Friday agora guarda um histórico curto da conversa e alguns itens lembrados, como a última música pesquisada. Isso permite continuar pedidos sem repetir tudo de novo, por exemplo:

- `sexta-feira, pesquise no YouTube a música Monster da banda Skillet`
- `friday, toque essa música`

Por padrão, a memória fica em `config/conversation_memory.json`, dura `180` minutos e mantém até `24` mensagens recentes. Se quiser ajustar isso, use o bloco `memory` no `config/settings.json`:

```json
{
	"memory": {
		"path": "config/conversation_memory.json",
		"ttl_minutes": 180,
		"max_messages": 24
	}
}
```

Se preferir usar o módulo Python após `pip install -e .`, os comandos equivalentes são `python -m friday.main`, `python -m friday.main --once ...` e `python -m friday.main --voice`.

## Observações

- O controle de mídia usa teclas multimídia do Windows.
- Para jogos, o ideal é cadastrar cada executável ou atalho no `config/apps.json`.
- A configuração principal agora fica em `config/settings.json`.
- O modo voz depende de um microfone funcional. Em alguns ambientes Windows, pode ser necessário instalar suporte adicional para captura de áudio.
- Se o modo voz acusar falta de PyAudio, instale com `pip install PyAudioWPatch`.

## Exemplo de settings.json

```json
{
	"gemini_api_key": "sua_chave_aqui",
	"gemini_model": "gemini-2.5-flash",
	"friday_name": "friday",
	"wake_words": ["friday", "sexta feira", "sexta-feira"],
	"friday_language": "pt-BR"
}
```

