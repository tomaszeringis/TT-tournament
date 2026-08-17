# Deepgram SDK 7.6.0 — API Shape Probe

**Purpose:** Document the exact API surface of `deepgram-sdk==7.6.0` before writing
production backend code. This probe gates implementation (see plan §2.1).

**Probe date:** 2026-08-05
**Python:** 3.13.9

---

## 1. Client constructors

### Sync client

```python
from deepgram import DeepgramClient

client = DeepgramClient(api_key="...")
# api_key is keyword-only (passed through to BaseClient).
# Positional api_key raises:
#   TypeError: BaseClient.__init__() takes 1 positional argument but 2 positional
#   arguments (and 1 keyword-only argument) were given
```

Optional kwargs accepted by `DeepgramClient.__init__`:

| kwarg                      | type     | default        | purpose                              |
|----------------------------|----------|----------------|--------------------------------------|
| `api_key`                  | str      | (required)     | API key for auth                     |
| `access_token`             | str      | None           | Bearer token override                |
| `session_id`               | str      | auto-generated | x-deepgram-session-id header         |
| `reconnect`                | bool     | True           | Auto-reconnect (set False for custom transport) |
| `redact_credentials_in_logs` | bool   | True           | Masks API key in websockets DEBUG logs |
| `telemetry_opt_out`        | bool     | True           | No-op (telemetry not implemented)    |
| `transport_factory`        | callable | None           | Custom WebSocket transport           |

### Async client

```python
from deepgram import AsyncDeepgramClient

client = AsyncDeepgramClient(api_key="...")
# Same kwargs as sync client.
```

**Recommendation for this repo:** Use the **sync** `DeepgramClient`.
The existing `VoiceAudioProcessor` already uses a background worker thread with a
`queue.Queue`. Using the sync SDK means:

1. `V1Client.connect(...)` is a `@contextmanager` — use `with` to scope the socket.
2. `V1SocketClient.start_listening()` is a **blocking** call — run it in a single
   dedicated I/O thread.
3. Event handlers are registered via `socket.on(EventType.MESSAGE, callback)`.
4. `send_media()` / `send_keep_alive()` / `send_finalize()` / `send_close_stream()`
   are synchronous and safe to call from the same I/O thread.

This avoids the complexity of `asyncio.run_coroutine_threadsafe()` when bridging
between the audio callback thread and the SDK.

---

## 2. Listen v1 connection

### `client.listen.v1.connect(...)`

```python
from contextlib import contextmanager

# connect is a @contextmanager yielding V1SocketClient
with client.listen.v1.connect(
    model="nova-3",             # ListenV1Model, required, no default
    language="lt",              # ListenV1Language
    keyterm=["term1", "term2"], # ListenV1Keyterm (list of strings)
    endpointing=300,            # ListenV1Endpointing (int ms)
    interim_results=True,       # ListenV1InterimResults (bool)
    sample_rate=16000,          # ListenV1SampleRate
    encoding="linear16",        # ListenV1Encoding
    channels=1,                 # ListenV1Channels
    smart_format=True,          # ListenV1SmartFormat
    punctuate=True,             # ListenV1Punctuate
    numerals=True,              # ListenV1Numerals
    tag="tournament",           # ListenV1Tag
    utterance_end_ms=1000,      # ListenV1UtteranceEndMs
    vad_events=True,            # ListenV1VadEvents
    version="1",                # ListenV1Version
    authorization=None,         # str or None
    request_options=None,       # RequestOptions
) as connection:
    ...
```

All parameters are keyword-only. `model` is the only required parameter.
All other parameters default to `None` and are stripped from the query string
via `remove_none_from_dict` before URL construction.

### URL construction

The WebSocket URL is built as:

```
wss://api.deepgram.com/v1/listen?<urlencoded_query_params>
```

Query params are assembled by:

1. `remove_none_from_dict({...})` — strips `None` values.
2. `jsonable_encoder(...)` — serializes to JSON-compatible values.
3. `encode_query(...)` + `single_query_encoder(...)` — converts each key/value
   pair into a list of `(key, value)` tuples.
4. `urllib.parse.urlencode(...)` — encodes the tuple list into a URL query string.

---

## 3. EventType

Located in `deepgram.core.events`:

```python
class EventType(str, Enum):
    OPEN = "open"
    MESSAGE = "message"
    ERROR = "error"
    CLOSE = "close"
```

Events are registered via `connection.on(EventType, callback)` and dispatched
internally by `EventEmitterMixin._emit()`.

---

## 4. Typed response classes

The WebSocket message handler parses each incoming JSON message into a
`V1SocketClientResponse` (a `Union` of all possible message types). The
`EventType.MESSAGE` callback receives this parsed object.

### `ListenV1Results` (type field = `"Results"`)

```
model_fields:
  type: typing.Literal['Results']
  channel_index: List[int]
  duration: float
  start: float
  is_final: Optional[bool]
  speech_final: Optional[bool]
  channel: ListenV1ResultsChannel
  metadata: ListenV1ResultsMetadata
  from_finalize: Optional[bool]
  entities: Optional[List[ListenV1ResultsEntitiesItem]]
```

### `ListenV1ResultsChannel`

```
model_fields:
  alternatives: List[ListenV1ResultsChannelAlternativesItem]
```

### `ListenV1ResultsChannelAlternativesItem`

```
model_fields:
  transcript: str
  confidence: float
  languages: Optional[List[str]]
  words: List[...]
```

**Transcript field mapping:**

```python
message.channel.alternatives[0].transcript  # str — primary transcript
message.is_final                            # Optional[bool] — segment is final
message.speech_final                        # Optional[bool] — utterance is final
```

### `ListenV1SpeechStarted` (type = `"SpeechStarted"`)

```
model_fields:
  type: Literal['SpeechStarted']
  channel: List[int]
  timestamp: float
```

Signals the start of speech within a channel.

### `ListenV1UtteranceEnd` (type = `"UtteranceEnd"`)

```
model_fields:
  type: Literal['UtteranceEnd']
  channel: List[int]
  last_word_end: float
```

Signals a pause long enough to mark the end of an utterance (controlled by
`utterance_end_ms`).

### `ListenV1Metadata` (type = `"Metadata"`)

```
model_fields:
  type: Literal['Metadata']
  transaction_key: str
  request_id: str
  sha256: str
  created: datetime
  duration: float
  channels: List[int]
```

### `ListenV1AcceptedResponse`

```
model_fields:
  type: Literal['Accepted']
  request_id: str
```

---

## 5. Control methods (`V1SocketClient`)

| method            | signature                                            | purpose                            |
|-------------------|------------------------------------------------------|------------------------------------|
| `send_media`      | `(message: bytes) -> None`                           | Send raw PCM frames                |
| `send_keep_alive` | `(message: Optional[ListenV1KeepAlive] = None) -> None` | Keep connection alive         |
| `send_finalize`   | `(message: Optional[ListenV1Finalize] = None) -> None` | Request finalization of utterance |
| `send_close_stream`| `(message: Optional[ListenV1CloseStream] = None) -> None` | Close the stream              |
| `start_listening` | `() -> None`                                         | Block & dispatch events (sync)    |
| `recv`            | `() -> V1SocketClientResponse`                       | Pull next message (sync)          |
| `on`              | `(event_name: EventType, callback: Callable) -> None` | Register event handler          |

### Async variants (`AsyncV1SocketClient`)

| method            | signature                                            |
|-------------------|------------------------------------------------------|
| `send_media`      | `async (message: bytes) -> None`                    |
| `send_keep_alive` | `async (message: Optional[...] = None) -> None`     |
| `send_finalize`   | `async (message: Optional[...] = None) -> None`     |
| `send_close_stream`| `async (message: Optional[...] = None) -> None`    |
| `start_listening` | `async () -> None` (blocking loop)                 |
| `recv`            | `async () -> Union[...]`                           |
| `on`              | `(event_name: EventType, callback: Callable) -> None` (sync registration) |

---

## 6. Error types

### WebSocket connection failure (auth / bad status)

`V1Client.connect` wraps the WebSocket open in a try/except:

```python
try:
    with websockets_sync_client.connect(ws_url, additional_headers=headers) as protocol:
        yield V1SocketClient(websocket=protocol)
except InvalidWebSocketStatus as exc:
    status_code: int = get_status_code(exc)
    if status_code == 401:
        raise ApiError(
            status_code=status_code,
            headers=dict(headers),
            body="Websocket initialized with invalid credentials.",
        )
    raise ApiError(
        status_code=status_code,
        headers=dict(headers),
        body="Unexpected error when initializing websocket connection.",
    )
```

- **Auth failure (401):** Raises `ApiError` (subclass of `Exception`) from the
  `with client.listen.v1.connect(...)` context manager entry. `status_code=401`,
  `body="Websocket initialized with invalid credentials."`.
- **Bad status (other):** Raises `ApiError` with the appropriate status code.

### Runtime errors during `start_listening`

Errors during the listening loop are emitted as `EventType.ERROR` events with the
exception object as the payload:

```python
except Exception as exc:
    self._emit(EventType.ERROR, exc)
```

The callback registered via `connection.on(EventType.ERROR, cb)` receives the
raw `Exception` object.

### Timeout handling

The SDK does not build in a connect timeout parameter. A blocking
`websockets_sync_client.connect(...)` call will hang indefinitely if the server
does not respond. For this repo, wrap the `connect()` context manager entry in
a `concurrent.futures.ThreadPoolExecutor` + `future.result(timeout=...)` to
enforce `VOICE_DEEPGRAM_CONNECT_TIMEOUT_SECONDS`.

---

## 7. Keyterm serialization verification

**Result: SDK 7.6.0 preserves repeated `keyterm=` query parameters.**

When a Python list is passed as `keyterm`:

```python
keyterm=["Tomas Žeringis", "Juozas Petraitis", "taškas", "atšaukti"]
```

The `single_query_encoder` iterates the list and produces one
`(keyterm, value)` tuple per element. The final URL contains:

```
keyterm=Tomas+%C5%BDeringis&keyterm=Juozas+Petraitis&keyterm=ta%C5%A1kas&keyterm=at%C5%A1aukti
```

Each Lithuanian diacritic is properly URL-encoded:
- `Ž` → `%C5%BD`
- `š` → `%C5%A1`
- `ū` → `%C5%AB`

**No workaround is needed.** Passing a list of strings is the correct approach.
Commonly comma-separated values (`keyterm=a,b,c`) produce a single parameter
and must **not** be used.

---

## 8. Sync vs Async ownership recommendation

**Recommended:** Sync client with a dedicated I/O thread.

Rationale:
- The existing `VoiceAudioProcessor` already uses a background worker thread.
- The audio callback thread only needs to enqueue PCM bytes into a thread-safe
  `queue.Queue`.
- One dedicated thread owns the `DeepgramClient`, the `connection` (socket),
  and runs `start_listening()` in a blocking loop.
- All SDK calls (`send_media`, `send_keep_alive`, `send_finalize`,
  `send_close_stream`) are synchronous and called from that single thread.
- Event handler callbacks push finalized transcripts into the processor's
  `event_queue` via a thread-safe `put_nowait()`.

**Not recommended for Phase 1:** Async client — would require
`asyncio.run_coroutine_threadsafe()` bridging and adds complexity for no benefit
in this single-connection use case.

---

## 9. Import summary

```python
from deepgram import DeepgramClient          # sync
from deepgram import AsyncDeepgramClient      # async (not used in Phase 1)
from deepgram import BadRequestError          # subclass of ApiError

# Event types
from deepgram.core.events import EventType
# EventType.OPEN, EventType.MESSAGE, EventType.ERROR, EventType.CLOSE

# Response types (for isinstance checks / type narrowing)
from deepgram.listen.v1.types import (
    ListenV1Results,
    ListenV1UtteranceEnd,
    ListenV1SpeechStarted,
    ListenV1Metadata,
)

# Error type
from deepgram.core.api_error import ApiError
```

Note: `EventType` is not exported from the top-level `deepgram` package. It must
be imported from `deepgram.core.events`.
