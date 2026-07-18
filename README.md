# Multi-Console Serial Terminal

A lightweight, responsive Python GUI application for Windows built using standard `tkinter` and `pyserial`. It allows developers to monitor and control 1 to 4 serial connections simultaneously in parallel, featuring thread-safe operation, customizable layouts, and smart parsing features.

### Key Features
* 📌 **Always-on-Top Toggle:** Keep the window pinned over other programs with a single click.
* 🔄 **Dynamic Split Layouts:** Cycle between **Mixed**, **Vertical**, and **Horizontal** layouts that scale automatically when the main window is resized.
* 💻 **Premium Retro Aesthetics:** Custom-styled dark theme featuring a black background and high-visibility neon-green monospace text logs with adjustable font sizes.
* 🛠️ **ANSI & Clear Screen Support:** Real-time rendering of ANSI terminal escape codes (text styling, bold, underline, color formats) and screen-clear commands (`Esc[2J`).
* 🔀 **Live ASCII / HEX Views:** Instantly toggle the log display format between standard ASCII text and space-separated hexadecimal bytes using a dedicated scrollback buffer.
* ⚡ **Smart Transmission:**
  * **Raw Input:** Sends content exactly as typed.
  * **Enter Key Binding:** Appends CRLF (`\r\n`) newlines.
  * **Hex Parsing:** Detects space/comma-separated hex tokens (e.g., `0xFF 0xAA 0x12`) and sends them as raw binary bytes.
* 🔌 **Loopback Mode:** Enter `loop://` in the port selection to run loopback tests offline.

**Additional info for users**  

- **Python version:** Tested with Python 3.13 (requires ≥ 3.8).  
- **Core dependencies:**  
  ```bash
  pip install pyserial
  ```
  (Tkinter is included with the standard Windows Python installer.)  

- **Running the app:**  
  ```bash
  python serial_dual_tool.py
  ```  
