import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPlainTextEdit, QPushButton, QLineEdit, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QTextCursor
import paramiko
import time

class SSHClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Interactive SSH Client")
        self.setGeometry(100, 100, 800, 600)

        # Main Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.central_widget.setLayout(self.layout)

        # Host and credentials
        self.host_input = QLineEdit(placeholderText="Host (e.g., 192.168.1.1)")
        self.username_input = QLineEdit(placeholderText="Username")
        self.password_input = QLineEdit(placeholderText="Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.layout.addWidget(self.host_input)
        self.layout.addWidget(self.username_input)
        self.layout.addWidget(self.password_input)

        # Connect Button
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.start_connection)
        self.layout.addWidget(self.connect_button)

        # Terminal Display
        self.terminal_display = TerminalDisplay()
        self.layout.addWidget(self.terminal_display)

        # SSH connection variables
        self.ssh_thread = None
        self.is_closing = False

    def start_connection(self):
        host = self.host_input.text()
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        # Start a background thread for the SSH connection
        self.ssh_thread = SSHConnectionThread(host, username, password)
        self.ssh_thread.output_received.connect(self.terminal_display.append_output)
        self.ssh_thread.connection_failed.connect(self.show_error)
        self.ssh_thread.connection_closed.connect(self.on_connection_closed)  # Handle disconnection
        self.ssh_thread.start()

        # Link terminal display to SSH thread for real-time input
        self.terminal_display.set_ssh_thread(self.ssh_thread)

    def show_error(self, message):
        if not self.is_closing:
            QMessageBox.critical(self, "Connection Error", message)

    def on_connection_closed(self):
        if not self.is_closing:
            QMessageBox.warning(self, "Connection Closed", "The SSH connection has been closed. Please reconnect.")

    def closeEvent(self, event):
        # Ensure the SSH thread exits gracefully on application close
        self.is_closing = True
        if self.ssh_thread:
            self.ssh_thread.close_connection()
            self.ssh_thread.wait()  # Wait for the thread to exit
        event.accept()


class TerminalDisplay(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)  # Terminal display should be read-only
        self.ssh_thread = None
        self.current_line_buffer = ""  # Initialize current line buffer

    def set_ssh_thread(self, ssh_thread):
        self.ssh_thread = ssh_thread

    def append_output(self, output):
        # Process each character in the output individually
        for char in output:
            if char == '\b':  # Handle backspace
                # Remove the last character from the buffer if possible
                self.current_line_buffer = self.current_line_buffer[:-1]
            elif char == '\n':  # Handle newline
                # Append the completed line to the display and clear the buffer
                self.appendPlainText(self.current_line_buffer.rstrip())
                self.current_line_buffer = ""  # Clear buffer after appending line
            else:
                # Add character to the buffer for inline display
                self.current_line_buffer += char

        # Temporarily display the current line being typed inline, avoiding extra newlines
        if self.current_line_buffer:
            last_line_position = self.toPlainText().rfind('\n')
            # Update only the current line without additional line feeds
            self.setPlainText(self.toPlainText()[:last_line_position + 1] + self.current_line_buffer)

        # Move cursor to the end of the display to keep scrolling in view
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.ensureCursorVisible()

    def keyPressEvent(self, event):
        if self.ssh_thread and self.ssh_thread.channel:
            if event.key() == Qt.Key.Key_Backspace:
                # Send backspace character to SSH server
                self.ssh_thread.send_input('\x08')
            else:
                # Send regular character to SSH server
                text = event.text()
                self.ssh_thread.send_input(text)


class SSHConnectionThread(QThread):
    output_received = pyqtSignal(str)
    connection_failed = pyqtSignal(str)
    connection_closed = pyqtSignal()  # New signal for connection closure

    def __init__(self, host, username, password):
        super().__init__()
        self.host = host
        self.username = username
        self.password = password
        self.ssh_client = None
        self.channel = None
        self.keep_running = True  # Control flag for graceful shutdown

    def run(self):
        try:
            # Establish SSH connection
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(self.host, username=self.username, password=self.password)

            # Open an interactive session
            self.channel = self.ssh_client.invoke_shell()
            self.channel.settimeout(0.1)

            # Read output continuously
            while self.keep_running:
                if self.channel.recv_ready():
                    output = self.channel.recv(1024).decode()
                    self.output_received.emit(output)
                time.sleep(0.1)
        except Exception as e:
            if self.keep_running:
                self.connection_failed.emit(str(e))
        finally:
            self.close_connection()  # Ensure closure when the thread stops
            self.connection_closed.emit()  # Notify that the connection is closed

    def send_input(self, text):
        try:
            if self.channel and not self.channel.closed:
                self.channel.send(text)
            else:
                raise OSError("Socket is closed")
        except OSError:
            self.connection_closed.emit()  # Emit connection closed signal on error

    def close_connection(self):
        self.keep_running = False
        if self.channel:
            self.channel.close()
        if self.ssh_client:
            self.ssh_client.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SSHClient()
    window.show()
    sys.exit(app.exec())
