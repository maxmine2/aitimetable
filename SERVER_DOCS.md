# Техническая документация: serve.py

## 1. Обзор

HTTP-сервер для локального запуска приложения Timetable Viewer. Построен на стандартном `http.server` из Python без внешних зависимостей.

Основные функции:
- Раздача статических файлов (HTML, JSON).
- API-эндпоинт для обновления расписания через `analysis.py`.
- Отслеживание прогресса обновления в реальном времени.
- Многоуровневая защита от сканеров, ботов и злоумышленников.

### Файлы
- [serve.py](serve.py) — Исходный код сервера.
- [analysis.py](analysis.py) — Скрипт обновления данных (вызывается сервером).
- [nsu_data.json](nsu_data.json) — Файл данных, генерируемый `analysis.py`.
- [timetable.html](timetable.html) — Клиентское приложение.

---

## 2. Запуск

```bash
python serve.py                        # localhost:8764
python serve.py -p 9000                # localhost:9000
python serve.py --host 0.0.0.0         # доступен из сети
python serve.py --host 0.0.0.0 -p 80   # из сети на порту 80
python serve.py --no-open              # не открывать браузер
```

Сервер стартует на `http://<host>:<port>` и автоматически открывает `timetable.html` в браузере (если не указан `--no-open`).

### Аргументы командной строки

| Аргумент | По умолчанию | Описание |
|----------|-------------|----------|
| `-p`, `--port` | `8764` | Порт HTTP-сервера |
| `--host` | `127.0.0.1` | Адрес привязки. `0.0.0.0` — все интерфейсы (доступ из сети) |
| `--no-open` | — | Не открывать браузер при старте |

### Конфигурация

| Константа | Значение | Описание |
|-----------|----------|----------|
| `DEFAULT_PORT` | `8764` | Порт по умолчанию |
| Привязка | `127.0.0.1` | По умолчанию только localhost. Можно изменить через `--host` |

---

## 3. Архитектура

```
┌─────────────┐    GET /timetable.html     ┌──────────────────┐
│   Браузер   │ ◄────────────────────────► │    serve.py      │
│             │    GET /nsu_data.json       │                  │
│             │                            │  ┌────────────┐  │
│             │    POST /api/update ──────► │  │ _guard()   │  │──► 403 / 429
│             │                            │  └─────┬──────┘  │
│             │    GET /api/update/status   │        │ OK      │
│             │ ◄──────────────────────────│  ┌─────▼──────┐  │
│             │    {current, total, phase}  │  │  Handler   │  │
│             │                            │  └─────┬──────┘  │
└─────────────┘                            │        │         │
                                           │  ┌─────▼──────┐  │
                                           │  │ analysis.py│  │ (subprocess)
                                           │  └────────────┘  │
                                           └──────────────────┘
```

### Потоковая модель

- **Основной поток**: HTTP-сервер (`serve_forever()`), обрабатывает запросы последовательно.
- **Фоновый поток (daemon)**: Запускается при `POST /api/update` для выполнения `analysis.py`. Обновляет глобальные переменные прогресса, доступные через `GET /api/update/status`.

---

## 4. Раздача статических файлов

### Белый список

Сервер раздаёт **только** файлы из явного белого списка `_ALLOWED_FILES`:

| Путь | Описание |
|------|----------|
| `/timetable.html` | Клиентское приложение |
| `/nsu_data.json` | База данных расписания |
| `/favicon.ico` | Иконка браузера |

Любой другой путь возвращает `403 Forbidden`.

Корневой путь `/` перенаправляется на `/timetable.html`.

### Листинг каталогов

Отключён полностью. Метод `list_directory()` переопределён и всегда возвращает `403`.

---

## 5. API-эндпоинты

### `POST /api/update`

Запускает обновление расписания (вызов `analysis.py` в фоновом потоке).

**Тело запроса**: не требуется.

**Ответ** (JSON):

| Поле | Тип | Описание |
|------|-----|----------|
| `status` | string | `"started"` / `"busy"` / `"cooldown"` |
| `message` | string | Описание результата |
| `retry_after` | number | Секунд до доступности (только для `cooldown`) |

**Статусы**:
- `started` — Обновление запущено. Клиент должен начать опрос `/api/update/status`.
- `busy` — Обновление уже выполняется. Повторный запуск невозможен.
- `cooldown` — Между предыдущим завершением и текущим запросом прошло менее 10 минут.

### `GET /api/update/status`

Возвращает текущее состояние обновления. Предназначен для периодического опроса (polling).

**Ответ** (JSON):

| Поле | Тип | Описание |
|------|-----|----------|
| `status` | string | `"idle"` / `"busy"` / `"ok"` / `"error"` / `"cooldown"` |
| `current` | number | Обработано групп (только при `busy`/`ok`/`error`) |
| `total` | number | Всего групп (только при `busy`/`ok`/`error`) |
| `phase` | string | Фаза: `"Запуск…"`, `"Факультеты…"`, `"Загрузка расписаний"`, `"Готово"`, `"Ошибка"` |
| `message` | string | Описание результата (при `ok`/`error`) |
| `output` | string | Последние строки вывода процесса (при `ok`/`error`) |
| `retry_after` | number | Секунд до доступности (при `cooldown`) |

**Статусы**:
- `idle` — Сервер готов к обновлению.
- `busy` — Обновление выполняется. Поля `current`/`total`/`phase` показывают прогресс.
- `ok` — Последнее обновление завершилось успешно.
- `error` — Последнее обновление завершилось с ошибкой.
- `cooldown` — Обновление недоступно, не истёк интервал ожидания.

---

## 6. Процесс обновления

### Жизненный цикл

```
POST /api/update
  │
  ├── Проверка: _updating == True? → {"status": "busy"}
  ├── Проверка: cooldown < 600s? → {"status": "cooldown"}
  │
  ├── _updating = True
  ├── Запуск daemon-потока (_run_update_bg)
  └── {"status": "started"}

Фоновый поток:
  │
  ├── subprocess.Popen("python -u analysis.py")
  │     stderr → stdout (merged), line-buffered
  │
  ├── Чтение stdout построчно:
  │     ├── "[N/M]" → _progress_current=N, _progress_total=M
  │     ├── "Fetching list of faculties" → phase="Факультеты…"
  │     └── "Discovered K unique groups" → _progress_total=K
  │
  ├── proc.wait(timeout=300)
  │
  ├── Успех: _result_box_store = {"status":"ok", ...}
  │   Ошибка: _result_box_store = {"status":"error", ...}
  │   Таймаут: proc.kill(), {"status":"error", "message":"timed out"}
  │
  └── _updating = False, _last_finish = time.time()
```

### Ограничения

| Параметр | Значение | Описание |
|----------|----------|----------|
| `_MIN_INTERVAL` | 600 с (10 мин) | Минимальный интервал между завершением обновления и следующим запуском |
| `timeout` | 300 с (5 мин) | Жёсткий лимит на выполнение `analysis.py` |
| Параллельность | 1 | Только одно обновление одновременно |

### Парсинг прогресса

`analysis.py` логирует строки вида:
```
2026-03-04 12:00:00 [INFO] [42/690] Group 24812.1 (ФИТ, Бакалавриат, year 2): 28 classes.
```

Сервер парсит регулярным выражением `\[(\d+)/(\d+)\]` и обновляет `_progress_current` / `_progress_total`. Клиент получает эти значения через `GET /api/update/status` и отображает как `"42/690"` на кнопке обновления.

### Синхронизация

Все переменные состояния (`_updating`, `_last_finish`, `_progress_*`, `_result_box_store`) защищены мьютексом `_lock` (`threading.Lock`). Фоновый поток пишет, HTTP-обработчик читает — гонок нет.

---

## 7. Защита от сканеров и ботов

Каждый входящий запрос проходит через метод `_guard()`, который последовательно применяет четыре проверки. При срабатывании любой из них запрос отклоняется, а остальная логика не исполняется.

### 7.1. Rate Limiting (ограничение частоты)

**Механизм**: Скользящее окно (`_RATE_WINDOW = 10 с`) с максимумом `_RATE_MAX_HITS = 60` запросов на IP.

**Структура данных**: `_rate_hits` — словарь `{IP: deque(timestamps)}`. При каждом запросе:
1. Удаляются записи старше 10 с из начала очереди.
2. Если длина очереди ≥ 60 — IP банится на 60 с (`_ban_until`).
3. Иначе — текущий timestamp добавляется в очередь.

**Бан**: Забаненный IP получает `429 Too Many Requests` на все последующие запросы до истечения срока.

**Защита**: от DDoS-атак, brute-force и агрессивных сканеров, генерирующих десятки запросов в секунду.

### 7.2. Блокировка User-Agent

**Механизм**: Регулярное выражение `_BLOCKED_UA_RE` проверяет заголовок `User-Agent`.

**Блокируемые инструменты**:

| Категория | Инструменты |
|-----------|-------------|
| Сканеры портов | nmap, masscan |
| Сканеры уязвимостей | nikto, nuclei, acunetix, nessus, openvas, skipfish, whatweb |
| SQL-инъекции | sqlmap |
| Перебор каталогов | dirbuster, gobuster, ffuf, wfuzz |
| Прокси-перехватчики | Burp Suite, ZAP (OWASP) |
| Brute-force | hydra, medusa |
| Программные клиенты | curl, wget, python-requests, Go-http-client, libwww-perl, httpclient |
| Краулеры | scrapy, zgrab, censys, shodan |

**Реакция**: IP немедленно банится на 300 с (5 мин). Ответ: `403 Forbidden`.

### 7.3. Блокировка подозрительных URL-паттернов

**Механизм**: Регулярное выражение `_BLOCKED_PATH_RE` проверяет `self.path`.

**Категории блокируемых паттернов**:

| Категория | Примеры | Описание |
|-----------|---------|----------|
| Обход пути | `..`, `%2e%2e`, `%c0%af` | Path traversal для чтения файлов за пределами корня |
| Чувствительные файлы | `.env`, `.git`, `.htpasswd`, `.sql`, `.log`, `.config`, `.bak` | Конфигурации, бэкапы, логи |
| CMS/Admin панели | `/wp-admin`, `/phpmyadmin`, `/phpinfo`, `/admin` | Стандартные точки входа CMS |
| Фреймворки | `/actuator`, `/telescope`, `/_profiler`, `/swagger` | Debug/admin эндпоинты фреймворков |
| Файл-менеджеры | `/elfinder`, `/filemanager`, `/upload` | Веб-интерфейсы загрузки файлов |
| Выполнение кода | `/shell`, `/eval`, `/cmd`, `/exec` | Попытки RCE |
| Инфраструктура | `/jenkins`, `/jmx`, `/console`, `/solr`, `/struts` | Эксплуатация серверного ПО |
| Базы данных | `/mysql`, `/postgres`, `/sqlite`, `/db`, `/database` | Прямой доступ к БД |
| Скриптовые расширения | `.php`, `.asp`, `.jsp`, `.cgi`, `.pl`, `.py`, `.rb`, `.sh`, `.bat` | Попытки исполнения серверных скриптов |
| URL-кодирование | `%00`, `%2e`, `%5c`, `%c0`, `%c1`, `%25` | Null-байты, закодированные обходы |
| Инъекции | `<`, `>`, `"`, `'`, `;` | XSS / SQL-инъекции через URL |

**Реакция**: IP банится на 300 с (5 мин). Ответ: `403 Forbidden`.

### 7.4. Ограничение размера тела запроса

**Механизм**: Проверяется заголовок `Content-Length`. Если значение > 4096 байт — запрос отклоняется.

**Ответы**:
- `413 Payload Too Large` — тело слишком большое.
- `400 Bad Request` — `Content-Length` не является числом.

**Защита**: от попыток загрузки вредоносных файлов или переполнения буфера.

---

## 8. Дополнительные меры безопасности

### 8.1. Привязка сетевого интерфейса

```python
http.server.HTTPServer((args.host, args.port), Handler)
```

По умолчанию (`--host 127.0.0.1`) сервер принимает подключения только с localhost. Запросы с внешних IP отклоняются ОС на сетевом уровне.

При запуске с `--host 0.0.0.0` сервер слушает на всех интерфейсах и доступен из локальной сети. В этом случае защита обеспечивается остальными уровнями (rate limiting, блокировка UA/URL, белый список файлов).

### 8.2. Белый список файлов

Константа `_ALLOWED_FILES` содержит исчерпывающий список файлов, доступных по GET:

```python
_ALLOWED_FILES = frozenset({
    "/timetable.html",
    "/nsu_data.json",
    "/favicon.ico",
})
```

Все остальные пути (включая `serve.py`, `analysis.py`, `.git/`, `.env`, `__pycache__/` и любые другие файлы в каталоге) возвращают `403 Forbidden`. Запрос нормализуется — query-параметры и фрагменты отбрасываются перед проверкой.

### 8.3. Запрет HTTP-методов

Разрешены только `GET` и `POST`. Остальные методы (`PUT`, `DELETE`, `PATCH`, `OPTIONS`) явно переопределены и возвращают `405 Method Not Allowed`:

```python
def do_PUT(self):     self.send_error(405, "Method Not Allowed")
def do_DELETE(self):  self.send_error(405, "Method Not Allowed")
def do_PATCH(self):   self.send_error(405, "Method Not Allowed")
def do_OPTIONS(self): self.send_error(405, "Method Not Allowed")
```

### 8.4. Запрет листинга каталогов

```python
def list_directory(self, path):
    self.send_error(403)
    return None
```

Стандартный `SimpleHTTPRequestHandler` показывает содержимое каталога при обращении к `/`. Это переопределено — любой запрос каталога даёт `403`.

### 8.5. Заголовки безопасности

Метод `_add_security_headers()` добавляет защитные заголовки к **каждому** ответу (вызывается и из `_json_response()`, и через переопределённый `end_headers()`):

| Заголовок | Значение | Назначение |
|-----------|----------|------------|
| `X-Content-Type-Options` | `nosniff` | Запрещает браузеру угадывать MIME-тип (защита от MIME-sniffing атак) |
| `X-Frame-Options` | `DENY` | Запрещает встраивание страницы в `<iframe>` (защита от clickjacking) |
| `X-XSS-Protection` | `1; mode=block` | Активирует встроенный XSS-фильтр браузера |
| `Referrer-Policy` | `no-referrer` | Запрещает отправку заголовка Referer (утечка URL) |
| `Content-Security-Policy` | `default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'` | Разрешает загрузку ресурсов только с того же origin. Inline-скрипты и стили разрешены (необходимо для single-file HTML) |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Отключает доступ к камере, микрофону и геолокации |

---

## 9. Порядок обработки запроса

```
Запрос
  │
  ├─ 1. _guard():
  │     ├── _check_rate(ip) → 429
  │     ├── _BLOCKED_UA_RE.search(ua) → ban + 403
  │     ├── _BLOCKED_PATH_RE.search(path) → ban + 403
  │     └── Content-Length > 4096 → 413
  │
  ├─ 2. Маршрутизация:
  │     ├── POST /api/update → _start_update() → JSON
  │     ├── GET /api/update/status → _status() → JSON
  │     ├── GET /whitelist → super().do_GET()
  │     ├── GET /other → 403
  │     ├── PUT/DELETE/PATCH/OPTIONS → 405
  │     └── POST /other → 404
  │
  └─ 3. end_headers() → _add_security_headers()
        → X-Content-Type-Options, X-Frame-Options, CSP, ...
```

---

## 10. Глобальное состояние

### Переменные

| Переменная | Тип | Защита | Описание |
|------------|-----|--------|----------|
| `_updating` | `bool` | `_lock` | Выполняется ли обновление |
| `_last_finish` | `float` | `_lock` | Epoch завершения последнего обновления |
| `_progress_current` | `int` | `_lock` | Количество обработанных групп |
| `_progress_total` | `int` | `_lock` | Общее количество групп |
| `_progress_phase` | `str` | `_lock` | Текущая фаза обновления |
| `_result_box_store` | `dict` | `_lock` | Результат завершённого обновления |
| `_rate_hits` | `dict[str, deque]` | `_rate_lock` | Временные метки запросов по IP |
| `_ban_until` | `dict[str, float]` | `_rate_lock` | Время окончания бана по IP |

### Мьютексы

| Мьютекс | Защищает |
|---------|----------|
| `_lock` | Все переменные обновления (`_updating`, `_last_finish`, `_progress_*`, `_result_box_store`) |
| `_rate_lock` | Rate-limiter (`_rate_hits`, `_ban_until`) |

---

## 11. Константы

| Константа | Значение | Описание |
|-----------|----------|----------|
| `DEFAULT_PORT` | `8764` | HTTP-порт по умолчанию |
| `_MIN_INTERVAL` | `600` (10 мин) | Cooldown между обновлениями |
| `_RATE_WINDOW` | `10` (с) | Окно rate-limiter |
| `_RATE_MAX_HITS` | `60` | Макс. запросов за окно на IP |
| Ban за rate-limit | `60` с | Длительность бана при превышении лимита |
| Ban за scanner/URL | `300` с (5 мин) | Длительность бана при обнаружении сканера |
| Subprocess timeout | `300` с (5 мин) | Таймаут выполнения `analysis.py` |
| Max Content-Length | `4096` байт | Максимальный размер тела POST-запроса |

---

## 12. Логирование

Используется стандартный `log_message()` из `http.server`. Запросы к API-путям (`/api/...`) подавлены чтобы не засорять журнал при polling. Все остальные запросы (статические файлы, ошибки) логируются в stderr в стандартном формате:

```
127.0.0.1 - - [04/Mar/2026 12:00:00] "GET /timetable.html HTTP/1.1" 200 -
```

---

## 13. Граф вызовов

### Запуск
```
main
  └─ HTTPServer((args.host, args.port), Handler)
     ├─ webbrowser.open(url)  # unless --no-open
     └─ serve_forever()
```

### Обработка запроса
```
do_GET / do_POST
  └─ _guard()
     ├─ _check_rate(ip)
     ├─ _BLOCKED_UA_RE.search(ua)
     ├─ _BLOCKED_PATH_RE.search(path)
     └─ Content-Length check
  └─ маршрутизация
     ├─ _start_update() → Thread(_run_update_bg)
     ├─ _status()
     └─ super().do_GET()
  └─ end_headers() → _add_security_headers()
```

### Обновление
```
_start_update()
  ├─ проверки (_updating, cooldown)
  └─ Thread(target=_run_update_bg, daemon=True).start()

_run_update_bg()
  ├─ Popen([python, -u, analysis.py])
  ├─ for line in proc.stdout:
  │   └─ _PROGRESS_RE.search(line) → _progress_current/_total
  ├─ proc.wait(timeout=300)
  └─ _result_box_store["result"] = {...}
```
