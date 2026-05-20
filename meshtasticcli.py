#!/usr/bin/env python3
"""
meshtastic TUI client — no internet, no servers, no gods
"""

import asyncio
import time
import sys
import os
import pprint
from datetime import datetime
from collections import defaultdict, deque
from typing import Optional

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from rich.text import Text


# ── HARD-CODED CONNECTION CONFIGURATION ───────────────────────────────────────
CONNECTION_TYPE = "tcp"  # "serial" or "tcp"
SERIAL_PORT = "/dev/ttyUSB0"
TCP_HOST = "192.168.1.1"
TCP_PORT = 4403
# ──────────────────────────────────────────────────────────────────────────────


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


def find_node_by_name(interface, name: str) -> Optional[str]:
    """Find node ID by shortName or longName (case-insensitive)."""
    if not interface.nodes:
        return None
    for node_id, node_data in interface.nodes.items():
        user_info = node_data.get("user", {})
        if (user_info.get("longName", "").lower() == name.lower() or 
            user_info.get("shortName", "").lower() == name.lower()):
            return str(node_id)
    return None


def ts() -> str:
    """Return current time as HH:MM:SS."""
    return datetime.now().strftime("%H:%M:%S")


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
        level = 0

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


# ── MESSAGE STORE ─────────────────────────────────────────────────────────────


class MessageStore:
    def __init__(self):
        self.channels: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.unread: dict[str, int] = defaultdict(int)

    def add(self, channel: str, sender: str, text: str,
            is_own=False, rssi=None, snr=None, is_raw_debug=False) -> dict:
        entry = {
            "ts": ts(),
            "sender": str(sender),
            "text": text,
            "is_own": is_own,
            "rssi": rssi,
            "snr": snr,
            "raw_debug": is_raw_debug
        }
        self.channels[channel].append(entry)
        if not is_own:
            self.unread[channel] += 1
        return entry

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


class MeshInterface:
    def __init__(self, store: MessageStore, on_update):
        self.store = store
        self.on_update = on_update
        self.iface = None
        self.my_id = "!local"
        self.my_name = "operator"
        self.nodes: dict = {}
        self.connected = False
        self.channel_names: dict[int, str] = {0: "primary"}
        self.app_channels_callback = None
        self.app_dm_callback = None

    def _refresh_nodes(self) -> None:
        """Safely refresh node cache from interface."""
        if self.iface and hasattr(self.iface, "nodes") and self.iface.nodes:
            self.nodes = dict(self.iface.nodes)

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
        if "heartbeat" in topic_name.lower():
            return

        try:
            clean_kwargs = {k: v for k, v in kwargs.items() if k != 'interface'}
            formatted_data = pprint.pformat(clean_kwargs, indent=2, width=60, depth=3)
        except Exception as e:
            formatted_data = f"Formatting error: {e}\nRaw keys: {list(kwargs.keys())}"

        debug_entry = f"[bold #ff79c6]▶ {topic_name}[/bold #ff79c6]\n[#8be9fd]{formatted_data}[/#8be9fd]"
        self.store.add("debug", "raw", debug_entry, is_raw_debug=True)
        if hasattr(self, 'on_update') and self.on_update:
            self.on_update()

    def _on_recv(self, packet, interface):
        self._refresh_nodes()

        decoded = packet.get("decoded", {})
        text = decoded.get("text", "")
        if not text:
            self.on_update()
            return

        raw_to_id = packet.get("toId")
        sender_id = str(packet.get("fromId", "!unknown"))
        to_id = str(raw_to_id if raw_to_id is not None else "^all")
        rssi = packet.get("rxRssi")
        snr  = packet.get("rxSnr")

        is_broadcast = (
            to_id.startswith("^") or 
            to_id == "4294967295" or 
            raw_to_id == 4294967295 or
            to_id.lower() == "!ffffffff"
        )
        is_dm = not is_broadcast

        if is_dm:
            my_str_id = str(self.my_id)
            is_from_me = sender_id == my_str_id or sender_id.replace("!", "") == my_str_id.replace("!", "")
            peer_id = sender_id if not is_from_me else to_id
            dm_tab_name = f"▶{peer_id}"

            if self.app_dm_callback:
                self.app_dm_callback(dm_tab_name)
            self.store.add(dm_tab_name, sender_id, text, rssi=rssi, snr=snr)
        else:
            ch_index = packet.get("channel", 0)
            channel = self.channel_names.get(ch_index, f"ch_{ch_index}")
            if self.app_channels_callback:
                self.app_channels_callback(channel)
            self.store.add(channel, sender_id, text, rssi=rssi, snr=snr)

        self.on_update()
        if hasattr(self, 'app') and self.app:
            self.app.call_from_thread(self.app._refresh_log)
            self.app.call_from_thread(self.app._refresh_nodes)

    def _refresh_log(self):
        log = self.query_one("#log", RichLog)
        msgs = self.store.get(self.current_channel)
        self.store.mark_read(self.current_channel)
        self._refresh_channel_bar()

        lines_count = len(log.lines)
        if not msgs:
            log.clear()
            log.write(Text(f"  — channel #{self.current_channel} is empty —", style=C["ghost"]))
            return

        if lines_count <= 1:
            log.clear()
            for m in msgs:
                self._write_msg(log, m)
        else:
            delta = len(msgs) - lines_count
            if delta > 0:
                for m in msgs[-delta:]:
                    self._write_msg(log, m)

    def _on_connect(self, interface, topic=pub.AUTO_TOPIC):
        self.connected = True
        self.store.add("system", "sys", "link established")
        self._refresh_nodes()
        self.on_update()

    def send(self, text: str, channel: int = 0) -> bool:
        if self.iface and self.connected:
            try:
                self.iface.sendText(text, channelIndex=channel)
                return True
            except Exception as e:
                self.store.add("system", "sys", f"tx failed: {e}")
                return False
        return False

    def send_dm(self, text: str, target_id: str) -> bool:
        if self.iface and self.connected:
            try:
                destination = target_id if target_id.startswith("!") else f"!{target_id}"
                if destination.startswith("!") and len(destination) > 1:
                    try:
                        destination = int(destination[1:], 16)
                    except ValueError:
                        pass
                self.iface.sendText(text, destinationId=destination)
                return True
            except Exception as e:
                self.store.add("system", "sys", f"dm tx failed: {e}")
                return False
        return False


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
                short = name[:14].ljust(14)

                node_text = Text(f"  ◈ {short}\n", style=col)
                node_text.append(Text.from_markup(f"    {snr_bar(snr_val)} {hop_indicator(hops)}\n"))
                self.mount(Static(node_text))

        footer_text = Text(f"\n  {'─'*18}\n", style=C["dim"])
        footer_text.append(f"  total: {len(nodes)}\n", style=C["ghost"])
        footer_text.append(f"  self: {self.mesh.my_name[:14]}\n", style=f"{C['accent']}")
        self.mount(Static(footer_text))


# ── MAIN APP ───────────────────────────────────────────────────────────────────


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
    """

    BINDINGS = [
        Binding("ctrl+c", "quit",         "quit",       show=True),
        Binding("ctrl+n", "next_channel", "next ch",    show=True),
        Binding("ctrl+p", "prev_channel", "prev ch",    show=True),
        Binding("ctrl+x", "close_channel","close DM",   show=True),
        Binding("ctrl+l", "clear_log",    "clear",      show=True),
        Binding("ctrl+d", "toggle_nodes", "nodes",      show=True),
        Binding("f1",     "show_help",    "help",       show=True),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = MessageStore()
        self.mesh = MeshInterface(self.store, self._schedule_update)
        self.mesh.app = self
        self.mesh.app_channels_callback = self._register_channel_from_mesh
        self.mesh.app_dm_callback = self._register_dm_tab

        self.channels = ["primary", "system", "debug"]
        self.ch_index = 0
        self._nodes_visible = True
        self._update_pending = False

    @property
    def current_channel(self) -> str:
        return self.channels[self.ch_index]

    def _register_channel_from_mesh(self, name: str):
        if name not in self.channels:
            idx = self.channels.index("system")
            self.channels.insert(idx, name)
            try:
                self._refresh_channel_bar()
            except RuntimeError:
                self.call_from_thread(self._refresh_channel_bar)

    def _register_dm_tab(self, tab_name: str):
        if tab_name not in self.channels:
            idx = self.channels.index("system")
            self.channels.insert(idx, tab_name)
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
                    yield Static(f"[{C['accent']}]mesh ›[/{C['accent']}] ", id="prompt", markup=True)
                    yield Input(placeholder="type msg, :dm <name/id> <text> or :close", id="msg-input")
            yield NodePanel(self.mesh, id="node-col")
        yield Static("", id="statusbar")

    def _header_art(self) -> str:
        logo = f"[bold {C['hi']}]▰▰ meshtastic cli client[/bold {C['hi']}]"
        mode = f"[{C['accent']}]⟁ AUTONOMOUS MODE[/{C['accent']}]"
        manifest = f"[{C['ghost']}]no internet · no servers · no gods[/{C['ghost']}]"
        return f" {logo} │ {mode} ── {manifest}"

    def on_mount(self):
        self._refresh_channel_bar()
        self._refresh_log()
        self._refresh_status()
        self._refresh_nodes()

        if CONNECTION_TYPE == "serial":
            self.store.add("system", "sys", f"Auto-connecting to Serial: {SERIAL_PORT}...")
            try:
                self.mesh.connect_serial(SERIAL_PORT)
            except Exception as e:
                self.store.add("system", "sys", f"[red]❌ Serial connection failed: {e}[/red]")
        elif CONNECTION_TYPE == "tcp":
            self.store.add("system", "sys", f"Auto-connecting to TCP: {TCP_HOST}:{TCP_PORT} (timeout 2s)...")
            self._refresh_log()

            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)

            port_open = False
            try:
                sock.connect((TCP_HOST, int(TCP_PORT)))
                port_open = True
                sock.close()
            except (socket.timeout, Exception):
                port_open = False

            if port_open:
                try:
                    self.mesh.connect_tcp(TCP_HOST, TCP_PORT)
                    self.store.add("system", "sys", "[green]✓ Connected to Meshtastic via TCP![/green]")
                except Exception as e:
                    self.store.add("system", "sys", f"[red]❌ Meshtastic init error: {e}[/red]")
            else:
                self.store.add("system", "sys",
                               f"[red]❌ TCP Connection failed. Host {TCP_HOST}:{TCP_PORT} is unreachable.[/red]")
                self.store.add("system", "sys",
                               "[#38bdf8]TUI loaded. Use :tcp <ip> to try another address. Use :help to help[/#38bdf8]")
                if hasattr(self.mesh, 'iface'):
                    self.mesh.iface = None
                if "system" in self.channels:
                    self.ch_index = self.channels.index("system")

            self.query_one("#log", RichLog).clear()
            self._refresh_log()

        self.set_interval(0.5, self._refresh_status)
        self.set_interval(0.2, self._poll_updates)
        self.query_one("#msg-input", Input).focus()

    def _poll_updates(self):
        if self._update_pending:
            self._update_pending = False
            self._refresh_log()
            self._refresh_status()
            self._refresh_nodes()

    def _refresh_ui(self):
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
            name = self.mesh.my_name[:12]
            t.append(f"▸ {name:<13}", style=f"bold {C['accent']}")
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
            t.append(f"  {display_sender[:12]:<13}", style=col)

        t.append(m["text"], style=C["text"])

        meta_parts = []
        if m.get("rssi") is not None:
            meta_parts.append(f"rssi:{m['rssi']}")
        if m.get("snr") is not None:
            meta_parts.append(f"snr:{m['snr']:.1f}")
        if meta_parts:
            t.append(f"  [{' '.join(meta_parts)}]", style=C["dim"])

        log.write(t)

    
    def _refresh_log(self):
        log = self.query_one("#log", RichLog)
        msgs = self.store.get(self.current_channel)
        self.store.mark_read(self.current_channel)
        self._refresh_channel_bar()

        lines_count = len(log.lines)

        if not msgs:
            log.clear()
            log.write(Text(f"  — channel #{self.current_channel} is empty —", style=C["ghost"]))
            return

        if lines_count <= 1:
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

    def _refresh_nodes(self):
        try:
            panel = self.query_one("#node-col")
        except Exception:
            return

        nodes_widget = None
        for widget_type in ["RichLog", "TextLog", "Static", "Label"]:
            try:
                from textual.widgets import RichLog, Static, Label
                try: from textual.widgets import TextLog
                except ImportError: TextLog = None

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

            try:
                raw_nodes = self.mesh.iface.nodes
                nodes_dict = dict(raw_nodes) if raw_nodes else {}
            except Exception:
                lines.append("  [red]Read error[/red]")
                write_func("\n".join(lines))
                return

            if not nodes_dict:
                lines.append("  [gray]No nodes discovered yet...[/gray]")
                write_func("\n".join(lines))
                return

            self._displayed_node_ids = []

            for nid, info in nodes_dict.items():
                if isinstance(info, dict):
                    user_info = info.get("user", {})
                    name = user_info.get("longName") or user_info.get("shortName") or f"!{nid:08x}"
                    snr = info.get("snr", 0.0)
                    bar = "█" if snr > 0 else "▄"

                    lines.append(f" {bar} [bold #e2e8f0]{name}[/bold #e2e8f0] [gray]({snr}dB)[/gray]")
                    self._displayed_node_ids.append(str(nid))

            write_func("\n".join(lines))

            def handle_widget_click(event):
                line_index = event.style.y - 1
                if hasattr(self, '_displayed_node_ids') and 0 <= line_index < len(self._displayed_node_ids):
                    target_node_id = self._displayed_node_ids[line_index]
                    if hasattr(self, 'open_dm'):
                        self.open_dm(target_node_id)
                    elif hasattr(self, '_register_dm_tab'):
                        self._register_dm_tab(f"▶{target_node_id}")

            nodes_widget.on_click = handle_widget_click

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

        from datetime import datetime
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%d.%m.%y")

        my_hex_id = "!local"
        long_name = "Operator"

        if hasattr(self, 'mesh') and self.mesh:
            nid = self.mesh.my_id
            try:
                if isinstance(nid, int):
                    my_hex_id = f"!{nid:08x}"
                elif isinstance(nid, str) and nid.isdigit():
                    my_hex_id = f"!{int(nid):08x}"
                else:
                    my_hex_id = str(nid)
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
            f"[bold #ae7cff]{date_str} {time_str}[/bold #ae7cff]"
        )

        if hasattr(statusbar, "update"):
            statusbar.update(status_text)
        elif hasattr(statusbar, "clear"):
            statusbar.clear()
            statusbar.write(status_text)

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

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        if text.startswith(":"):
            self._handle_command(text[1:])
        else:
            self._send_message(text)

    def _send_message(self, text: str):
        if self.current_channel in ("system", "debug"):
            self.store.add("system", "sys", f"Error: Cannot send messages in #{self.current_channel} channel.")
            self._refresh_log()
            return

        if self.current_channel.startswith("▶"):
            target_id = self.current_channel[1:]
            sent = self.mesh.send_dm(text, target_id)
            if sent:
                self.store.add(self.current_channel, self.mesh.my_id, text, is_own=True)
            else:
                self.store.add(self.current_channel, "sys", "DM sending failed.")
            self._refresh_log()
            return

        ch_index = 0
        for idx, name in self.mesh.channel_names.items():
            if name == self.current_channel:
                ch_index = idx
                break

        sent = self.mesh.send(text, channel=ch_index)
        if sent:
            self.store.add(self.current_channel, self.mesh.my_id, text, is_own=True)
        else:
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

        elif verb == "serial" and args:
            self.store.add("system", "sys", f"connecting serial {args[0]}…")
            ok = self.mesh.connect_serial(args[0])
            self.store.add("system", "sys", "serial ok" if ok else "serial failed")
            self._refresh_log()

        elif verb == "tcp" and args:
            host = args[0]
            port = int(args[1]) if len(args) > 1 else 4403
            self.store.add("system", "sys", f"connecting tcp {host}:{port}…")
            ok = self.mesh.connect_tcp(host, port)
            self.store.add("system", "sys", "tcp ok" if ok else "tcp failed")
            self._refresh_log()

        elif verb == "ch" and args:
            ch = args[0].lstrip("#").lower()
            if ch not in self.channels:
                idx = self.channels.index("system")
                self.channels.insert(idx, ch)
            self.ch_index = self.channels.index(ch)
            self.store.add("system", "sys", f"switched to #{ch}")
            self.query_one("#log", RichLog).clear()
            self._refresh_log()
            self._refresh_channel_bar()

        elif verb == "nodes":
            self.store.add("system", "sys", "=== node table ===")
            self._node_index_map = {}
            idx = 1

            for nid, info in self.mesh.nodes.items():
                str_nid = str(nid)
                if isinstance(info, dict):
                    u = info.get("user", info)
                    name = u.get("longName", str_nid[-6:])
                    snr_val = info.get("snr", "?")
                    hops = info.get("hopsAway", "?")

                    self._node_index_map[str(idx)] = str_nid
                    self.store.add(
                        "system",
                        "sys",
                        f" [{idx}] {name:<18} id:{str_nid[-8:]}  snr:{snr_val}  hops:{hops}"
                    )
                    idx += 1

            self.ch_index = self.channels.index("system")
            self.query_one("#log", RichLog).clear()
            self._refresh_log()

        elif verb == "dm" and args:
            target = " ".join(args).strip() if isinstance(args, list) else str(args).strip()
            if not target:
                self.store.add("system", "sys", "Usage: :dm <name/node_id/index>")
                self._refresh_log()
                return

            resolved_id = None
            if hasattr(self, '_node_index_map') and target in self._node_index_map:
                resolved_id = self._node_index_map[target]
                self.store.add("system", "sys", f"[sys] Switching to node {target} (ID: {resolved_id})")

            if not resolved_id:
                for nid, info in self.mesh.nodes.items():
                    if isinstance(info, dict):
                        current_long_name = info.get("user", {}).get("longName", "")
                        if current_long_name.lower() == target.lower():
                            resolved_id = str(nid)
                            break

            if not resolved_id:
                resolved_id = target

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
            (":close / :x",      "close current private DM tab"),
            (":serial /dev/ttyUSB0",  "connect manual serial device(linux only)"),
            (":tcp 192.168.1.1", "connect manual via TCP"),
            (":ch <name>",       "switch channel"),
            (":nodes",           "list all mesh nodes details"),
            (":clear",           "clear current log window"),
            (":help",            "this message"),
            (":q",               "quit"),
            ("ctrl+n",           "next channel"),
            ("ctrl+p",           "previous channel"),
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

    def action_next_channel(self):
        self.ch_index = (self.ch_index + 1) % len(self.channels)
        self.query_one("#log", RichLog).clear()
        self._refresh_log()

    def action_prev_channel(self):
        self.ch_index = (self.ch_index - 1) % len(self.channels)
        self.query_one("#log", RichLog).clear()
        self._refresh_log()

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
