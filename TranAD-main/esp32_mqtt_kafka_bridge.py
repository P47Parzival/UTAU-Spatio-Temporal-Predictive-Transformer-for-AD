import argparse
import asyncio
import json
import math
import os
import signal
import time
from dataclasses import dataclass
from typing import Any, Optional

try:
    from aiokafka import AIOKafkaProducer
except ImportError as exc:  # pragma: no cover - runtime guard
    raise SystemExit(
        "Missing dependency 'aiokafka'. Install with: pip install aiokafka"
    ) from exc

try:
    import paho.mqtt.client as mqtt
except ImportError as exc:  # pragma: no cover - runtime guard
    raise SystemExit(
        "Missing dependency 'paho-mqtt'. Install with: pip install paho-mqtt"
    ) from exc


DEFAULT_MQTT_HOST = os.getenv("ESP32_MQTT_HOST", "127.0.0.1")
DEFAULT_MQTT_HOSTS = os.getenv("ESP32_MQTT_HOSTS", "")
DEFAULT_MQTT_PORT = int(os.getenv("ESP32_MQTT_PORT", "1883"))
DEFAULT_MQTT_TOPIC = os.getenv("ESP32_MQTT_TOPIC", "esp32/telemetry")
DEFAULT_KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:29092")
DEFAULT_KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "telemetry-stream")


@dataclass
class BridgeStats:
    mqtt_messages: int = 0
    parse_errors: int = 0
    dropped_invalid: int = 0
    dropped_queue_full: int = 0
    kafka_published: int = 0
    connected: bool = False
    started_at_ms: int = 0
    last_mqtt_message_ms: int = 0
    last_failover_ms: int = 0


def _reason_code_to_int(reason_code: Any) -> int:
    if isinstance(reason_code, int):
        return reason_code
    try:
        return int(reason_code)
    except Exception:
        value = getattr(reason_code, "value", None)
        if isinstance(value, int):
            return value
    return -1


def _safe_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(f):
        return f
    return None


def _normalize_payload(
    payload: dict[str, Any],
    dataset: str,
    default_source_id: str,
    expected_dimensions: int,
    timestamp_field: str,
    sensors_field: str,
    seq_counter: int,
) -> Optional[dict[str, Any]]:
    timestamp_raw = payload.get(timestamp_field, int(time.time() * 1000))
    try:
        timestamp_ms = int(timestamp_raw)
    except (TypeError, ValueError):
        return None

    sensors_raw = payload.get(sensors_field)
    sensors: list[Any]
    if isinstance(sensors_raw, list):
        sensors = sensors_raw
    elif isinstance(sensors_raw, dict):
        # Stable ordering for dict payloads: sensor0..sensorN or lexicographic fallback
        ordered_keys = sorted(sensors_raw.keys(), key=str)
        sensors = [sensors_raw[k] for k in ordered_keys]
    else:
        return None

    parsed = []
    for value in sensors:
        f = _safe_float(value)
        if f is None:
            return None
        parsed.append(f)

    if expected_dimensions > 0 and len(parsed) != expected_dimensions:
        return None

    source_id = str(payload.get("source_id", default_source_id))
    seq_id_raw = payload.get("seq_id", seq_counter)
    try:
        seq_id = int(seq_id_raw)
    except (TypeError, ValueError):
        seq_id = seq_counter

    return {
        "timestamp_ms": timestamp_ms,
        "sensors": parsed,
        "dataset": dataset,
        "source_id": source_id,
        "seq_id": seq_id,
    }


async def run_bridge(args: argparse.Namespace) -> None:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max(100, int(args.queue_size)))
    stats = BridgeStats()
    stats.started_at_ms = int(time.time() * 1000)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if str(args.mqtt_hosts).strip():
        mqtt_hosts = [h.strip() for h in str(args.mqtt_hosts).split(",") if h.strip()]
    else:
        mqtt_hosts = [str(args.mqtt_host).strip()]
    if not mqtt_hosts:
        mqtt_hosts = [DEFAULT_MQTT_HOST]
    mqtt_host_index = 0
    active_mqtt_host = mqtt_hosts[mqtt_host_index]

    seq_counter = 0

    def _enqueue(item: dict[str, Any]) -> None:
        if queue.full():
            stats.dropped_queue_full += 1
            return
        queue.put_nowait(item)

    def on_connect(
        client: mqtt.Client,
        _userdata: Any,
        _flags: dict[str, Any],
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        rc = _reason_code_to_int(reason_code)
        if rc == 0:
            stats.connected = True
            print(f"[BRIDGE] MQTT connected: {active_mqtt_host}:{args.mqtt_port}; subscribing {args.mqtt_topic}")
            client.subscribe(args.mqtt_topic, qos=args.mqtt_qos)
        else:
            stats.connected = False
            print(f"[BRIDGE] MQTT connect failed with rc={rc}")

    def on_disconnect(
        _client: mqtt.Client,
        _userdata: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        rc = _reason_code_to_int(reason_code)
        stats.connected = False
        print(f"[BRIDGE] MQTT disconnected rc={rc}")

    def on_message(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        nonlocal seq_counter
        stats.mqtt_messages += 1
        stats.last_mqtt_message_ms = int(time.time() * 1000)
        seq_counter += 1
        try:
            payload_obj = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            stats.parse_errors += 1
            return
        if not isinstance(payload_obj, dict):
            stats.parse_errors += 1
            return

        normalized = _normalize_payload(
            payload=payload_obj,
            dataset=args.dataset,
            default_source_id=args.source_id,
            expected_dimensions=args.expected_dimensions,
            timestamp_field=args.timestamp_field,
            sensors_field=args.sensors_field,
            seq_counter=seq_counter,
        )
        if normalized is None:
            stats.dropped_invalid += 1
            return
        loop.call_soon_threadsafe(_enqueue, normalized)

    try:
        mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=args.mqtt_client_id,
            protocol=mqtt.MQTTv311,
        )
    except Exception:
        mqtt_client = mqtt.Client(client_id=args.mqtt_client_id, protocol=mqtt.MQTTv311)
    if args.mqtt_username:
        mqtt_client.username_pw_set(args.mqtt_username, args.mqtt_password)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message
    mqtt_client.connect(active_mqtt_host, args.mqtt_port, keepalive=60)
    mqtt_client.loop_start()

    producer = AIOKafkaProducer(
        bootstrap_servers=[s.strip() for s in args.kafka_bootstrap_servers.split(",") if s.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
    )
    await producer.start()

    async def _stats_reporter() -> None:
        nonlocal mqtt_host_index, active_mqtt_host
        while not stop_event.is_set():
            await asyncio.sleep(max(1.0, args.report_interval_sec))
            now_ms = int(time.time() * 1000)
            up_for_ms = now_ms - stats.started_at_ms
            no_mqtt_for_ms = (now_ms - stats.last_mqtt_message_ms) if stats.last_mqtt_message_ms else up_for_ms
            print(
                "[BRIDGE] "
                f"connected={stats.connected} "
                f"mqtt={stats.mqtt_messages} parse_errors={stats.parse_errors} "
                f"invalid={stats.dropped_invalid} queue_full={stats.dropped_queue_full} "
                f"kafka_published={stats.kafka_published} queue={queue.qsize()}"
            )
            if stats.connected and stats.mqtt_messages == 0 and up_for_ms >= 20000:
                print(
                    "[BRIDGE] Hint: still no MQTT messages. Verify ESP32 broker IP/port, topic, "
                    "and host firewall for inbound TCP 1883."
                )
                if (
                    len(mqtt_hosts) > 1
                    and no_mqtt_for_ms >= int(args.no_mqtt_failover_sec * 1000)
                    and (now_ms - stats.last_failover_ms) >= int(args.no_mqtt_failover_sec * 1000)
                ):
                    mqtt_host_index = (mqtt_host_index + 1) % len(mqtt_hosts)
                    active_mqtt_host = mqtt_hosts[mqtt_host_index]
                    stats.last_failover_ms = now_ms
                    print(f"[BRIDGE] No MQTT traffic, failover -> {active_mqtt_host}:{args.mqtt_port}")
                    try:
                        mqtt_client.disconnect()
                    except Exception:
                        pass
                    try:
                        mqtt_client.connect(active_mqtt_host, args.mqtt_port, keepalive=60)
                    except Exception as exc:
                        print(f"[BRIDGE] failover connect error: {exc}")
            elif stats.connected and stats.mqtt_messages > 0 and no_mqtt_for_ms >= 20000:
                print(
                    "[BRIDGE] Hint: MQTT stream stalled. Check ESP32 power/network stability "
                    "and keepalive reconnect behavior."
                )

    reporter_task = asyncio.create_task(_stats_reporter())

    try:
        print(
            f"[BRIDGE] Running dataset={args.dataset}, expected_dimensions={args.expected_dimensions}, "
            f"mqtt_topic={args.mqtt_topic}, kafka_topic={args.kafka_topic}"
        )
        while True:
            event = await queue.get()
            await producer.send_and_wait(args.kafka_topic, event)
            stats.kafka_published += 1
    except asyncio.CancelledError:
        raise
    finally:
        stop_event.set()
        reporter_task.cancel()
        try:
            await reporter_task
        except Exception:
            pass
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        await producer.stop()
        print("[BRIDGE] stopped")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESP32 MQTT to Kafka bridge for TranAD telemetry")
    parser.add_argument("--mqtt-host", default=DEFAULT_MQTT_HOST)
    parser.add_argument("--mqtt-hosts", default=DEFAULT_MQTT_HOSTS)
    parser.add_argument("--mqtt-port", type=int, default=DEFAULT_MQTT_PORT)
    parser.add_argument("--mqtt-topic", default=DEFAULT_MQTT_TOPIC)
    parser.add_argument("--mqtt-qos", type=int, default=0, choices=[0, 1, 2])
    parser.add_argument("--mqtt-client-id", default="tranad-esp32-bridge")
    parser.add_argument("--mqtt-username", default="")
    parser.add_argument("--mqtt-password", default="")
    parser.add_argument("--kafka-bootstrap-servers", default=DEFAULT_KAFKA_BOOTSTRAP)
    parser.add_argument("--kafka-topic", default=DEFAULT_KAFKA_TOPIC)
    parser.add_argument("--dataset", default="ESP32")
    parser.add_argument("--source-id", default="esp32-001")
    parser.add_argument("--expected-dimensions", type=int, default=64)
    parser.add_argument("--timestamp-field", default="timestamp_ms")
    parser.add_argument("--sensors-field", default="sensors")
    parser.add_argument("--queue-size", type=int, default=2000)
    parser.add_argument("--report-interval-sec", type=float, default=5.0)
    parser.add_argument("--no-mqtt-failover-sec", type=float, default=20.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task = loop.create_task(run_bridge(args))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, main_task.cancel)
        except NotImplementedError:
            # Windows event loop fallback
            pass

    try:
        loop.run_until_complete(main_task)
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
