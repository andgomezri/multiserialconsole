#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Console Serial Terminal
-----------------------------
A Python Tkinter application for Windows that manages 1 to 4 parallel serial connections.
Features:
- Always on Top toggle
- Dynamic layouts (Vertical, Horizontal, Mixed grids)
- ANSI color rendering and screen clearing support
- Live ASCII / HEX display modes for received data
- Smart send parsing (hex values like 0xFF vs standard strings)
- Scalable monospace fonts per console
"""

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import serial
import serial.tools.list_ports
import threading
import time
import re
import queue

class ConsoleWidget(tk.Frame):
    """
    A self-contained serial console widget with its own controls,
    text log display (monospace green/black), and transmission controls.
    """
    def __init__(self, parent, console_id, remove_callback, **kwargs):
        super().__init__(parent, bd=2, relief="groove", bg="#1a1a1a", **kwargs)
        self.console_id = console_id
        self.remove_callback = remove_callback
        
        self.serial_port = None
        self.is_connected = False
        self.rx_thread = None
        self.rx_queue = queue.Queue()
        
        # Buffer for received bytes (limits scrollback size to prevent memory lag)
        self.rx_buffer = bytearray()
        self.max_buffer_size = 100000
        
        # State tracking for ANSI escape code rendering
        self.active_tags = set()
        
        # ANSI Escape Code Colors mapping
        self.COLOR_MAP = {
            '30': '#2d2d2d',  # Black/Dark Gray
            '31': '#ff5555',  # Red
            '32': '#55ff55',  # Green
            '33': '#ffff55',  # Yellow
            '34': '#5555ff',  # Blue
            '35': '#ff55ff',  # Magenta
            '36': '#55ffff',  # Cyan
            '37': '#ffffff',  # White
            '90': '#555555',  # Bright Black (Gray)
            '91': '#ff6e6e',  # Bright Red
            '92': '#6eff6e',  # Bright Green
            '93': '#ffff6e',  # Bright Yellow
            '94': '#6e6eff',  # Bright Blue
            '95': '#ff6eff',  # Bright Magenta
            '96': '#6effff',  # Bright Cyan
            '97': '#ffffff',  # Bright White
        }
        self.BG_COLOR_MAP = {
            '40': '#000000',  # Background Black
            '41': '#880000',  # Background Red
            '42': '#008800',  # Background Green
            '43': '#888800',  # Background Yellow
            '44': '#000088',  # Background Blue
            '45': '#880088',  # Background Magenta
            '46': '#008888',  # Background Cyan
            '47': '#888888',  # Background White
        }
        
        self.create_widgets()
        self.refresh_ports()

    def create_widgets(self):
        # Configure layout inside this console widget frame
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ----------------------------------------------------
        # 1. Header Toolbar Frame
        # ----------------------------------------------------
        header = tk.Frame(self, bg="#2b2b2b", pady=4, padx=6)
        header.grid(row=0, column=0, sticky="ew")

        # Remove/Close Console Button
        close_btn = tk.Button(header, text="✕", fg="#ff4d4d", bg="#2b2b2b", activeforeground="#ffffff", 
                              activebackground="#ff4d4d", bd=0, font=("Segoe UI", 10, "bold"), 
                              command=self.close_console, cursor="hand2")
        close_btn.pack(side="left", padx=(0, 6))

        # Title Label & Entry
        tk.Label(header, text="Title:", fg="#e0e0e0", bg="#2b2b2b", font=("Segoe UI", 9, "bold")).pack(side="left", padx=2)
        self.title_var = tk.StringVar(value=f"Console {self.console_id}")
        title_entry = tk.Entry(header, textvariable=self.title_var, width=12, font=("Segoe UI", 9), 
                               bg="#1e1e1e", fg="#ffffff", insertbackground="white", bd=1, relief="solid")
        title_entry.pack(side="left", padx=(2, 6))

        # Port Label & Combobox
        tk.Label(header, text="Port:", fg="#e0e0e0", bg="#2b2b2b", font=("Segoe UI", 9, "bold")).pack(side="left", padx=2)
        self.port_combo = ttk.Combobox(header, width=8, font=("Segoe UI", 9), postcommand=self.refresh_ports)
        self.port_combo.pack(side="left", padx=(2, 6))

        # Baud Rate Label & Combobox
        tk.Label(header, text="Baud:", fg="#e0e0e0", bg="#2b2b2b", font=("Segoe UI", 9, "bold")).pack(side="left", padx=2)
        self.baud_combo = ttk.Combobox(header, width=7, font=("Segoe UI", 9))
        self.baud_combo['values'] = ('9600', '115200', '1200', '2400', '4800', '19200', '38400', '57600', '230400', '460800', '921600')
        self.baud_combo.set('115200')
        self.baud_combo.pack(side="left", padx=(2, 6))

        # Connection Action Toggle Button (Open/Close)
        self.open_button = tk.Button(header, text="Open", fg="white", bg="#28a745", activebackground="#218838",
                                     font=("Segoe UI", 9, "bold"), bd=1, relief="flat", padx=6, 
                                     command=self.toggle_connection, cursor="hand2")
        self.open_button.pack(side="left", padx=(2, 8))

        # View Mode Toggle: ASCII vs HEX
        self.view_mode = tk.StringVar(value="ASCII")
        ascii_rb = tk.Radiobutton(header, text="ASCII", variable=self.view_mode, value="ASCII", 
                                  fg="#ffffff", bg="#2b2b2b", selectcolor="#1e1e1e", activeforeground="#ffffff", 
                                  activebackground="#2b2b2b", font=("Segoe UI", 9), command=self.on_format_change)
        hex_rb = tk.Radiobutton(header, text="HEX", variable=self.view_mode, value="HEX", 
                                fg="#ffffff", bg="#2b2b2b", selectcolor="#1e1e1e", activeforeground="#ffffff", 
                                activebackground="#2b2b2b", font=("Segoe UI", 9), command=self.on_format_change)
        ascii_rb.pack(side="left", padx=2)
        hex_rb.pack(side="left", padx=2)

        # Font Size Selector
        tk.Label(header, text="Size:", fg="#e0e0e0", bg="#2b2b2b", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(8, 2))
        self.font_size_var = tk.IntVar(value=10)
        font_spin = ttk.Spinbox(header, from_=8, to=30, textvariable=self.font_size_var, width=3, 
                                command=self.update_font)
        font_spin.pack(side="left", padx=2)
        font_spin.bind("<Return>", lambda e: self.update_font())
        font_spin.bind("<FocusOut>", lambda e: self.update_font())

        # Clear Console Screen Button
        clear_btn = tk.Button(header, text="🗑️ Clear", fg="#ffffff", bg="#6c757d", activebackground="#5a6268",
                              font=("Segoe UI", 9), bd=1, relief="flat", padx=6, command=lambda: self.clear_display(clear_buffer=True),
                              cursor="hand2")
        clear_btn.pack(side="right", padx=2)

        # ----------------------------------------------------
        # 2. Log Text Frame (Terminal Area)
        # ----------------------------------------------------
        display_frame = tk.Frame(self, bg="#0d0d0d")
        display_frame.grid(row=1, column=0, sticky="nsew")

        # Monospace Text Box
        self.text_display = tk.Text(display_frame, bg="#0d0d0d", fg="#39ff14", insertbackground="#39ff14",
                                    font=("Consolas", 10), wrap=tk.CHAR, bd=0, highlightthickness=0)
        self.text_display.pack(side="left", fill="both", expand=True)

        # Vertical Scrollbar
        scrollbar = ttk.Scrollbar(display_frame, orient="vertical", command=self.text_display.yview)
        scrollbar.pack(side="right", fill="y")
        self.text_display.configure(yscrollcommand=scrollbar.set)

        # Make read-only by default
        self.text_display.configure(state=tk.DISABLED)

        # Setup custom tag styles (ANSI color support)
        self.setup_tags()

        # ----------------------------------------------------
        # 3. Footer Control Frame (Send Area)
        # ----------------------------------------------------
        footer = tk.Frame(self, bg="#2b2b2b", pady=4, padx=6)
        footer.grid(row=2, column=0, sticky="ew")

        # Entry for text input
        self.send_entry = tk.Entry(footer, bg="#1e1e1e", fg="#ffffff", insertbackground="white", 
                                   bd=1, relief="solid", font=("Consolas", 10))
        self.send_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        # Enter key triggers send + carriage return line feed
        self.send_entry.bind("<Return>", self.send_data)

        # Send Button
        send_btn = tk.Button(footer, text="Send", fg="white", bg="#007bff", activebackground="#0069d9",
                             font=("Segoe UI", 9, "bold"), bd=1, relief="flat", padx=10, 
                             command=lambda: self.send_data(None), cursor="hand2")
        send_btn.pack(side="right")

    def setup_tags(self):
        """Initializes text widget tag configurations for bold, underline, system status, and colors."""
        size = self.font_size_var.get()
        font_family = "Consolas"
        self.text_display.tag_configure('bold', font=(font_family, size, 'bold'))
        self.text_display.tag_configure('underline', underline=True)
        
        # Orange tag for system messages (connected, disconnected, etc.)
        self.text_display.tag_configure('system', foreground='#ffc107')
        
        # Load ANSI color tag specifications
        for code, color in self.COLOR_MAP.items():
            self.text_display.tag_configure(f'fg_{code}', foreground=color)
        for code, color in self.BG_COLOR_MAP.items():
            self.text_display.tag_configure(f'bg_{code}', background=color)

    def refresh_ports(self):
        """Scans host system for serial COM ports and updates selection dropdown."""
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo['values'] = ports
        if ports:
            if self.port_combo.get() not in ports:
                self.port_combo.set(ports[0])
        else:
            self.port_combo.set('')

    def update_font(self):
        """Dynamically adjusts text size of log terminal according to selection spinner."""
        try:
            size = self.font_size_var.get()
            if size < 6:
                size = 6
            elif size > 50:
                size = 50
        except ValueError:
            size = 10
            
        font_family = "Consolas"
        self.text_display.configure(font=(font_family, size))
        self.text_display.tag_configure('bold', font=(font_family, size, 'bold'))

    def toggle_connection(self):
        """Toggles serial port between connection and disconnection states."""
        if self.is_connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        """Attempts to open the serial port using configured selection."""
        port = self.port_combo.get()
        baud_str = self.baud_combo.get()
        if not port:
            messagebox.showerror("Port Error", "Please select a serial port.")
            return
        try:
            baud = int(baud_str)
        except ValueError:
            messagebox.showerror("Baud Error", f"Baud rate '{baud_str}' is invalid.")
            return

        try:
            self.serial_port = serial.serial_for_url(port, baudrate=baud, timeout=0.1)
            self.is_connected = True
            
            # Switch open button to red 'Close' style
            self.open_button.configure(text="Close", bg="#dc3545", activebackground="#bd2130")
            
            # Clear queue of any stale entries
            while not self.rx_queue.empty():
                try:
                    self.rx_queue.get_nowait()
                except Exception:
                    pass

            # Start reception thread
            self.rx_thread = threading.Thread(target=self.receive_loop, daemon=True)
            self.rx_thread.start()
            
            # Start polling loop on the GUI main thread
            self.after(10, self.check_rx_queue)
            
            self.append_system_msg(f"*** Connected to {port} @ {baud} bps ***\n")
        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to {port}:\n{str(e)}")

    def disconnect(self):
        """Closes serial connection safely and terminates reception threads."""
        self.is_connected = False
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self.serial_port = None
        
        # Switch button back to green 'Open' style
        self.open_button.configure(text="Open", bg="#28a745", activebackground="#218838")
        self.append_system_msg("\n*** Connection Terminated ***\n")

    def receive_loop(self):
        """Background thread executing blocking reads on serial port."""
        while self.is_connected:
            if self.serial_port and self.serial_port.is_open:
                try:
                    in_waiting = self.serial_port.in_waiting
                    if in_waiting > 0:
                        data = self.serial_port.read(in_waiting)
                        if data:
                            self.rx_queue.put(("data", data))
                    else:
                        time.sleep(0.01)
                except Exception as e:
                    self.rx_queue.put(("error", str(e)))
                    break
            else:
                time.sleep(0.05)

    def check_rx_queue(self):
        """Timer loop that polls the queue for new serial data and errors."""
        if not self.is_connected:
            self.process_queue_items()
            return
            
        self.process_queue_items()
        self.after(10, self.check_rx_queue)

    def process_queue_items(self):
        """Helper to process all currently pending items in rx_queue."""
        try:
            while not self.rx_queue.empty():
                msg_type, payload = self.rx_queue.get_nowait()
                if msg_type == "data":
                    # Append and truncate buffer on the main thread
                    self.rx_buffer.extend(payload)
                    if len(self.rx_buffer) > self.max_buffer_size:
                        del self.rx_buffer[:-self.max_buffer_size]
                    self.append_received_data(payload)
                elif msg_type == "error":
                    self.handle_disconnect_error(payload)
                self.rx_queue.task_done()
        except queue.Empty:
            pass

    def handle_disconnect_error(self, err_msg):
        """Reports disconnection on port failure and updates state."""
        self.disconnect()
        self.append_system_msg(f"\n*** Hardware Connection Lost: {err_msg} ***\n")
        messagebox.showerror("Port Alert", f"Disconnected from {self.port_combo.get()}:\n{err_msg}")

    def insert_text_with_tags(self, text_chunk, tags):
        """Helper to insert text safely into read-only text log, maintaining autoscroll state."""
        self.text_display.configure(state=tk.NORMAL)
        
        # Determine if scrollbar is currently pushed to bottom
        is_at_bottom = self.text_display.yview()[1] >= 0.99
        
        self.text_display.insert(tk.END, text_chunk, tags)
        
        if is_at_bottom:
            self.text_display.see(tk.END)
            
        self.text_display.configure(state=tk.DISABLED)

    def append_received_data(self, data):
        """Handles display updates on new serial data packet."""
        if self.view_mode.get() == "ASCII":
            text = data.decode('utf-8', errors='replace')
            self.append_ascii_text(text)
        else:
            # HEX mode output (space-separated uppercase hex bytes)
            hex_string = " ".join(f"{b:02X}" for b in data) + " "
            self.insert_text_with_tags(hex_string, ())

    def append_ascii_text(self, text):
        """Parses and appends string data handling ANSI colors and newlines."""
        # 1. Screen Clearing Code (ANSI: Esc [ 2 J)
        if '\x1b[2J' in text or '\x1b[2j' in text:
            self.clear_display(clear_buffer=False)
            text = text.replace('\x1b[2J', '').replace('\x1b[2j', '')
            
        # 2. Strip unsupported cursor motions and control escapes
        text = re.sub(r'\x1b\[[0-9;]*[A-DkK]', '', text)

        # 3. Split by style escape sequences: \x1b[ <params> m
        parts = re.split(r'\x1b\[([0-9;]*)m', text)
        
        # Even parts: actual printable characters. Odd parts: style code arguments.
        for idx, part in enumerate(parts):
            if idx % 2 == 0:
                if part:
                    # Apply all active tags to this block
                    self.insert_text_with_tags(part, tuple(self.active_tags))
            else:
                # Update text styles based on code
                codes = part.split(';')
                for code in codes:
                    code = code.strip()
                    if not code or code == '0' or code == '00':
                        self.active_tags.clear()
                    elif code == '1' or code == '01':
                        self.active_tags.add('bold')
                    elif code == '4' or code == '04':
                        self.active_tags.add('underline')
                    elif code in self.COLOR_MAP:
                        # Clear existing foreground styles
                        self.active_tags = {tag for tag in self.active_tags if not tag.startswith('fg_')}
                        self.active_tags.add(f'fg_{code}')
                    elif code in self.BG_COLOR_MAP:
                        # Clear existing background styles
                        self.active_tags = {tag for tag in self.active_tags if not tag.startswith('bg_')}
                        self.active_tags.add(f'bg_{code}')

    def on_format_change(self):
        """Triggered on ASCII/HEX toggle change. Clears and re-renders scrollback buffer."""
        # Reset current logs
        self.text_display.configure(state=tk.NORMAL)
        self.text_display.delete('1.0', tk.END)
        self.text_display.configure(state=tk.DISABLED)
        
        if self.view_mode.get() == "ASCII":
            self.active_tags.clear()
            text = self.rx_buffer.decode('utf-8', errors='replace')
            self.append_ascii_text(text)
        else:
            hex_string = " ".join(f"{b:02X}" for b in self.rx_buffer) + (" " if self.rx_buffer else "")
            self.insert_text_with_tags(hex_string, ())

    def clear_display(self, clear_buffer=True):
        """Clears terminal screen and optionally empties raw data buffer."""
        if clear_buffer:
            self.rx_buffer.clear()
        self.text_display.configure(state=tk.NORMAL)
        self.text_display.delete('1.0', tk.END)
        self.text_display.configure(state=tk.DISABLED)

    def append_system_msg(self, msg):
        """Appends status updates inside terminal view in distinct amber formatting."""
        self.insert_text_with_tags(msg, ('system',))

    def send_data(self, event=None):
        """
        Sends contents of user input box.
        - Event is not None if triggered via 'Enter' key, meaning we append a CRLF newline byte to the request.
        - If the string starts with 0x and follows hex format (0xFF 0xAA ...), we send raw binary.
        """
        if not self.is_connected or not self.serial_port:
            messagebox.showwarning("Send Alert", "Not connected to any port. Open a connection first.")
            return

        raw_text = self.send_entry.get()
        if not raw_text and event is None:
            return  # Ignore empty button clicks

        # Try to parse string as hexadecimal representation
        normalized = raw_text.replace(',', ' ')
        tokens = normalized.split()
        
        is_hex = False
        byte_values = []
        
        if tokens:
            is_hex = True
            for t in tokens:
                # Require 0x prefix for hexadecimal format (e.g. 0xFF)
                if not (t.lower().startswith('0x') and len(t) > 2):
                    is_hex = False
                    break
                try:
                    val = int(t, 16)
                    if 0 <= val <= 255:
                        byte_values.append(val)
                    else:
                        is_hex = False
                        break
                except ValueError:
                    is_hex = False
                    break

        if is_hex:
            bytes_to_send = bytes(byte_values)
        else:
            bytes_to_send = raw_text.encode('utf-8')

        # If Enter key pressed, append newline
        if event is not None:
            bytes_to_send += b'\r\n'

        try:
            self.serial_port.write(bytes_to_send)
            # Clear input box on successful transmission
            self.send_entry.delete(0, tk.END)
        except Exception as e:
            messagebox.showerror("Write Error", f"Failed to send data:\n{str(e)}")
            self.disconnect()

    def close_console(self):
        """Destroys widget and disconnects background threads."""
        self.disconnect()
        self.remove_callback(self)


class SerialMultiTool(tk.Tk):
    """
    Main application window hosting the Top Toolbar settings panel,
    and managing the layout/weighting configuration of active consoles.
    """
    def __init__(self):
        super().__init__()
        self.title("Multi-Serial Console Terminal")
        self.geometry("1100x700")
        self.configure(bg="#121212")
        
        # Catch close window action to shutdown serial threads clean
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Layout arrangements
        self.layout_modes = ["Mixed", "Vertical", "Horizontal"]
        self.current_layout_idx = 0
        self.always_on_top = False
        
        self.consoles = []
        self.console_id_counter = 0

        self.create_global_widgets()
        
        # Load first console by default
        self.add_console()

    def create_global_widgets(self):
        # ----------------------------------------------------
        # Top Settings Header Bar
        # ----------------------------------------------------
        self.toolbar = tk.Frame(self, bg="#1a1a1a", height=45, bd=1, relief="flat")
        self.toolbar.pack(side="top", fill="x")
        
        # App Branding Logo
        app_title = tk.Label(self.toolbar, text="🔗 MULTI-SERIAL TERMINAL", fg="#39ff14", bg="#1a1a1a",
                             font=("Segoe UI", 12, "bold"))
        app_title.pack(side="left", padx=15, pady=10)

        # Right Header Control Layout
        btn_frame = tk.Frame(self.toolbar, bg="#1a1a1a")
        btn_frame.pack(side="right", padx=15)

        # Add Console Button
        self.add_btn = tk.Button(btn_frame, text="➕ Add Console", fg="white", bg="#007bff", 
                                 activebackground="#0069d9", font=("Segoe UI", 9, "bold"), bd=1, relief="flat",
                                 padx=10, pady=5, command=self.add_console, cursor="hand2")
        self.add_btn.pack(side="left", padx=6)

        # Layout Arrangement Button
        self.layout_btn = tk.Button(btn_frame, text="🔄 Layout: Mixed", fg="white", bg="#495057",
                                    activebackground="#343a40", font=("Segoe UI", 9, "bold"), bd=1, relief="flat",
                                    padx=10, pady=5, command=self.cycle_layout, cursor="hand2")
        self.layout_btn.pack(side="left", padx=6)

        # Always on Top Window Pin Button
        self.top_btn = tk.Button(btn_frame, text="📌 Always on Top: OFF", fg="white", bg="#495057",
                                 activebackground="#343a40", font=("Segoe UI", 9, "bold"), bd=1, relief="flat",
                                 padx=10, pady=5, command=self.toggle_always_on_top, cursor="hand2")
        self.top_btn.pack(side="left", padx=6)

        # ----------------------------------------------------
        # Console Display Grid Area
        # ----------------------------------------------------
        self.container = tk.Frame(self, bg="#121212")
        self.container.pack(side="top", fill="both", expand=True)

    def add_console(self):
        """Spawns a new ConsoleWidget and places it in the grid (Max 4)."""
        if len(self.consoles) >= 4:
            messagebox.showwarning("Max Limit", "A maximum of 4 console terminals is allowed.")
            return

        self.console_id_counter += 1
        console = ConsoleWidget(self.container, self.console_id_counter, self.remove_console)
        self.consoles.append(console)
        
        # Redraw grids
        self.rebuild_layout()

        # Disable button when limit reached
        if len(self.consoles) >= 4:
            self.add_btn.configure(state=tk.DISABLED, bg="#343a40")

    def remove_console(self, console):
        """Removes selected ConsoleWidget and dynamically repositions remaining consoles."""
        if console in self.consoles:
            self.consoles.remove(console)
            console.destroy()
            
            # Re-enable add button if space is free
            if len(self.consoles) < 4:
                self.add_btn.configure(state=tk.NORMAL, bg="#007bff")
            
            self.rebuild_layout()

    def cycle_layout(self):
        """Cycles layout mode and triggers layout updates."""
        self.current_layout_idx = (self.current_layout_idx + 1) % len(self.layout_modes)
        mode = self.layout_modes[self.current_layout_idx]
        self.layout_btn.configure(text=f"🔄 Layout: {mode}")
        self.rebuild_layout()

    def toggle_always_on_top(self):
        """Toggles topmost state window attribute."""
        self.always_on_top = not self.always_on_top
        self.wm_attributes("-topmost", self.always_on_top)
        
        if self.always_on_top:
            self.top_btn.configure(text="📌 Always on Top: ON", bg="#28a745", activebackground="#218838")
        else:
            self.top_btn.configure(text="📌 Always on Top: OFF", bg="#495057", activebackground="#343a40")

    def rebuild_layout(self):
        """Recalculates grid layouts and grid scaling weight options for active consoles."""
        # Reset existing grid placements
        for c in self.consoles:
            c.grid_forget()

        # Reset row/column weights
        for r in range(4):
            self.container.grid_rowconfigure(r, weight=0)
            self.container.grid_columnconfigure(r, weight=0)

        n = len(self.consoles)
        if n == 0:
            return

        mode = self.layout_modes[self.current_layout_idx]

        if mode == "Vertical":
            # Stack all consoles on top of each other
            for idx, console in enumerate(self.consoles):
                console.grid(row=idx, column=0, sticky="nsew", padx=3, pady=3)
                self.container.grid_rowconfigure(idx, weight=1)
            self.container.grid_columnconfigure(0, weight=1)

        elif mode == "Horizontal":
            # Align all consoles horizontally side-by-side
            for idx, console in enumerate(self.consoles):
                console.grid(row=0, column=idx, sticky="nsew", padx=3, pady=3)
                self.container.grid_columnconfigure(idx, weight=1)
            self.container.grid_rowconfigure(0, weight=1)

        elif mode == "Mixed":
            # Smart mixed splits
            if n == 1:
                # 1 Fullscreen
                self.consoles[0].grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
                self.container.grid_rowconfigure(0, weight=1)
                self.container.grid_columnconfigure(0, weight=1)
            elif n == 2:
                # 1x2 (Left / Right split)
                for idx, console in enumerate(self.consoles):
                    console.grid(row=0, column=idx, sticky="nsew", padx=3, pady=3)
                    self.container.grid_columnconfigure(idx, weight=1)
                self.container.grid_rowconfigure(0, weight=1)
            elif n == 3:
                # Split (Top Left, Top Right, Bottom Spanned)
                self.consoles[0].grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
                self.consoles[1].grid(row=0, column=1, sticky="nsew", padx=3, pady=3)
                self.consoles[2].grid(row=1, column=0, columnspan=2, sticky="nsew", padx=3, pady=3)
                
                self.container.grid_rowconfigure(0, weight=1)
                self.container.grid_rowconfigure(1, weight=1)
                self.container.grid_columnconfigure(0, weight=1)
                self.container.grid_columnconfigure(1, weight=1)
            elif n == 4:
                # 2x2 Grid Layout
                self.consoles[0].grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
                self.consoles[1].grid(row=0, column=1, sticky="nsew", padx=3, pady=3)
                self.consoles[2].grid(row=1, column=0, sticky="nsew", padx=3, pady=3)
                self.consoles[3].grid(row=1, column=1, sticky="nsew", padx=3, pady=3)
                
                self.container.grid_rowconfigure(0, weight=1)
                self.container.grid_rowconfigure(1, weight=1)
                self.container.grid_columnconfigure(0, weight=1)
                self.container.grid_columnconfigure(1, weight=1)

    def on_close(self):
        """Shut down handler to disconnect and close active serial handles and worker threads."""
        for c in list(self.consoles):
            try:
                c.disconnect()
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    app = SerialMultiTool()
    app.mainloop()
