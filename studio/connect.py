"""Connection dialog: an ~/.ssh/config profile, or host / port / user / key (USB preset), a connection test, and a
one-time key setup where ssh asks for the tablet's password in its own terminal window (never in this app)."""
import os
import platform
import shlex
import subprocess
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout)

from .common import NO_WINDOW, ctl

DEFAULT_KEY = os.path.join(os.path.expanduser("~"), ".ssh", "id_ed25519_rmpp_studio")


def label(conn):
    return ctl.Tablet.from_conn(conn).describe() if conn else "not set"


def open_terminal(cmd):
    """Run a shell command in a new terminal window (for ssh's password prompt)."""
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["cmd", "/c", cmd + " & echo. & pause"], creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif system == "Darwin":
        script = cmd.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{script}"'])
    else:
        for term in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["konsole", "-e"], ["xterm", "-e"]):
            try:
                subprocess.Popen(term + ["sh", "-c", cmd + "; echo; read -p 'Press Enter to close' x"])
                return
            except OSError:
                continue
        raise OSError("no terminal emulator found")


class ConnectDialog(QDialog):
    tested = Signal(str)

    def __init__(self, parent, conn=None, first_run=False):
        super().__init__(parent)
        self.setWindowTitle("Connect to the tablet")
        self.result_conn = None
        conn = dict(conn or {})
        self.hosts = sorted(ctl.ssh_config_hosts(), key=lambda h: (not ctl.looks_like_tablet(h), h["alias"].lower()))
        lay = QVBoxLayout(self)
        if first_run:
            t = QLabel("<b style='font-size:14pt'>Welcome to rmpp-studio</b><br>Choose how to reach your reMarkable "
                       "Paper Pro over SSH (developer mode must be on). You can change this later "
                       "(Tablet ▸ Connection).")
            t.setWordWrap(True)
            lay.addWidget(t)

        self.rb_profile = QRadioButton("Profile from ~/.ssh/config")
        self.rb_direct = QRadioButton("Direct")
        g1 = QGroupBox()
        v1 = QVBoxLayout(g1)
        v1.addWidget(self.rb_profile)
        self.profile = QComboBox()
        for h in self.hosts:
            target = h["hostname"] or h["alias"]
            if h["user"]:
                target = f"{h['user']}@{target}"
            if h["port"]:
                target += f":{h['port']}"
            self.profile.addItem(f"{h['alias']}   ({target})", h["alias"])
        if not self.hosts:
            self.profile.addItem("(no Host entries in ~/.ssh/config)", "")
        v1.addWidget(self.profile)
        lay.addWidget(g1)

        g2 = QGroupBox()
        v2 = QVBoxLayout(g2)
        v2.addWidget(self.rb_direct)
        form = QFormLayout()
        hrow = QHBoxLayout()
        self.host = QLineEdit(conn.get("host") or ctl.USB_HOST)
        usb = QPushButton("USB cable")
        usb.clicked.connect(lambda: self.host.setText(ctl.USB_HOST))
        hrow.addWidget(self.host)
        hrow.addWidget(usb)
        form.addRow("Host / IP", hrow)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(conn.get("port") or 22))
        form.addRow("Port", self.port)
        self.user = QLineEdit(conn.get("user") or "root")
        form.addRow("User", self.user)
        krow = QHBoxLayout()
        self.key = QLineEdit(conn.get("key") or (DEFAULT_KEY if os.path.exists(DEFAULT_KEY) else ""))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_key)
        krow.addWidget(self.key)
        krow.addWidget(browse)
        form.addRow("Key file", krow)
        v2.addLayout(form)
        self.setup_btn = QPushButton("Set up key login (asks for the tablet's password once)…")
        self.setup_btn.clicked.connect(self.setup_key)
        v2.addWidget(self.setup_btn)
        hint = QLabel("With developer mode on, the root password is shown on the tablet under Settings ▸ Help ▸ "
                      "About (Copyrights and licenses). USB cable: 10.11.99.1; Wi-Fi: the IP from Settings ▸ Wi-Fi.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#aaa")
        v2.addWidget(hint)
        lay.addWidget(g2)
        self.direct_widgets = [self.host, usb, self.port, self.user, self.key, browse, self.setup_btn]

        trow = QHBoxLayout()
        test = QPushButton("Test connection")
        test.clicked.connect(self.test)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        trow.addWidget(test)
        trow.addWidget(self.status, 1)
        lay.addLayout(trow)
        self.tested.connect(self.status.setText)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        mode = conn.get("mode") or ("profile" if any(map(ctl.looks_like_tablet, self.hosts)) else "direct")
        (self.rb_profile if mode == "profile" else self.rb_direct).setChecked(True)
        alias = conn.get("alias") or next((h["alias"] for h in self.hosts if ctl.looks_like_tablet(h)), "")
        i = self.profile.findData(alias)
        if i >= 0:
            self.profile.setCurrentIndex(i)
        self.rb_profile.toggled.connect(self.on_mode)
        self.on_mode()
        self.resize(560, 0)

    def on_mode(self):
        direct = self.rb_direct.isChecked()
        self.profile.setEnabled(not direct)
        for w in self.direct_widgets:
            w.setEnabled(direct)

    def browse_key(self):
        p, _ = QFileDialog.getOpenFileName(self, "Private key file", os.path.join(os.path.expanduser("~"), ".ssh"))
        if p:
            self.key.setText(p)

    def conn(self):
        if self.rb_profile.isChecked():
            alias = self.profile.currentData()
            return {"mode": "profile", "alias": alias} if alias else None
        return {"mode": "direct", "host": self.host.text().strip(), "port": self.port.value(),
                "user": self.user.text().strip() or "root", "key": self.key.text().strip()}

    def test(self):
        c = self.conn()
        if not c:
            self.status.setText("pick a profile")
            return
        self.status.setText("testing …")

        def go():
            ok, msg = ctl.Tablet.from_conn(c).probe()
            self.tested.emit(("✔ " if ok else "✘ ") + msg)
        threading.Thread(target=go, daemon=True).start()

    def setup_key(self):
        key = self.key.text().strip() or DEFAULT_KEY
        host, user, port = self.host.text().strip(), self.user.text().strip() or "root", self.port.value()
        if not host:
            return
        if not os.path.exists(key):
            os.makedirs(os.path.dirname(key), exist_ok=True)
            r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "rmpp-studio", "-f", key],
                               capture_output=True, creationflags=NO_WINDOW)
            if r.returncode:
                QMessageBox.critical(self, "Key", r.stderr.decode(errors="replace"))
                return
        self.key.setText(key)
        remote = "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys; echo; echo Key installed."
        if platform.system() == "Windows":
            cmd = f'ssh -p {port} -o StrictHostKeyChecking=accept-new {user}@{host} "{remote}" < "{key}.pub"'
        else:
            cmd = (f"ssh -p {port} -o StrictHostKeyChecking=accept-new {user}@{host} {shlex.quote(remote)} "
                   f"< {shlex.quote(key + '.pub')}")
        QMessageBox.information(self, "Key login", "A terminal window opens next: type the tablet's root password "
                                "there (it is not shown while typing). Then press Test connection here.")
        try:
            open_terminal(cmd)
        except OSError as e:
            QMessageBox.critical(self, "Key login", f"{e}\n\nRun this yourself:\n{cmd}")

    def save(self):
        c = self.conn()
        if not c or (c["mode"] == "direct" and not c["host"]):
            QMessageBox.warning(self, "Connection", "Pick a profile or enter a host.")
            return
        self.result_conn = c
        self.accept()
