# Meshtastic TUI Messenger 📟

A minimalist, cyberpunk-styled Text User Interface (TUI) messenger for off-grid Meshtastic hardware networks, built with Python and the Textual framework.
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen6.png)
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen8.png)
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen9.png)
![Meshtastic TUI Screenshot](https://raw.githubusercontent.com/mikeelucky/meshtasticCLI/refs/heads/main/screen3.png)


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

All control commands start with a colon (`:`):
:help Help
etc

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

Управление интерфейсом и навигация осуществляются через встроенные команды (начинаются с `:`):
:help - Отобразить справку
и так далее

---
