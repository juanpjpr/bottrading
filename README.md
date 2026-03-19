# Bot de trading por noticias

Este proyecto es una base para un bot que:

- lee noticias del dia
- calcula un scoring multifactor de sentimiento, impacto, geopolitica, recencia, precio, volumen, volatilidad, consenso y smart money
- genera senales por activo con breakdown cuantitativo
- ejecuta operaciones en modo simulacion
- genera un dashboard visual estilo terminal de trading
- exporta un reporte de research para analizar el modelo

## Aviso importante

No existe una forma seria de garantizar una ganancia fija por dia. Este bot esta preparado para investigar oportunidades y operar con reglas de riesgo, primero en `paper trading`.

## Estructura

- `main.py`: punto de entrada
- `bot_trading_news/config.py`: carga de configuracion
- `bot_trading_news/news.py`: lectura de noticias desde API o archivo
- `bot_trading_news/market.py`: factores de precio, volumen, volatilidad, regimen y validacion
- `bot_trading_news/smart_money.py`: factor institucional basado en carteras conocidas o 13F
- `bot_trading_news/strategy.py`: scoring y senales
- `bot_trading_news/research.py`: reporte cuantitativo de research
- `bot_trading_news/broker.py`: simulador de ordenes y posiciones
- `bot_trading_news/dashboard.py`: generador del dashboard HTML
- `sample_news.json`: noticias de ejemplo para pruebas
- `sample_market_data.json`: series de precio y volumen para pruebas
- `sample_smart_money.json`: conviccion institucional de ejemplo

## Configuracion

Crear un archivo `.env` opcional con:

```env
NEWS_API_KEY=tu_api_key
NEWS_API_URL=https://newsapi.org/v2/everything
SMART_MONEY_MODE=sample
# SMART_MONEY_MODE=sec
# SEC_USER_AGENT=tu_app contacto@tuemail.com
# FMP_API_KEY=tu_api_key_fmp
BOT_BALANCE=10000
BOT_RISK_PER_TRADE=0.01
BOT_MAX_DAILY_TRADES=3
BOT_MIN_SIGNAL_SCORE=2.5
BOT_WATCHLIST=AAPL,MSFT,NVDA,TSLA,SPY,BTC
```

## App Web

Levantar la app con FastAPI:

```bash
uvicorn bot_trading_news.service:app --reload
```

Despues abrir:

```text
http://127.0.0.1:8000
```

Endpoints utiles:

- `/`: dashboard web
- `/api/dashboard?horizon=short|medium|long`: payload JSON del dashboard
- `/api/signals?horizon=short|medium|long`: senales y research
- `/health`: estado del servicio
- `/health/stack`: salud global del stack y broker
- `/api/monitor`: resumen operativo del bot y servicios

## Microservicios

Primer microservicio disponible:

- `services/execution_service`: cuenta, posiciones, actividad y ejecucion
- `services/market_data_service`: snapshots y factores de precio, volumen, volatilidad y regimen
- `services/ai_filter_service`: filtro de noticias, relevancia, impacto y tradability
- `services/signal_engine`: genera señales y score final por activo
- `services/news_service`: ingesta, deduplicacion y cache de noticias

Levantar solo ese servicio:

```bash
python -m uvicorn services.execution_service.app:app --reload --port 8010
```

Levantar automaticamente todos los microservicios detectados en `services/`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-microservices.ps1
```

Si tambien queres abrir la web principal:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-microservices.ps1 -WithWeb
```

La web principal puede usar el microservicio de ejecucion si agregas en `.env`:

```env
EXECUTION_SERVICE_URL=http://127.0.0.1:8010
```

Y si queres usar todo el stack por microservicios:

```env
NEWS_SERVICE_URL=http://127.0.0.1:8050
AI_FILTER_SERVICE_URL=http://127.0.0.1:8030
MARKET_DATA_SERVICE_URL=http://127.0.0.1:8020
SIGNAL_ENGINE_URL=http://127.0.0.1:8040
EXECUTION_SERVICE_URL=http://127.0.0.1:8010
```

## Persistencia

La actividad del bot ahora se guarda en SQLite.

- base por defecto: `bot_activity.db`
- migracion automatica desde `bot_activity.json` si existe

Tambien podes cambiar rutas con:

```env
ACTIVITY_DB_PATH=./data/bot_activity.db
ACTIVITY_JSON_PATH=./bot_activity.json
```

## Docker

Construir y levantar todo el stack:

```bash
docker compose up --build
```

Levantar en segundo plano:

```bash
docker compose up -d --build
```

Ver logs:

```bash
docker compose logs -f
```

Bajar el stack:

```bash
docker compose down
```

La web queda en:

```text
http://127.0.0.1:8000
```

La pagina ahora soporta 3 modos de analisis:

- `short`: mas sensible a noticias recientes, precio y volumen
- `medium`: balanceado
- `long`: mas peso en regimen y validacion historica

Smart money:

- `SMART_MONEY_MODE=sample`: usa carteras institucionales de ejemplo
- `SMART_MONEY_MODE=sec`: usa SEC/EDGAR gratis para leer 13F de gestores conocidos
- `SMART_MONEY_MODE=fmp`: intenta usar datos institucionales via FMP si definis `FMP_API_KEY`

Importante para SEC:

- definir `SEC_USER_AGENT` con un contacto valido
- el modo `sec` es mejor para medio/largo plazo
- si SEC falla, el sistema vuelve a `sample`

## Uso

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Correr con noticias de ejemplo:

```bash
python main.py run --news-file sample_news.json
```

Usando tambien factores de mercado:

```bash
python main.py run --news-file sample_news.json --market-file sample_market_data.json
```

Buscar noticias del dia desde API:

```bash
python main.py run --fetch-news
```

Mostrar solo el analisis sin operar:

```bash
python main.py analyze --news-file sample_news.json
```

Generar reporte de research:

```bash
python main.py research --news-file sample_news.json
```

Generar el dashboard:

```bash
python main.py dashboard --news-file sample_news.json
```

Generar el dashboard con auto-refresh del navegador:

```bash
python main.py dashboard --news-file sample_news.json --auto-refresh 5
```

Modo vivo para regenerarlo automaticamente:

```bash
python main.py live --news-file sample_news.json --refresh-seconds 5
```

Guardar el dashboard en otra ruta:

```bash
python main.py dashboard --fetch-news --output dashboard.html
```

## Siguientes pasos recomendados

1. Probar varias semanas en simulacion.
2. Medir win rate, drawdown y profit factor.
3. Sumar datos de precio, volumen y volatilidad para mejorar la prediccion.
4. Incorporar features historicas y validacion out-of-sample.
5. Recien despues conectar un broker real como Alpaca o Binance.
