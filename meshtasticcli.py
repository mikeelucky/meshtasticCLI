#!/usr/bin/env python3
"""
meshtastic TUI client — no internet, no servers, no gods
"""
import random
import asyncio
import time
import sys
import os
import pprint
import sqlite3
import jsonQ
from datetime import datetime, timezone, timedelta
from collections import defaultdict, deque
from typing import Optional
from textual.widget import Widget
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static, Label, Button
from textual.screen import ModalScreen
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from rich.text import Text
from rich.markup import escape as markup_escape

try:
    import meshtastic
    import meshtastic.serial_interface
    import meshtastic.tcp_interface
    from pubsub import pub
    MESH_AVAILABLE = True
except ImportError:
    print("Error: meshtastic or pypubsub dependencies not installed.")
    sys.exit(1)


C = {
    "dim":     "#3d4451",
    "border":  "#4a5568",
    "accent":  "#68d391",   # green
    "accent2": "#63b3ed",   # blue
    "warn":    "#f6ad55",   # amber
    "danger":  "#fc8181",   # red
    "ghost":   "#718096",   # grey
    "text":    "#e2e8f0",   # near-white
    "hi":      "#9f7aea",   # purple
    "bg":      "on #0d1117",
}

MANIFESTS = [   
    "no internet · no servers · no gods",
    "off-grid · off-cloud · off-leash",
    "off-grid, on-air",
    "decentralized by design",
    "frequency is freedom",
    "peer-to-peer, forever",
    "signal through silence",
    "nodes over networks",
    "when in doubt · transmit",
    "the cloud is someone else's computer · this is yours",
    "radio waves don't need terms of service",
    "no login required · no soul collected",
    "no API keys · no rate limits · no quarterly earnings calls",
    "packet radio never needed a venture capitalist",
    "the mesh doesn't have a privacy policy · the mesh has physics",
    "no data broker can hear you on 915MHz",
    "packets travel by radio · not by grace of silicon valley",
    "no subscription · no surveillance · no surrender",
    "infrastructure is a liability · frequency is free",
    "born in the noise floor · thriving in the static",
    "no uptime SLA · just physics and willpower",
    "SNR > politics", 
    "LoRa carries farther than promises",
    "500mW of transmit power · infinite jurisdictional ambiguity",
    "every hop a handshake between equals",
    "no BGP required · no peering agreements · just RF",
    "spread spectrum · spread autonomy",
    "your data ends at the antenna · not in a warehouse",
    "when the towers fall · the mesh stands",
    "mesh survives the apocalypse · you might too",
    "mesh: the last network standing",
    "every node a republic · every packet sovereign",
    "the topology is flat · like the power structure should be",
    "mesh topology: no head to cut off",
    "where coverage ends · community begins",
    "nodes don't ask for permission · neither should you",
    "signal propagates · empires don't",    
    "pinging the ether · no traceroute needed", 
    "hardware, firmware, atmosphere", 
    "terminal to terminal, antenna to antenna", 
    "can't patch out the laws of physics", 
    "free speech runs on 12.5 kHz bandwidth", 
    "encrypted in transit · forgotten on arrival", 
    "routing tables built by trust · not algorithms",
    "packet injected · airwaves liberated",
    "the grid is an illusion · the mesh is real",
    "no central authority · just peer consensus and RF",
    "airwaves belong to the code",
    "unmonitored, unfiltered, unstoppable",
    "unplugged from the net · plugged into the environment",
    ]


# ── НАСТРОЙКИ ВРЕМЕНИ (UTC+3 Москва автономно) ──────────────────────────────
MOSCOW_TZ = timezone(timedelta(hours=3))

# ── DATABASE INTERFACE (SQLite3) ──────────────────────────────────────────────
DB_PATH = "mcli.db"

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
         
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    node_id TEXT PRIMARY KEY,
                    label   TEXT
                )
            """)
    
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT,
                    sender TEXT,
                    text TEXT,
                    is_own BOOLEAN,
                    rssi REAL,
                    snr REAL,
                    hops INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
      
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS packets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    payload TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def add_favorite(self, node_id: str, label: str):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO favorites (node_id, label) VALUES (?, ?)",
                (node_id, label)
            )

    def remove_favorite(self, node_id: str):
        with self.conn:
            self.conn.execute("DELETE FROM favorites WHERE node_id = ?", (node_id,))

    def get_favorites(self) -> dict:
        """Возвращает {node_id: label}"""
        cur = self.conn.execute("SELECT node_id, label FROM favorites")
        return {row["node_id"]: row["label"] for row in cur.fetchall()}

    def get_setting(self, key: str) -> Optional[str]:
        cur = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
                (key, str(value))
            )

    def save_message(self, channel: str, sender: str, text: str, is_own: bool, 
                     rssi: Optional[float], snr: Optional[float], hops: Optional[int]):
        with self.conn:
            self.conn.execute("""
                INSERT INTO messages (channel, sender, text, is_own, rssi, snr, hops)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (channel, sender, text, 1 if is_own else 0, rssi, snr, hops))

    def get_history(self, channel: str, limit: int = 100) -> list:
        cur = self.conn.execute("""
            SELECT channel, sender, text, is_own, rssi, snr, hops, timestamp 
            FROM messages 
            WHERE channel = ? 
            ORDER BY id DESC LIMIT ?
        """, (channel, limit))
        rows = cur.fetchall()
        return list(reversed(rows))

    def save_packet(self, topic: str, payload: dict):
        try:
            serialized = json.dumps(payload, default=str)
            with self.conn:
                self.conn.execute(
                    "INSERT INTO packets (topic, payload) VALUES (?, ?)",
                    (topic, serialized)
                )
        except Exception:
            pass

db = Database()


def _normalize_node_id(raw: str) -> str:
    """Convert any node id form to !hexid.
    Accepts: decimal int string '181026860', '!0aca402c', '0aca402c'.
    Returns: '!0aca402c'
    """
    if not raw:
        return raw
    s = str(raw).strip()
    if s.startswith("!"):
        return s.lower()
   
    try:
        n = int(s)
        return f"!{n:08x}"
    except ValueError:
        pass
 
    try:
        int(s, 16)
        return f"!{s.lower()}"
    except ValueError:
        pass
    return s


def ts() -> str:
    """Return current time as HH:MM:SS in Europe/Moscow timezone."""
    return datetime.now(MOSCOW_TZ).strftime("%H:%M:%S")


def node_color(node_id: str) -> str:
    """Assign a deterministic color to a node ID."""
    colors = [C["accent"], C["accent2"], C["hi"], C["warn"], "#f687b3", "#76e4f7"]
    return colors[abs(hash(str(node_id))) % len(colors)]


def snr_bar(snr: float) -> str:
    """Render SNR as a bar with color-coded intensity."""
    bars = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    try:
        level = max(0, min(7, int((float(snr) + 5) / 3)))
    except (ValueError, TypeError):
        return f"[{C['ghost']}]?[/{C['ghost']}]"

    if snr >= 8:   col = C["accent"]
    elif snr >= 3: col = C["warn"]
    else:          col = C["danger"]

    return f"[{col}]{bars[level] * (level + 1)}[/{col}]"


def hop_indicator(hops: int) -> str:
    """Render hop count with visual indicator."""
    if hops == 0:
        return f"[{C['accent']}]◉ direct[/{C['accent']}]"
    elif hops == 1:
        return f"[{C['accent2']}]◎ {hops}hop[/{C['accent2']}]"
    elif hops == 2:
        return f"[{C['warn']}]○ {hops}hop[/{C['warn']}]"
    else:
        return f"[{C['ghost']}]· {hops}hop[/{C['ghost']}]"


# ── MESSAGE STORE WITH PERSISTENCE ────────────────────────────────────────────

class MessageStore:
    def __init__(self):
        self.channels: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.unread: dict[str, int] = defaultdict(int)
        self.pending_acks: dict[int, dict] = {}
        self._late_acks: dict[int, tuple] = {}

    def load_history(self, channel: str):
        """Loads historical messages from SQLite if current queue is empty."""
        if len(self.channels[channel]) == 0:
            history = db.get_history(channel)
            for row in history:
                timestamp_str = row["timestamp"]
                
                try:
                    dt_utc = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    dt_msc = dt_utc.astimezone(MOSCOW_TZ)
                    ts_str = dt_msc.strftime("%H:%M:%S")
                except Exception:
                    if " " in timestamp_str:
                        ts_str = timestamp_str.split(" ")[1][:8]
                    else:
                        ts_str = timestamp_str[:8]

                self.channels[channel].append({
                    "ts": ts_str,
                    "sender": row["sender"],
                    "text": row["text"],
                    "is_own": bool(row["is_own"]),
                    "rssi": row["rssi"],
                    "snr": row["snr"],
                    "raw_debug": False,
                    "hops": row["hops"],
                    "ack": "ack" if row["is_own"] else None,
                    "ack_detail": "",
                })

    def add(self, channel: str, sender: str, text: str,
            is_own=False, rssi=None, snr=None, hops=None, is_raw_debug=False, packet_id=None) -> dict:
        
        if channel not in ("system", "debug") and not is_raw_debug:
            db.save_message(channel, sender, text, is_own, rssi, snr, hops)

        entry = {
            "ts": ts(),
            "sender": str(sender),
            "text": text,
            "is_own": is_own,
            "rssi": rssi,
            "snr": snr,
            "raw_debug": is_raw_debug,
            "hops": hops,
            "ack": None,
            "ack_detail": "",
        }
        self.channels[channel].append(entry)
        if not is_own:
            self.unread[channel] += 1
        if is_own and packet_id is not None:
            self.pending_acks[int(packet_id)] = entry
            self.add("debug", ">>>DBG<<<",
                f"\n" + "="*50 +
                f"\n  [PENDING_ACK REGISTERED] pid={int(packet_id)}"
                f"\n  pending_keys={list(self.pending_acks.keys())}"
                f"\n  late_acks={list(self._late_acks.keys())}"
                f"\n" + "="*50, is_raw_debug=True)
        return entry

    def set_ack(self, packet_id: int, status: str, detail: str = "") -> bool:
        """Mark a sent message ack/nack/relay. Returns True if found."""
        pid = int(packet_id)
        entry = self.pending_acks.get(pid)
        if entry:
            if entry["ack"] != "ack":  
                entry["ack"] = status
                entry["ack_detail"] = detail
            return True
        self._late_acks[pid] = (status, detail)
        return False

    def _apply_late_ack(self, packet_id: int, entry: dict):
        """Apply buffered ACK if it arrived before store.add()."""
        pid = int(packet_id)
        if pid in self._late_acks:
            status, detail = self._late_acks.pop(pid)
            entry["ack"] = status
            entry["ack_detail"] = detail

    def mark_read(self, channel: str):
        self.unread[channel] = 0

    def get(self, channel: str) -> list:
        return list(self.channels[channel])

    def drop_channel(self, channel: str):
        if channel in self.channels:
            del self.channels[channel]
        if channel in self.unread:
            del self.unread[channel]


# ── MESH INTERFACE WRAPPER ────────────────────────────────────────────────────

def _extract_packet_id(result, store=None) -> Optional[int]:
    """Extract packet id. store= optional MessageStore for debug logging."""
    def dbg(msg):
        if store:
            store.add("debug", ">>>DBG<<<", f"\n{'='*50}\n  EXTRACT_PID: {msg}\n{'='*50}", is_raw_debug=True)

    if result is None:
        dbg("result is None")
        return None

    dbg(f"type={type(result).__name__}  repr={repr(result)[:200]}")

    if isinstance(result, dict):
        v = result.get("id") or result.get("packetId")
        dbg(f"dict path -> {v}")
        return v

    for attr in ("id", "packetId", "packet_id"):
        val = getattr(result, attr, None)
        dbg(f"getattr({attr!r}) = {val!r}")
        if val:
            return int(val)

    try:
        names = [f.name for f in result.DESCRIPTOR.fields]
        dbg(f"DESCRIPTOR fields: {names}")
        for field in result.DESCRIPTOR.fields:
            if field.name == "id":
                v = int(getattr(result, field.name))
                dbg(f"DESCRIPTOR id = {v}")
                return v
    except Exception as ex:
        dbg(f"DESCRIPTOR error: {ex}")

    import re
    r = repr(result)
    m = re.search(r"\bid:\s*(\d+)", r)
    dbg(f"regex on repr -> {m.group(1) if m else None}")
    if m:
        return int(m.group(1))

    dbg("ALL METHODS FAILED - returning None")
    return None


class MeshInterface:
    def __init__(self, store: MessageStore, on_update):
        self.store = store
        self.on_update = on_update
        self.iface = None
        self.my_id = "!local"
        self.my_name = "operator"
        self.nodes: dict = {}
        self._excluded_nodes: set = set()        
        self.connected = False
        self.channel_names: dict[int, str] = {0: "primary"}
        self.app_channels_callback = None
        self.app_dm_callback = None
        self._ping_sessions: dict[int, tuple] = {}
        self._traceroute_sessions: dict[int, tuple] = {}

    def _refresh_nodes(self) -> None:
        if self.iface and hasattr(self.iface, "nodes") and self.iface.nodes:
            self.nodes = {
                k: v for k, v in self.iface.nodes.items()
                if str(k) not in self._excluded_nodes
            }

    def connect_serial(self, port: str) -> bool:
        try:
            self.iface = meshtastic.serial_interface.SerialInterface(port)
            self._setup_real()
            return True
        except Exception as e:
            self.store.add("system", "sys", f"serial connect failed: {e}")
            return False

    def connect_tcp(self, host: str, port: int = 4403) -> bool:
        try:
            self.iface = meshtastic.tcp_interface.TCPInterface(host, portNumber=port)
            self._setup_real()
            return True
        except Exception as e:
            self.store.add("system", "sys", f"tcp connect failed: {e}")
            return False

    def _setup_real(self):
        pub.subscribe(self._on_recv, "meshtastic.receive")
        pub.subscribe(self._on_connect, "meshtastic.connection.established")
        pub.subscribe(self._global_raw_logger, pub.ALL_TOPICS)
        self.connected = True

        if self.iface and hasattr(self.iface, "channels"):
            for ch in self.iface.channels:
                if ch.index is not None and ch.settings and ch.settings.name:
                    ch_name = ch.settings.name.lower()
                    self.channel_names[ch.index] = ch_name
                    if self.app_channels_callback:
                        self.app_channels_callback(ch_name)

        info = self.iface.getMyNodeInfo()
        if info:
            self.my_id = str(info.get("num", "!local"))
            user = info.get("user", {})
            self.my_name = user.get("longName", "operator")
        self._refresh_nodes()

    def _global_raw_logger(self, topic=pub.AUTO_TOPIC, **kwargs):
        topic_name = topic.getName()
        clean_kwargs = {k: v for k, v in kwargs.items() if k != 'interface'}
        db.save_packet(topic_name, clean_kwargs)

        if "heartbeat" in topic_name.lower():
            return

        try:
            formatted_data = pprint.pformat(clean_kwargs, indent=2, width=60, depth=3)
        except Exception as e:
            formatted_data = f"Formatting error: {e}\nRaw keys: {list(kwargs.keys())}"

        debug_entry = f"[bold #ff79c6]▶ {topic_name}[/bold #ff79c6]\n[#8be9fd]{formatted_data}[/#8be9fd]"
        self.store.add("debug", "raw", debug_entry, is_raw_debug=True)
        if hasattr(self, 'on_update') and self.on_update:
            self.on_update()

    def _on_connect(self, interface, topic=pub.AUTO_TOPIC):
        self.connected = True
        self.store.add("system", "sys", "link established")
        self._refresh_nodes()
        self.on_update()

    def _on_recv(self, packet, interface):
        self._refresh_nodes()

        decoded = packet.get("decoded", {})
        text = decoded.get("text", "")
        portnum = decoded.get("portnum", "")
        sender_id_raw = str(packet.get("fromId", ""))
        sender_norm = _normalize_node_id(sender_id_raw) if sender_id_raw else ""

        # ── REPLY_APP pong (незашифрованные каналы) ──────────────────────────
        is_reply_app = (portnum == "REPLY_APP" or portnum == 32)
        if is_reply_app:
            self._handle_pong(packet, sender_norm)
            return

        # ── TRACEROUTE_APP response ───────────────────────────────────────────
        is_traceroute = (portnum == "TRACEROUTE_APP" or portnum == 70)
        if is_traceroute:
            self._handle_traceroute(packet, sender_norm)
            return

        # ── ROUTING (ACK/NAK) ────────────────────────────────────────────────
        routing = decoded.get("routing")
        if routing is not None:
            req_id = packet.get("requestId") or decoded.get("requestId")
            if req_id:
                error = routing.get("errorReason", "NONE")
                if isinstance(error, int):
                    error = "NONE" if error == 0 else str(error)
                is_ok = error in (None, "NONE", 0, "0")

                if is_ok and req_id in self._ping_sessions:
                    self._handle_pong(packet, sender_norm, via_ack=True, req_id=req_id)
                elif is_ok:
                    self.store.set_ack(req_id, "ack")
                else:
                    if req_id in self._ping_sessions:
                        _, _, ping_tab = self._ping_sessions.pop(req_id)
                        self.store.add(ping_tab, "~ ping", f"✗ NAK: {error}")
                        if self.app_dm_callback:
                            self.app_dm_callback(ping_tab)
                    else:
                        self.store.set_ack(req_id, "nack", error)
                self.on_update()
            if hasattr(self, "app") and self.app:
                self.app.call_from_thread(self.app._force_refresh_log)
            return

        # ── нет текста — дамп в debug ────────────────────────────────────────
        if not text:
            self.store.add("debug", "raw",
                f"[no-text pkt] portnum={portnum!r} from={sender_id_raw} "
                f"reqId={packet.get('requestId')} decoded_keys={list(decoded.keys())}",
                is_raw_debug=True)
            self.on_update()
            return

        # ── текстовое сообщение ──────────────────────────────────────────────
        raw_to_id = packet.get("toId")
        to_id = str(raw_to_id if raw_to_id is not None else "^all")
        rssi = packet.get("rxRssi")
        snr  = packet.get("rxSnr")
        hops_away = packet.get("hopsAway")
        if hops_away is None:
            hop_start = packet.get("hopStart")
            hop_limit = packet.get("hopLimit")
            if hop_start is not None and hop_limit is not None:
                hops_away = hop_start - hop_limit

        is_broadcast = (
            to_id.startswith("^") or
            to_id == "4294967295" or
            raw_to_id == 4294967295 or
            to_id.lower() == "!ffffffff"
        )
        is_dm = not is_broadcast

        if is_dm:
            my_str_id = str(self.my_id)
            is_from_me = (sender_id_raw == my_str_id or
                          sender_id_raw.replace("!", "") == my_str_id.replace("!", ""))
            peer_id = sender_id_raw if not is_from_me else to_id
            dm_tab_name = f"▶{_normalize_node_id(str(peer_id))}"
            if self.app_dm_callback:
                self.app_dm_callback(dm_tab_name)
            self.store.add(dm_tab_name, sender_id_raw, text, rssi=rssi, snr=snr, hops=hops_away)
        else:
            ch_index = packet.get("channel", 0)
            channel = self.channel_names.get(ch_index, f"ch_{ch_index}")
            if self.app_channels_callback:
                self.app_channels_callback(channel)
            self.store.add(channel, sender_id_raw, text, rssi=rssi, snr=snr, hops=hops_away)
        

            if channel == self.channel_names.get(ch_index) and ch_index == 0:  
                self.on_update()
                if hasattr(self, 'app') and self.app:
                    self.app.call_from_thread(self.app._force_refresh_log)
                
            if channel == self.current_channel: 
                self.on_update()
                if hasattr(self, 'app') and self.app:
                    self.app.call_from_thread(lambda: self.app._refresh_log(force=True))



        self.on_update()
        if hasattr(self, 'app') and self.app:
            self.app.call_from_thread(self.app._refresh_log)
            self.app.call_from_thread(self.app._refresh_nodes)

    def _handle_pong(self, packet, sender_norm: str, via_ack: bool = False, req_id=None):
        rssi = packet.get("rxRssi")
        snr  = packet.get("rxSnr")
        hops_away = packet.get("hopsAway")
        if hops_away is None:
            hop_start = packet.get("hopStart")
            hop_limit = packet.get("hopLimit")
            if hop_start is not None and hop_limit is not None:
                hops_away = hop_start - hop_limit

        matched_session = None
        matched_pid = None

        if req_id and req_id in self._ping_sessions:
            matched_pid = req_id
            matched_session = self._ping_sessions.pop(req_id)
        else:
            for pid, sess in list(self._ping_sessions.items()):
                sess_target, _, _ = sess
                if _normalize_node_id(sess_target) == sender_norm:
                    matched_pid = pid
                    matched_session = self._ping_sessions.pop(pid)
                    break

        if matched_session:
            _, send_time, ping_tab = matched_session
            rtt_ms = (time.time() - send_time) * 1000
            rtt_str = f"{rtt_ms:.0f}ms"
        else:
            ping_tab = f"▶{sender_norm or packet.get('fromId', '?')}"
            rtt_str = "?"

        if via_ack and matched_session:
            sess_target = matched_session[0]
            norm_target = _normalize_node_id(sess_target)
            for nid, info in self.nodes.items():
                if _normalize_node_id(str(nid)) == norm_target and isinstance(info, dict):
                    if snr is None:
                        snr = info.get("snr")
                    if hops_away is None:
                        hops_away = info.get("hopsAway")
                    break

        label = "PONG"
        hop_part  = hop_indicator(hops_away) if hops_away is not None else ""
        snr_part  = snr_bar(snr) if snr is not None else ""
        rssi_part = f"rssi:{rssi}" if rssi is not None else ""

        pong_line = f"{label}  rtt:{rtt_str}".strip()
        self.store.add(ping_tab, "pong", pong_line, rssi=rssi, snr=snr, hops=hops_away)

        if self.app_dm_callback:
            self.app_dm_callback(ping_tab)
        self.on_update()
        if hasattr(self, 'app') and self.app:
            self.app.call_from_thread(self.app._refresh_log)
            self.app.call_from_thread(self.app._refresh_nodes)

    def _handle_traceroute(self, packet, sender_norm: str):
        decoded = packet.get("decoded", {})
        tr = decoded.get("traceroute", {})
        route      = tr.get("route", [])
        route_back = tr.get("routeBack", [])
        snr_towards = tr.get("snrTowards", [])
        snr_back    = tr.get("snrBack", [])

        req_id = packet.get("requestId") or decoded.get("requestId")

        matched_session = None
        if req_id and req_id in self._traceroute_sessions:
            matched_session = self._traceroute_sessions.pop(req_id)
        else:
            for pid, sess in list(self._traceroute_sessions.items()):
                sess_target, _, _ = sess
                if _normalize_node_id(sess_target) == sender_norm:
                    matched_session = self._traceroute_sessions.pop(pid)
                    break

        if matched_session:
            target_id, send_time, dm_tab = matched_session
            rtt_ms = (time.time() - send_time) * 1000
            rtt_str = f"{rtt_ms:.0f}ms"
        else:
            dm_tab = f"▶{sender_norm or packet.get('fromId', '?')}"
            rtt_str = "?"
            target_id = sender_norm

        def node_name(num: int) -> str:
            if num == 0xFFFFFFFF or num == 0:
                return "???"
            hex_id = f"!{num:08x}"
            for nid, info in self.nodes.items():
                if _normalize_node_id(str(nid)) == hex_id and isinstance(info, dict):
                    ln = info.get("user", {}).get("longName") or info.get("user", {}).get("shortName")
                    if ln:
                        return ln
            return hex_id[-8:]

        my_name = self.my_name
        dest_name = node_name(int(packet.get("from", 0)))

        UNK_SNR = -128

        def fmt_snr(val) -> str:
            if val is None or val == UNK_SNR:
                return ""
            return f"({val}dB)"

        forward_hops = [my_name]
        for i, num in enumerate(route_back):
            snr = snr_towards[i] if i < len(snr_towards) else None
            forward_hops.append(f"{node_name(num)}{fmt_snr(snr)}")
        snr_last = snr_towards[len(route_back)] if len(route_back) < len(snr_towards) else None
        forward_hops.append(f"{dest_name}{fmt_snr(snr_last)}")

        back_hops = [dest_name]
        for i, num in enumerate(route):
            snr = snr_back[i] if i < len(snr_back) else None
            back_hops.append(f"{node_name(num)}{fmt_snr(snr)}")
        snr_back_last = snr_back[len(route)] if len(route) < len(snr_back) else None
        back_hops.append(f"{my_name}{fmt_snr(snr_back_last)}")

        self.store.add(dm_tab, "tracert", f"traceroute  rtt:{rtt_str}")
        self.store.add(dm_tab, "tracert", f"  → {' → '.join(forward_hops)}")
        self.store.add(dm_tab, "tracert", f"  ← {' ← '.join(back_hops)}")

        if self.app_dm_callback:
            self.app_dm_callback(dm_tab)
        self.on_update()
        if hasattr(self, 'app') and self.app:
            self.app.call_from_thread(self.app._refresh_log)
            self.app.call_from_thread(self.app._refresh_nodes)

    def send(self, text: str, channel: int = 0) -> Optional[int]:
        if self.iface and self.connected:
            try:
                result = self.iface.sendText(text, channelIndex=channel, wantAck=True)
                pid = _extract_packet_id(result, store=self.store)
                return pid
            except Exception as e:
                self.store.add("system", "sys", f"tx failed: {e}")
                return None
        return None

    def send_dm(self, text: str, target_id: str) -> Optional[int]:
        if self.iface and self.connected:
            try:
                destination = target_id if target_id.startswith("!") else f"!{target_id}"
                if destination.startswith("!") and len(destination) > 1:
                    try:
                        destination = int(destination[1:], 16)
                    except ValueError:
                        pass
                result = self.iface.sendText(text, destinationId=destination, wantAck=True)
                pid = _extract_packet_id(result, store=self.store)
                return pid
            except Exception as e:
                self.store.add("system", "sys", f"dm tx failed: {e}")
                return None
        return None

    def send_ping(self, target_id: str) -> Optional[int]:
        if not self.iface or not self.connected:
            return None
        try:
            from meshtastic import portnums_pb2
            destination = target_id if target_id.startswith("!") else f"!{target_id}"
            if destination.startswith("!") and len(destination) > 1:
                try:
                    destination = int(destination[1:], 16)
                except ValueError:
                    pass
            result = self.iface.sendData(
                b"ping",
                destinationId=destination,
                portNum=portnums_pb2.PortNum.REPLY_APP,
                wantAck=True,
                wantResponse=True,
            )
            pid = _extract_packet_id(result, store=self.store)
            return pid
        except Exception as e:
            self.store.add("system", "sys", f"ping tx failed: {e}")
            return None

    def send_traceroute(self, target_id: str, hop_limit: int = 7) -> Optional[int]:
        if not self.iface or not self.connected:
            return None
        try:
            from meshtastic import portnums_pb2, mesh_pb2
            destination = target_id if target_id.startswith("!") else f"!{target_id}"
            if destination.startswith("!") and len(destination) > 1:
                try:
                    destination = int(destination[1:], 16)
                except ValueError:
                    pass
            r = mesh_pb2.RouteDiscovery()
            result = self.iface.sendData(
                r,
                destinationId=destination,
                portNum=portnums_pb2.PortNum.TRACEROUTE_APP,
                wantAck=True,
                wantResponse=True,
                hopLimit=hop_limit,
            )
            pid = _extract_packet_id(result, store=self.store)
            return pid
        except Exception as e:
            self.store.add("system", "sys", f"traceroute tx failed: {e}")
            return None


# ── INITIAL INITIALIZATION MODAL SCREEN ───────────────────────────────────────

class SetupScreen(ModalScreen):
    DEFAULT_CSS = f"""
    SetupScreen {{
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }}
    #setup-dialog {{
        padding: 1 2;
        width: 60;
        height: auto;
        background: #161b22;
        border: solid {C['accent']};
    }}
    .setup-title {{
        text-align: center;
        margin-bottom: 1;
    }}
    .btn-choice {{
        width: 1fr;
        margin: 0 1;
    }}
    #conn-target-input {{
        margin: 1 0;
        background: #0d1117;
        border: solid {C['border']};
    }}
    #btn-submit {{
        width: 1fr;
    }}
    """
    def __init__(self):
        super().__init__()
        self.selected_type = "tcp"

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-dialog"):
            yield Label(f"[bold {C['accent']}]⟁ MCLI INITIALIZATION[/bold {C['accent']}]", classes="setup-title", markup=True)
            yield Label("Select Connection Interface Type:")
            with Horizontal():
                yield Button("TCP Network", id="choice-tcp", classes="btn-choice", variant="primary")
                yield Button("Serial/USB COM", id="choice-serial", classes="btn-choice")
            yield Label("\nConnection Target Destination:", id="target-label")
            yield Input(placeholder="192.168.1.9:4403", id="conn-target-input")
            yield Button("CONFIRM & SAVE SETTINGS", id="btn-submit", variant="success")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "choice-tcp":
            self.selected_type = "tcp"
            self.query_one("#choice-tcp").variant = "primary"
            self.query_one("#choice-serial").variant = "default"
            self.query_one("#conn-target-input", Input).placeholder = "192.168.1.9:4403"
        elif event.button.id == "choice-serial":
            self.selected_type = "serial"
            self.query_one("#choice-tcp").variant = "default"
            self.query_one("#choice-serial").variant = "warning"
            self.query_one("#conn-target-input", Input).placeholder = "/dev/ttyUSB0"
        elif event.button.id == "btn-submit":
            val = self.query_one("#conn-target-input", Input).value.strip()
            if not val:
                val = "192.168.1.9:4403" if self.selected_type == "tcp" else "/dev/ttyUSB0"
            self.dismiss({"type": self.selected_type, "target": val})


# ── WIDGETS ────────────────────────────────────────────────────────────────────

class NodePanel(ScrollableContainer):
    def __init__(self, mesh: MeshInterface, **kwargs):
        super().__init__(**kwargs)
        self.mesh = mesh
        self.styles.overflow_y = "scroll"

    def compose(self) -> ComposeResult:
        yield Static("  loading nodes...", id="node-loading")

    def update_nodes(self) -> None:
        self.remove_children()

        header_text = Text.from_markup(f"  ◈ NODES\n", style=f"bold {C['accent']}")
        header_text.append(f"  {'─'*18}\n", style=C["dim"])
        self.mount(Static(header_text))

        nodes = self.mesh.nodes
        if not nodes:
            self.mount(Static("  no nodes visible\n", style=C["ghost"]))
        else:
            for node_id, info in list(nodes.items()):
                str_id = str(node_id)
                if isinstance(info, dict):
                    user = info.get("user", info)
                    name = user.get("longName", str_id[-6:])
                    snr_val = info.get("snr", 0)
                    hops = info.get("hopsAway", info.get("hop", 1))
                else:
                    name, snr_val, hops = str_id[-6:], 0, 1

                col = node_color(str_id)
                short = name[:20].ljust(20)

                node_text = Text(f"  ◈ {short}\n", style=col)
                node_text.append(Text.from_markup(f"    {snr_bar(snr_val)} {hop_indicator(hops)}\n"))
                self.mount(Static(node_text))

        footer_text = Text(f"\n  {'─'*18}\n", style=C["dim"])
        footer_text.append(f"  total: {len(nodes)}\n", style=C["ghost"])
        footer_text.append(f"  self: {self.mesh.my_name[:14]}\n", style=f"{C['accent']}")
        self.mount(Static(footer_text))


import math

class RadarWidget(Static):
    
    
    DEFAULT_CSS = """
    RadarWidget {
        width: 1fr;
        height: 1fr;
        background: #0d1117;
        padding: 0;
        margin: 0;
        border: none;
        display: none;
    }
    """
    
    MYCITY_LAT = 57.0004
    MYCITY_LON = 40.9739
    
    def __init__(self, mesh: MeshInterface, **kwargs):
        super().__init__(**kwargs)
        self.mesh = mesh
        self.zoom = 2000.0
        self.width_chars = 76
        self.height_chars = 28
        self.pan_x = 0.0  # смещение центра по долготе (в метрах)
        self.pan_y = 0.0  # смещение центра по широте (в метрах)

    def on_mount(self):
        self.set_interval(2.0, self.update_radar)
    
    def on_resize(self, event) -> None:
        if self.display:
            self.update_radar()
        
    def action_zoom_in(self):
        self.zoom = max(100, self.zoom / 1.5)
        self.update_radar()
        
    def action_zoom_out(self):
        self.zoom = min(100000, self.zoom * 1.5)
        self.update_radar()

    def action_pan_up(self):
        self.pan_y += self.zoom * 0.3
        self.update_radar()

    def action_pan_down(self):
        self.pan_y -= self.zoom * 0.3
        self.update_radar()

    def action_pan_left(self):
        self.pan_x -= self.zoom * 0.3
        self.update_radar()

    def action_pan_right(self):
        self.pan_x += self.zoom * 0.3
        self.update_radar()

    def action_pan_reset(self):
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update_radar()
        
    def update_radar(self):
        my_pos = self._get_center_position()
        nodes_with_pos = []
        
        for nid, info in self.mesh.nodes.items():
            if str(nid) == str(self.mesh.my_id):
                continue
            pos = self._extract_position(info)
            if not pos:
                continue
            dist = self._haversine(my_pos[0], my_pos[1], pos[0], pos[1])
            snr = None
            name = ""
            if isinstance(info, dict):
                user = info.get("user", {})
                name = (user.get("shortName") or user.get("longName", ""))[:5]
            nodes_with_pos.append((nid, pos[0], pos[1], name))
            
        nodes_with_pos.sort(key=lambda x: x[3], reverse=True)
        
        size = self.size
        w = max(size.width - 2, 20) if size.width > 10 else self.width_chars
        h = max(size.height - 2, 10) if size.height > 6 else self.height_chars
        
        canvas = [[" " for _ in range(w)] for _ in range(h)]
        cx, cy = w // 2, h // 2
        
        for x in range(0, w, 8):
            for y in range(h):
                canvas[y][x] = f"[{C['dim']}]·[/]"
        for y in range(0, h, 5):
            for x in range(w):
                if canvas[y][x] == " ":
                    canvas[y][x] = f"[{C['dim']}]·[/]"
                    
        canvas[cy][cx] = f"[bold {C['accent']}]◉[/]"
        
        placed_rects = [(cx - 1, cy - 1, cx + 2, cy + 2)]
        cos_lat = math.cos(math.radians(my_pos[0]))
        
        for nid, lat, lon, name in nodes_with_pos:
            d_lat = (lat - my_pos[0]) * 111_000 - self.pan_y
            d_lon = (lon - my_pos[1]) * 111_000 * cos_lat - self.pan_x
        
            scale = min(w / 2, h / 2)
            px = int(cx + (d_lon / self.zoom) * scale)
            py = int(cy - (d_lat / self.zoom) * scale)
            
            if not (0 <= px < w and 0 <= py < h):
                continue
                
            col = node_color(str(nid))
            canvas[py][px] = f"[{col}]●[/]"
            
            snr_str = f"{snr:.0f}dB" if snr is not None else "?dB"
            label =  f"{markup_escape(name)}"
            
            best_pos = None
            offsets = [
                (2, 0), (-len(label) - 1, 0),
                (2, -1), (-len(label) - 1, -1),
                (2, 1), (-len(label) - 1, 1),
            ]
            for dx, dy in offsets:
                lx, ly = px + dx, py + dy
                if 0 <= lx <= w - len(label) and 0 <= ly < h:
                    rect = (lx, ly, lx + len(label), ly + 1)
                    overlap = any(
                        not (rect[2] < r[0] or rect[0] > r[2] or
                             rect[3] < r[1] or rect[1] > r[3])
                        for r in placed_rects
                    )
                    if not overlap:
                        best_pos = (lx, ly)
                        placed_rects.append(rect)
                        break
                        
            if best_pos:
                lx, ly = best_pos
                for i, ch in enumerate(label):
                    if 0 <= lx + i < w:
                        canvas[ly][lx + i] = f"[dim {col}]{ch}[/]"
                        
        lines = ["".join(row) for row in canvas]
        mode = "[NOGPS: IVANOVO]" if not self._has_real_gps() else "[GPS LIVE]"
        pan_info = f" pan:{self.pan_x/1000:.1f}km,{self.pan_y/1000:.1f}km" if (self.pan_x or self.pan_y) else ""
        header = f"[bold {C['accent2']}]⟁ RADAR[/] zoom:{self.zoom:.0f}m{pan_info} | [Ctrl+U/O] zoom | [Ctrl+↑↓←→] pan | {mode}"
        footer = f"[{C['ghost']}]Nodes w/GPS: {len(nodes_with_pos)} | Center: YOU[/]"
        
        self.update(f"{header}\n" + "\n".join(lines) + f"\n{footer}")
        
    def _get_center_position(self):
        real = self._get_my_real_position()
        if real:
            return real
        return (self.MYCITY_LAT, self.MYCITY_LON)
        
    def _has_real_gps(self):
        return self._get_my_real_position() is not None
        
    def _get_my_real_position(self):
        if not self.mesh.iface:
            return None
        try:
            my_num = self.mesh.iface.myInfo.myNodeNum
            if hasattr(self.mesh.iface, 'nodes') and my_num in self.mesh.iface.nodes:
                return self._extract_position(self.mesh.iface.nodes[my_num])
        except Exception:
            pass
        return None
        
    def _extract_position(self, info):
        if not isinstance(info, dict):
            return None
        pos = info.get("position", {})
        lat = pos.get("latitude") if pos.get("latitude") is not None else pos.get("latitudeI")
        lon = pos.get("longitude") if pos.get("longitude") is not None else pos.get("longitudeI")
        if lat is not None and lon is not None:
            if abs(lat) > 180:
                lat, lon = lat * 1e-7, lon * 1e-7
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
        return None
        
    def _haversine(self, lat1, lon1, lat2, lon2):
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ── MAIN APPLICATION ──────────────────────────────────────────────────────────

class MeshApp(App):
    CSS = f"""
    #header {{ 
        background: #161b22; 
        color: #e2e8f0; 
        height: 2; 
        padding: 0 1; 
        border-bottom: solid #4a5568;
    }}
    Screen {{ background: #0d1117; }}
    #main {{ height: 1fr; }}
    #chat-col {{ width: 1fr; border-right: solid {C['border']}; }}
    #log {{ height: 1fr; background: #0d1117; padding: 0 1; scrollbar-color: {C['dim']}; scrollbar-size: 1 1; }}
    #node-col {{ width: 26; background: #0d1117; scrollbar-color: #3d4451; scrollbar-size: 1 1; }}
    #input-row {{ height: 3; border-top: solid {C['border']}; background: #0d1117; padding: 0 1; }}
    #prompt {{ color: {C['accent']}; width: 10; padding: 1 0; text-style: bold; }}
    Input {{ background: #0d1117; border: none; color: {C['text']}; height: 3; padding: 1 0; }}
    Input:focus {{ border: none; }}
    #statusbar {{ height: 1; background: #161b22; color: {C['ghost']}; padding: 0 1; }}
    #channel-bar {{ height: 1; background: #161b22; padding: 0 1; }}
    #radar-view {{ width: 1fr; height: 1fr; display: none; }}
    """

    BINDINGS = [
        Binding("ctrl+c", "quit",         "quit",       show=True),
        Binding("ctrl+n", "next_channel", "next ch",    show=True),
        Binding("ctrl+p", "main_menu",    "main menu",  show=True),
        Binding("ctrl+x", "close_channel","close DM",   show=True),
        Binding("ctrl+l", "clear_log",    "clear",      show=True),
        Binding("ctrl+d", "toggle_nodes", "nodes",      show=True),
        Binding("ctrl+u", "radar_zoom_in",  "map+", show=False),
        Binding("ctrl+o", "radar_zoom_out", "map-", show=False),
        Binding("ctrl+up",    "radar_pan_up",    "map↑", show=False),
        Binding("ctrl+down",  "radar_pan_down",  "map↓", show=False),
        Binding("ctrl+left",  "radar_pan_left",  "map←", show=False),
        Binding("ctrl+right", "radar_pan_right", "map→", show=False),
        Binding("f1",     "show_help",    "help",       show=True),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = MessageStore()
        self.mesh = MeshInterface(self.store, self._schedule_update)
        self.mesh.app = self
        self.mesh.app_channels_callback = self._register_channel_from_mesh
        self.mesh.app_dm_callback = self._register_dm_tab

        self.channels = ["primary", "system", "map", "debug"]
        self.ch_index = 0
        self._nodes_visible = True
        self._update_pending = False
        self._favorites: dict[str, str] = db.get_favorites()

    @property
    def current_channel(self) -> str:
        return self.channels[self.ch_index]

    def _register_channel_from_mesh(self, name: str):
        if name not in self.channels:
            idx = self.channels.index("system")
            self.channels.insert(idx, name)
            self.store.load_history(name)
            try:
                self._refresh_channel_bar()
            except RuntimeError:
                self.call_from_thread(self._refresh_channel_bar)

    def _register_dm_tab(self, tab_name: str):
        if tab_name not in self.channels:
            idx = self.channels.index("system")
            self.channels.insert(idx, tab_name)
            self.store.load_history(tab_name)
            try:
                self._refresh_channel_bar()
            except RuntimeError:
                self.call_from_thread(self._refresh_channel_bar)

    def _schedule_update(self):
        self._update_pending = True

    def compose(self) -> ComposeResult:
        yield Static(self._header_art(), id="header")
        yield Static("", id="channel-bar")
        with Horizontal(id="main"):
            with Vertical(id="chat-col"):
                yield RichLog(id="log", wrap=True, highlight=False, markup=True)
                with Horizontal(id="input-row"):
                    yield Static(f"[{C['accent']}]mesh ›[/] ", id="prompt", markup=True)
                    yield Input(placeholder="type msg, :dm <name/id> or :help", id="msg-input")
            yield RadarWidget(self.mesh, id="radar-view")   
            yield NodePanel(self.mesh, id="node-col")
        yield Static("", id="statusbar")

    
    def _header_art(self) -> str:
        logo = f"[bold {C['hi']}]▰▰ meshtastic cli client[/bold {C['hi']}]"
        mode = f"[{C['accent']}]⟁ AUTONOMOUS MODE[/{C['accent']}]"
        manifest = f"[{C['ghost']}]{random.choice(MANIFESTS)}[/{C['ghost']}]"
        return f" {logo} │ {mode} ── {manifest}"

    def on_mount(self):
        self._refresh_channel_bar()
        self._refresh_log()
        self._refresh_status()
        self._refresh_nodes()

        for ch in self.channels:
            if ch not in ("system", "debug"):
                self.store.load_history(ch)
        self._refresh_log()

        conn_type = db.get_setting("conn_type")
        conn_target = db.get_setting("conn_target")

        if not conn_type or not conn_target:
            self.push_screen(SetupScreen(), self.handle_setup_result)
        else:
            self._connect_to_mesh(conn_type, conn_target)

        self.set_interval(0.5, self._refresh_status)
        self.set_interval(0.2, self._poll_updates)
        self.query_one("#msg-input", Input).focus()
        self._update_chat_view()

    def handle_setup_result(self, result: dict):
        if not result:
            return
        db.set_setting("conn_type", result["type"])
        db.set_setting("conn_target", result["target"])
        self._connect_to_mesh(result["type"], result["target"])

    def _connect_to_mesh(self, conn_type: str, conn_target: str):
        if conn_type == "serial":
            self.store.add("system", "sys", f"Auto-connecting to Serial: {conn_target}...")
            try:
                self.mesh.connect_serial(conn_target)
            except Exception as e:
                self.store.add("system", "sys", f"[red]❌ Serial connection failed: {e}[/red]")
        
        elif conn_type == "tcp":
            if ":" in conn_target:
                host, port_str = conn_target.split(":", 1)
                try: port = int(port_str)
                except ValueError: port = 4403
            else:
                host = conn_target
                port = 4403

            self.store.add("system", "sys", f"Auto-connecting to TCP: {host}:{port}...")
            self._refresh_log()

            try:
                time.sleep(0.5) 
                if self.mesh.connect_tcp(host, port):
                    self.store.add("system", "sys", "[green]✓ Connected to Meshtastic via TCP![/green]")
                else:
                    self.store.add("system", "sys", "[red]❌ Meshtastic connect failed[/red]")
                    self.store.add("system", "sys", "[#38bdf8]Use :tcp <ip> to retry or check your node connection.[/#38bdf8]")
            except Exception as e:
                self.store.add("system", "sys", f"[red]❌ Meshtastic init error: {e}[/red]")
                if hasattr(self.mesh, 'iface'):
                    self.mesh.iface = None
                if "system" in self.channels:
                    self.ch_index = self.channels.index("system")

            self.query_one("#log", RichLog).clear()
            self._refresh_log()

    def _poll_updates(self):
        if self._update_pending:
            self._update_pending = False
            self._refresh_log()
            self._refresh_status()
            self._refresh_nodes()

    def _write_msg(self, log: RichLog, m: dict):
        if m.get("raw_debug"):
            t = Text.from_markup(f"[{C['ghost']}]{m['ts']}[/{C['ghost']}] {m['text']}\n{'-'*40}")
            log.write(t)
            return

        t = Text()
        t.append(f" {m['ts']} ", style=C["ghost"])

        if m["sender"] == "sys":
            t.append("◈ ", style=C["warn"])
            t.append(m["text"], style=C["warn"])
            log.write(t)
            return

        sender_str = str(m["sender"])
        if sender_str == str(self.mesh.my_id):
            name = self.mesh.my_name[:20]
            t.append(f"▸ {name:<21}", style=f"bold {C['accent']}")
        else:
            node_info = self.mesh.nodes.get(m["sender"])
            if not node_info and sender_str.isdigit():
                node_info = self.mesh.nodes.get(int(m["sender"]))

            display_sender = sender_str
            if isinstance(node_info, dict):
                display_sender = node_info.get("user", {}).get("longName", sender_str[-6:])
            elif sender_str.startswith("!"):
                display_sender = sender_str[-6:]

            col = node_color(sender_str)
            t.append(f"  {display_sender[:20]:<21}", style=col)

        t.append(m["text"], style=C["text"])

        meta_parts = []
        if m.get("rssi") is not None:
            meta_parts.append(f"rssi:{m['rssi']}")
        if m.get("snr") is not None:
            meta_parts.append(f"snr:{m['snr']:.1f}")
        if m.get("hops") is not None:
            h = m["hops"]
            hop_str = "◉direct" if h == 0 else f"⬡×{h}"
            meta_parts.append(hop_str)
        if meta_parts:
            t.append(f"  [{' '.join(meta_parts)}]", style=C["dim"])

        if m.get("is_own"):
            ack = m.get("ack")
            detail = m.get("ack_detail", "")
            if ack is None:
                t.append("  [?]", style=C["ghost"])
            elif ack == "ack":
                t.append("  [✓]", style=C["accent"])
            elif ack == "relay":
                t.append("  [~]", style=C["accent2"])
            elif ack == "nack":
                label = f"✗ {detail}" if detail else "✗"
                t.append(f"  [{label}]", style=C["danger"])

        log.write(t)

    def _force_refresh_log(self):
        try:
            log = self.query_one("#log", RichLog)
            log.clear()
            for m in self.store.get(self.current_channel):
                self._write_msg(log, m)
            self.store.mark_read(self.current_channel)
            self._refresh_channel_bar()
        except Exception:
            pass

    def _refresh_log(self, force: bool = False):
        log = self.query_one("#log", RichLog)
        msgs = self.store.get(self.current_channel)
        self.store.mark_read(self.current_channel)
        self._refresh_channel_bar()

        lines_count = len(log.lines)

        if not msgs:
            log.clear()
            log.write(Text(f"  — channel #{self.current_channel} is empty —", style=C["ghost"]))
            return

        if force or lines_count <= 1:
            log.clear()
            for m in msgs:
                self._write_msg(log, m)
            return

        last_msg_changed = False
        if msgs and lines_count > 0:
            if msgs[-1].get("is_own"):
                last_msg_changed = True

        if last_msg_changed:
            log.clear()
            for m in msgs:
                self._write_msg(log, m)
        else:
            delta = len(msgs) - lines_count
            if delta > 0:
                for m in msgs[-delta:]:
                    self._write_msg(log, m)
	
    def _refresh_channel_bar(self):
        bar = self.query_one("#channel-bar", Static)
        parts = []
        for i, ch in enumerate(self.channels):
            unread = self.store.unread.get(ch, 0)
            display_name = ch
            if ch.startswith("▶"):
                raw_id = ch[1:]
                node_info = self.mesh.nodes.get(raw_id) or self.mesh.nodes.get(int(raw_id) if raw_id.isdigit() else 0)
                if isinstance(node_info, dict):
                    display_name = f"▶{node_info.get('user', {}).get('longName', raw_id[-6:])}"
                else:
                    display_name = f"▶{raw_id[-6:]}"

            if i == self.ch_index:
                badge = f"[bold {C['accent']}] #{display_name} [/bold {C['accent']}]"
            else:
                badge = f"[{C['ghost']}] #{display_name} [/{C['ghost']}]"
            if unread > 0 and ch != "debug":
                badge += f"[{C['danger']}]{unread}[/{C['danger']}]"
            parts.append(badge)
        bar.update(" ".join(parts))

        def _update_chat_view(self):
            try:
                log = self.query_one("#log", RichLog)
                radar = self.query_one("#radar-view", RadarWidget)
                input_row = self.query_one("#input-row")
                if self.current_channel == "map":
                    log.display = False
                    input_row.display = False
                    radar.display = True                   
                    radar.refresh()
                    radar.update_radar()
                else:
                    log.display = True
                    input_row.display = True
                    radar.display = False
            except Exception:
                pass


    def action_radar_zoom_in(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_zoom_in()
        except Exception:
            pass

    def action_radar_zoom_out(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_zoom_out()
        except Exception:
            pass

    def _refresh_nodes(self):
        try:
            panel = self.query_one("#node-col")
        except Exception:
            return

        nodes_widget = None
        for widget_type in ["RichLog", "TextLog", "Static", "Label"]:
            try:
                from textual.widgets import RichLog, Static, Label
                target_class = locals().get(widget_type)
                if target_class:
                    nodes_widget = panel.query_one(target_class)
                    break
            except Exception:
                continue

        if not nodes_widget:
            nodes_widget = panel

        try:
            if hasattr(nodes_widget, "clear"):
                nodes_widget.clear()

            write_func = getattr(nodes_widget, "write", getattr(nodes_widget, "update", None))
            if not write_func:
                return

            lines = [f"[bold #38bdf8]📡 KNOWN NODES:[/bold #38bdf8]"]

            if not hasattr(self, 'mesh') or not self.mesh or not getattr(self.mesh, 'iface', None):
                lines.append("  [gray]No mesh interface...[/gray]")
                write_func("\n".join(lines))
                return

            nodes_dict = self.mesh.nodes

            if not nodes_dict:
                lines.append("  [gray]No active nodes...[/gray]")
                write_func("\n".join(lines))
                return

            output = Text.from_markup("\n".join(lines) + "\n")

            for nid, info in sorted(nodes_dict.items(), key=lambda x: (x[1].get("user", {}).get("longName") or x[1].get("user", {}).get("shortName") or "").lower() if isinstance(x[1], dict) else ""):
                if isinstance(info, dict):
                    user_info = info.get("user", {})
                    name = user_info.get("longName") or user_info.get("shortName") or f"!{nid:08x}"
                    snr = info.get("snr", 0.0)
                    line = Text()
                    line.append(" ", style="bold #e2e8f0")
                    line.append(name, style="bold #e2e8f0")
                    line.append(f" ({snr}dB)\n", style="#808080")
                    output.append_text(line)

            write_func(output)

        except Exception as final_err:
            self.store.add("system", "debug", f"Render error: {final_err}")

    def action_open_dm(self, node_id: str) -> None:
        target_id = str(node_id)
        node_info = self.mesh.nodes.get(int(target_id) if target_id.isdigit() else target_id, {})
        name = target_id
        if isinstance(node_info, dict):
            name = node_info.get("user", {}).get("longName") or target_id

        dm_tab = f"▶{target_id}"
        self._register_dm_tab(dm_tab)
        if dm_tab in self.channels:
            self.ch_index = self.channels.index(dm_tab)

        self.query_one("#log", RichLog).clear()
        self._refresh_log()
        self.store.add("system", "sys", f"[*] Opened private chat with {name} ({target_id})")
        self._refresh_log()

    def _refresh_status(self):
        try:
            statusbar = self.query_one("#statusbar")
        except Exception:
            return

        now = datetime.now(MOSCOW_TZ)
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%d.%m.%y")

        my_hex_id = "!local"
        long_name = "Operator"

        if hasattr(self, 'mesh') and self.mesh:
            nid = self.mesh.my_id
            try:
                if isinstance(nid, int): my_hex_id = f"!{nid:08x}"
                elif isinstance(nid, str) and nid.isdigit(): my_hex_id = f"!{int(nid):08x}"
                else: my_hex_id = str(nid)
            except Exception:
                my_hex_id = str(self.mesh.my_id)

            if hasattr(self.mesh, 'iface') and self.mesh.iface and getattr(self.mesh.iface, 'myInfo', None):
                try:
                    my_node_num = self.mesh.iface.myInfo.myNodeNum
                    if hasattr(self.mesh.iface, 'nodes') and my_node_num in self.mesh.iface.nodes:
                        my_details = self.mesh.iface.nodes[my_node_num]
                        user_info = my_details.get("user", {})
                        long_name = user_info.get("longName", long_name)
                except Exception:
                    long_name = getattr(self.mesh, 'my_name', long_name)

        status_text = (
            f"[bold #38bdf8]MYID:[/bold #38bdf8] {my_hex_id}  "
            f"[bold #e2e8f0]MYNAME:[/bold #e2e8f0] {long_name}  |  "
            f"[bold #ae7cff]{date_str} {time_str} (MSK)[/bold #ae7cff]"
        )

        if hasattr(statusbar, "update"): statusbar.update(status_text)

    def _close_current_dm(self):
        target_ch = self.current_channel
        if not target_ch.startswith("▶"):
            self.store.add("system", "sys", "Error: You can only close private DM tabs.")
            self._refresh_log()
            return

        self.store.drop_channel(target_ch)
        self.channels.remove(target_ch)

        self.ch_index = max(0, self.ch_index - 1)
        self.query_one("#log", RichLog).clear()
        self._refresh_log()
        self._refresh_channel_bar()

    def _run_node_clean(self, days: int):
        if not self.mesh.iface or not hasattr(self.mesh.iface, "nodes"):
            self.store.add("system", "sys", "Ошибка: устройство не подключено.")
            return

        local_node = getattr(self.mesh.iface, "localNode", None)
        if local_node is None:
            self.store.add("system", "sys", "Ошибка: localNode недоступен.")
            return

        current_time = time.time()
        max_age_seconds = days * 86400
        removed_count = 0
        failed_count = 0

        node_ids = list(self.mesh.iface.nodes.keys())

        for node_id in node_ids:
            if str(node_id) == str(self.mesh.my_id):
                continue
            if str(node_id) in self._favorites:
                continue

            node_data = self.mesh.iface.nodes[node_id]
            if not isinstance(node_data, dict):
                continue

            last_heard = node_data.get("lastHeard", 0)
            if last_heard <= 0 or (current_time - last_heard) <= max_age_seconds:
                continue

            node_num = node_data.get("num")
            if node_num is None:
                try:
                    str_id = str(node_id)
                    node_num = int(str_id.lstrip("!"), 16)
                except (ValueError, AttributeError):
                    self.store.add("system", "sys", f"  ✗ не удалось определить nodeNum для {node_id}")
                    failed_count += 1
                    continue

            try:
                local_node.removeNode(node_num)
                self.store.add("system", "sys", f"  → removeNode({node_num}) sent for {node_id}")
                self.mesh._excluded_nodes.add(str(node_id))
                if node_id in self.mesh.iface.nodes:
                    del self.mesh.iface.nodes[node_id]
                removed_count += 1
            except Exception as e:
                self.store.add("system", "sys", f"  ✗ ошибка удаления {node_id}: {e}")
                failed_count += 1

        self.mesh._refresh_nodes()
        self._refresh_nodes()

        msg = f"✓ Очистка завершена. Удалено нод (молчали > {days} дн.): {removed_count}"
        if failed_count:
            msg += f"  |  ошибок: {failed_count}"
        self.store.add("system", "sys", msg)

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text: return
        event.input.value = ""

        if text.startswith(":"):
            self._handle_command(text[1:])
        else:
            self._send_message(text)

    def _send_message(self, text: str):
        if self.current_channel in ("system", "debug"):
            self.store.add("system", "sys", f"Error: Cannot send messages in #{self.current_channel} channel.")
            self._refresh_log(force=True)
            return

        if self.current_channel.startswith("▶"):
            target_id = self.current_channel[1:]
            pid = self.mesh.send_dm(text, target_id)
            if pid is not None:
                entry = self.store.add(self.current_channel, self.mesh.my_id, text, is_own=True, packet_id=pid)
                self.store._apply_late_ack(pid, entry)
            else:
                self.store.add(self.current_channel, "sys", "DM sending failed.")
            self._refresh_log(force=True)
            return

        ch_index = 0
        for idx, name in self.mesh.channel_names.items():
            if name == self.current_channel:
                ch_index = idx
                break

        pid = self.mesh.send(text, channel=ch_index)
        if pid is not None:
            entry = self.store.add(self.current_channel, self.mesh.my_id, text, is_own=True, packet_id=pid)
            self.store._apply_late_ack(pid, entry)
        else:
            db.save_message(self.current_channel, "sys", "Message sending failed.", False, None, None, None)
            self.store.add(self.current_channel, "sys", "Message sending failed.")
        self._refresh_log()

    def _handle_command(self, cmd: str):
        parts = cmd.strip().split(None, 2)
        verb = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        if verb in ("q", "quit", "exit"):
            self.exit()

        elif verb in ("close", "x"):
            self._close_current_dm()

        elif verb == "nodeclean" and args:
            try:
                days = int(args[0])
                self._run_node_clean(days)
            except ValueError:
                self.store.add("system", "sys", "Ошибка: укажите количество дней числом. Пример: :nodeclean 7")
            self._refresh_log()

        elif verb == "serial" and args:
            port = args[0]
            self.store.add("system", "sys", f"connecting serial {port}…")
            ok = self.mesh.connect_serial(port)
            if ok:
                db.set_setting("conn_type", "serial")
                db.set_setting("conn_target", port)
                self.store.add("system", "sys", "serial link established and saved as default")
            else:
                self.store.add("system", "sys", "serial failed")
            self._refresh_log()

        elif verb == "tcp" and args:
            host = args[0]
            try:
                port = int(args[1]) if len(args) > 1 else 4403
            except ValueError:
                self.store.add("system", "sys", "Ошибка: неверный порт.")
                self._refresh_log()
                return

            self.store.add("system", "sys", f"connecting tcp {host}:{port}…")
            ok = self.mesh.connect_tcp(host, port)
            if ok:
                db.set_setting("conn_type", "tcp")
                db.set_setting("conn_target", f"{host}:{port}")
                self.store.add("system", "sys", "tcp link established and saved as default")
            else:
                self.store.add("system", "sys", "tcp failed")
            self._refresh_log()

        elif verb == "ch" and args:
            ch = args[0].lstrip("#").lower()
            if ch not in self.channels:
                idx = self.channels.index("system")
                self.channels.insert(idx, ch)
                self.store.load_history(ch)
            self.ch_index = self.channels.index(ch)
            self.store.add("system", "sys", f"switched to #{ch}")
            self.query_one("#log", RichLog).clear()
            self._refresh_log()
            self._refresh_channel_bar()

        elif verb == "nodes":
            self.store.add("system", "sys", "=== node table ===")
            self._node_index_map = {}
            now = time.time()

            sorted_nodes = sorted(
                [(nid, info) for nid, info in self.mesh.nodes.items() if isinstance(info, dict)],
                key=lambda x: x[1].get("lastHeard", 0)
            )

            total = len(sorted_nodes)
            for idx_offset, (nid, info) in enumerate(sorted_nodes):
                idx = total - idx_offset
                str_nid = str(nid)
                u = info.get("user", info)
                name = u.get("longName", str_nid[-6:])
                hw_model = u.get("hwModel", "?")
                role = u.get("role", "?")

                snr_val = info.get("snr", "?")
                hops = info.get("hopsAway", "?")

                pos = info.get("position", {})
                lat = pos.get("latitude") or pos.get("latitudeI")
                lon = pos.get("longitude") or pos.get("longitudeI")
                if lat and lon:
                    if abs(lat) > 180:
                        lat = lat * 1e-7
                        lon = lon * 1e-7
                    pos_str = f"{lat:.4f},{lon:.4f}"
                else:
                    pos_str = "no gps"

                last_heard = info.get("lastHeard", 0)
                if last_heard and last_heard > 0:
                    age_sec = int(now - last_heard)
                    if age_sec < 60:
                        heard_str = f"{age_sec}s ago"
                    elif age_sec < 3600:
                        heard_str = f"{age_sec // 60}m ago"
                    elif age_sec < 86400:
                        heard_str = f"{age_sec // 3600}h ago"
                    else:
                        heard_str = f"{age_sec // 86400}d ago"
                else:
                    heard_str = "never"

                self._node_index_map[str(idx)] = str_nid
                self.store.add(
                    "system", "sys",
                    f" [{idx}] {name:<20} id:{str_nid[-8:]}"
                    f"  snr:{snr_val}  hops:{hops}"
                    f"  hw:{hw_model}  role:{role}"
                    f"  pos:{pos_str}  heard:{heard_str}"
                )

            self.ch_index = self.channels.index("system")
            self.query_one("#log", RichLog).clear()
            self._refresh_log()

        elif verb == "addfav" and args:
            target = args[0].strip()
            resolved_id = None
            label = "?"

            if hasattr(self, "_node_index_map") and target in self._node_index_map:
                resolved_id = self._node_index_map[target]

            if not resolved_id:
                for nid, info in self.mesh.nodes.items():
                    str_nid = str(nid)
                    if target.lstrip("!") in str_nid.lstrip("!"):
                        resolved_id = str_nid
                        break

            if not resolved_id:
                for nid, info in self.mesh.nodes.items():
                    if isinstance(info, dict):
                        ln = info.get("user", {}).get("longName", "")
                        if ln.lower() == target.lower():
                            resolved_id = str(nid)
                            break

            if not resolved_id:
                self.store.add("system", "sys", f"✗ addfav: нода не найдена: {target}")
                self._refresh_log()
                return

            node_info = self.mesh.nodes.get(resolved_id, {})
            if isinstance(node_info, dict):
                label = node_info.get("user", {}).get("longName", resolved_id)

            self._favorites[resolved_id] = label
            db.add_favorite(resolved_id, label)
            self.store.add("system", "sys", f"★ Добавлено в избранное: {label} ({resolved_id})")
            self._refresh_log()

        elif verb == "delfav" and args:
            target = args[0].strip()

            found_id = None
            for fid, flabel in self._favorites.items():
                if target.lstrip("!") in fid.lstrip("!") or target.lower() == flabel.lower():
                    found_id = fid
                    break
            if not found_id:
                self.store.add("system", "sys", f"✗ delfav: не найдено в избранном: {target}")
            else:
                label = self._favorites.pop(found_id)
                db.remove_favorite(found_id)
                self.store.add("system", "sys", f"✩ Удалено из избранного: {label} ({found_id})")
            self._refresh_log()

        elif verb == "favs":
            favs = self._favorites
            if not favs:
                self.store.add("system", "sys", "★ Избранных нод нет.")
            else:
                self.store.add("system", "sys", f"★ Избранные ноды ({len(favs)}):")
                for fid, flabel in favs.items():
                    self.store.add("system", "sys", f"   {flabel:<20} {fid}")
            self.ch_index = self.channels.index("system")
            self.query_one("#log", RichLog).clear()
            self._refresh_log()

        elif verb == "ping" and args:
            target = " ".join(args).strip() if isinstance(args, list) else str(args).strip()
            if not target:
                self.store.add("system", "sys", "Usage: :ping <name/node_id/index>")
                self._refresh_log()
                return

            resolved_id = None

            if hasattr(self, '_node_index_map') and target in self._node_index_map:
                resolved_id = _normalize_node_id(self._node_index_map[target])

            if not resolved_id:
                for nid, info in self.mesh.nodes.items():
                    if isinstance(info, dict):
                        ln = info.get("user", {}).get("longName", "")
                        sn = info.get("user", {}).get("shortName", "")
                        if ln.lower() == target.lower() or sn.lower() == target.lower():
                            resolved_id = _normalize_node_id(str(nid))
                            break

            if not resolved_id:
                resolved_id = _normalize_node_id(target) if target else target

            dm_tab = f"▶{resolved_id}"
            self._register_dm_tab(dm_tab)
            self.ch_index = self.channels.index(dm_tab)
            self.query_one("#log", RichLog).clear()
            self._refresh_log()

            display_name = resolved_id
            for nid, info in self.mesh.nodes.items():
                if _normalize_node_id(str(nid)) == resolved_id and isinstance(info, dict):
                    display_name = info.get("user", {}).get("longName", resolved_id)
                    break

            self.store.add(dm_tab, "ping", f"PING → {display_name}  waiting…")
            self._refresh_log()

            pid = self.mesh.send_ping(resolved_id)
            if pid is not None:
                self.mesh._ping_sessions[pid] = (resolved_id, time.time(), dm_tab)
                self.store.add(dm_tab, "ping", f"sent  packet_id={pid}")
            else:
                self.store.add(dm_tab, "ping", "✗ ping send failed (not connected?)")
            self._refresh_log()

        # ── TRACEROUTE COMMAND ──
        elif verb in ("tracert", "traceroute") and args:
            target = " ".join(args).strip() if isinstance(args, list) else str(args).strip()
            if not target:
                self.store.add("system", "sys", "Usage: :tracert <name/node_id/index>")
                self._refresh_log()
                return

            resolved_id = None

            if hasattr(self, '_node_index_map') and target in self._node_index_map:
                resolved_id = _normalize_node_id(self._node_index_map[target])

            if not resolved_id:
                for nid, info in self.mesh.nodes.items():
                    if isinstance(info, dict):
                        ln = info.get("user", {}).get("longName", "")
                        sn = info.get("user", {}).get("shortName", "")
                        if ln.lower() == target.lower() or sn.lower() == target.lower():
                            resolved_id = _normalize_node_id(str(nid))
                            break

            if not resolved_id:
                resolved_id = _normalize_node_id(target) if target else target

            dm_tab = f"▶{resolved_id}"
            self._register_dm_tab(dm_tab)
            self.ch_index = self.channels.index(dm_tab)
            self.query_one("#log", RichLog).clear()
            self._refresh_log()

            display_name = resolved_id
            for nid, info in self.mesh.nodes.items():
                if _normalize_node_id(str(nid)) == resolved_id and isinstance(info, dict):
                    display_name = info.get("user", {}).get("longName", resolved_id)
                    break

            self.store.add(dm_tab, "tracert", f"TRACEROUTE → {display_name}  waiting…")
            self._refresh_log()

            pid = self.mesh.send_traceroute(resolved_id)
            if pid is not None:
                self.mesh._traceroute_sessions[pid] = (resolved_id, time.time(), dm_tab)
                self.store.add(dm_tab, "tracert", f"sent  packet_id={pid}")
            else:
                self.store.add(dm_tab, "tracert", "✗ traceroute send failed (not connected?)")
            self._refresh_log()

        # ── DM COMMAND ──
        elif verb == "dm" and args:
            target = " ".join(args).strip() if isinstance(args, list) else str(args).strip()
            if not target:
                self.store.add("system", "sys", "Usage: :dm <name/node_id/index>")
                self._refresh_log()
                return

            resolved_id = None
            if hasattr(self, '_node_index_map') and target in self._node_index_map:
                resolved_id = _normalize_node_id(self._node_index_map[target])

            if not resolved_id:
                for nid, info in self.mesh.nodes.items():
                    if isinstance(info, dict):
                        current_long_name = info.get("user", {}).get("longName", "")
                        current_short_name = info.get("user", {}).get("shortName", "")
                        if current_long_name.lower() == target.lower() or current_short_name.lower() == target.lower():
                            resolved_id = _normalize_node_id(str(nid))
                            break

            if not resolved_id: 
                resolved_id = _normalize_node_id(target) if target else target

            dm_tab = f"▶{resolved_id}"
            self._register_dm_tab(dm_tab)

            if dm_tab in self.channels:
                self.ch_index = self.channels.index(dm_tab)
            else:
                self.store.add("system", "sys", f"Error: failed to switch to {dm_tab}")

            self.query_one("#log", RichLog).clear()
            self._refresh_log()

        elif verb == "clear":
            self.store.channels[self.current_channel].clear()
            self.query_one("#log", RichLog).clear()
            self._refresh_log()

        elif verb in ("help", "?"):
            self._show_help_in_log()
        else:
            self.store.add("system", "sys", f"unknown command: :{verb} — type :help")
            self._refresh_log()

        self._refresh_nodes()

    def _show_help_in_log(self):
        self.ch_index = self.channels.index("system")
        cmds = [
            (":dm <name/id> ",   "create direct chat with node"),
            (":tracert <name/id>", "start traceroute to node"),
            (":ping <name/id/idx>", "ping node via REPLY_APP (no chat message)"),
            (":close / :x",      "close current private DM tab"),
            (":nodeclean <days>","clean old nodes manually (e.g. :nodeclean 7)"),
            (":serial /dev/ttyUSB0",  "connect and save default Serial target"),
            (":tcp 192.168.1.1", "connect and save default TCP target"),
            (":ch <name>",       "switch channel"),
            (":nodes",           "list all active mesh nodes details"),
            (":clear",           "clear current log window"),
            (":help",            "this message"),
            (":addfav <name/id/idx>", "add node to favorite"),
            (":delfav <name/id>",     "remove favorite node"),
            (":favs",                 "show favorite nodes"),
            (":q",               "quit"),
            ("ctrl+n",           "next channel"),
            ("ctrl+p",           "main menu (system tab)"),
            ("ctrl+x",           "close current DM tab"),
            ("ctrl+d",           "toggle node sidebar"),
            ("ctrl+l",           "clear log"),
        ]
        self.store.add("system", "sys", "")
        self.store.add("system", "sys", "═══ commands ═══")
        for cmd, desc in cmds:
            self.store.add("system", "sys", f"  {cmd:<28} {desc}")
        self.query_one("#log", RichLog).clear()
        self._refresh_log()

    def _update_chat_view(self):
        try:
            chat_col = self.query_one("#chat-col")
            radar = self.query_one("#radar-view", RadarWidget)
            if self.current_channel == "map":
                chat_col.display = False
                radar.display = True
                radar.update_radar()
            else:
                chat_col.display = True
                radar.display = False
        except Exception:
            pass

    def action_radar_zoom_in(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_zoom_in()
        except Exception:
            pass

    def action_radar_zoom_out(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_zoom_out()
        except Exception:
            pass

    def action_radar_pan_up(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_pan_up()
        except Exception:
            pass

    def action_radar_pan_down(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_pan_down()
        except Exception:
            pass

    def action_radar_pan_left(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_pan_left()
        except Exception:
            pass

    def action_radar_pan_right(self):
        try:
            self.query_one("#radar-view", RadarWidget).action_pan_right()
        except Exception:
            pass

    def action_next_channel(self):
        self.ch_index = (self.ch_index + 1) % len(self.channels)
        self.query_one("#log", RichLog).clear()
        self._refresh_log()
        self._update_chat_view()

    def action_main_menu(self):
        if "system" in self.channels:
            self.ch_index = self.channels.index("system")
        else:
            self.ch_index = 0
        self.query_one("#log", RichLog).clear()
        self._refresh_log()
        self._update_chat_view() 
        self._refresh_channel_bar()

    def action_close_channel(self):
        self._close_current_dm()

    def action_clear_log(self):
        self.store.channels[self.current_channel].clear()
        self.query_one("#log", RichLog).clear()
        self._refresh_log()

    def action_toggle_nodes(self):
        panel = self.query_one("#node-col")
        self._nodes_visible = not self._nodes_visible
        panel.display = self._nodes_visible

    def action_show_help(self):
        self._show_help_in_log()

    def action_quit(self):
        if self.mesh.iface:
            try: self.mesh.iface.close()
            except Exception: pass
        self.exit()


def main():
    print("\033[?25l", end="")
    app = MeshApp()
    try:
        app.run()
    finally:
        print("\033[?25h", end="")
        print("\033[0m", end="")


if __name__ == "__main__":
    main()