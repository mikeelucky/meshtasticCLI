# Meshtastic TUI Messenger 📟

A minimalist, cyberpunk-styled Text User Interface (TUI) messenger for off-grid Meshtastic hardware networks, built with Python and the Textual framework.
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen1.png)
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen2.png)
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen3.png)
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen4.png)
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen5.png)

Минималистичный терминальный (TUI) мессенджер для работы с автономными радиосетями Meshtastic, написанный на Python с использованием фреймворка Textual.

---

## English

### 🚀 Key Features
* **Sleek TUI Layout:** High-contrast terminal design optimized for fast, mouse-free workflow.
* **Live Node Tracking:** Auto-refreshing side panel displaying nodes currently in the air with real-time SNR values.
* **Smart DM Routing:** Quick-access private messaging using names, raw Hex-IDs, or temporary short indices.
* **Tactical Status Bar:** Real-time system monitoring including your Node Hex-ID, configured names, and date/time tracking.

### 🛠️ Installation

#### Option 1: Fast Launch (Windows Only)
Don't want to install Python? Go to the **Releases** section of this repository and download the standalone `.exe` build. Just run it in your terminal, and you are ready to go!

#### Option 2: Run from Source (Cross-platform)
1. Clone the repository:
   ```bash
   git clone https://github.com/mikeelucky/meshtasticCLI.git
   cd meshtastic-tui
   pip install meshtastic textual rich
   python3 meshtasticcli.py # or launch .exe
   In the app type :tcp 192.168.x.x — the address of your node on the local network for connecting to a node
   ### ⌨️ TUI Commands Reference
All control commands start with a colon (`:`):
:help Help
* `:nodes` — Scans the mesh network, lists all active stations in the main log, and assigns them a quick-access index number `[1]`, `[2]`, etc.
* `:dm <index/name/node_id>` — Opens a private messaging tab for the selected target. Supports full names with spaces and short list indices (e.g., `:dm 2` or `:dm Base Station`).
* `Click/Enter` (on input field) — Send message to the currently active channel or private tab.

---
## Русский
### 🚀 Ключевые возможности
* **Классический TUI-интерфейс:** Высококонтрастный консольный дизайн, полностью оптимизированный под управление с клавиатуры.
* **Мониторинг эфира:** Автоматически обновляемая боковая панель со списком активных радиостанций и уровнем сигнала (SNR).
* **Приватные чаты:** Мгновенный переход к личной переписке по позывному, сырому Hex-ID или порядковому номеру ноды из списка.
* **Информативный статус-бар:** Живой контроль состояния станции: ваш HEX-адрес, позывные сети, текущее время и дата.

### 🛠️ Установка и запуск
#### Вариант 1: Быстрый запуск (Только для Windows)
Не хотите устанавливать Python и настраивать окружение? Перейдите в раздел **Releases** (Релизы) этого репозитория и скачайте готовый автономный `.exe` билд. Просто запустите его в консоли, и приложение готово к работе!

#### Вариант 2: Запуск из исходного кода (Кроссплатформенный)
1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/mikeelucky/meshtasticCLI.git
   cd meshtastic-tui
   pip install meshtastic textual rich
   python3 meshtasticcli.py # или запуск .exe
   В самом приложении напишите :tcp 192.168.x.x - адрес вашей ноды в локальной сети для подключения к ней.
   ### ⌨️ Справочник консольных команд
Управление интерфейсом и навигация осуществляются через встроенные команды (начинаются с `:`):
:help - Отобразить справку
* `:nodes` — Опрашивает память меш-модема, выводит список активных нод в главный лог и присваивает каждой станции короткий порядковый номер `[1]`, `[2]` и т.д.
* `:dm <индекс/имя/ID_ноды>` — Создает и открывает отдельную вкладку приватного чата с указанным узлом. Поддерживает имена с пробелами и быстрый вызов по индексу (например, `:dm 2` или `:dm Полевой Скаут`).
* `Ввод текста` (в строке ввода) — Отправка сообщения в текущую активную вкладку общего канала или приватного DM.

---
