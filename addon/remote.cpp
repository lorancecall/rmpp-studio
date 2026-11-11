// rmpp-remote add-on: loaded into xochitl with LD_PRELOAD (rmpp-preload). It lets a developer (or a script over SSH)
// look at and drive the UI:
//   - screenshots of the QQuickWindow (grabWindow) and timed frame recording,
//   - a dump / search of the visible QML items with their screen rectangles (to tap them with real input),
//   - text and key input to the focused item (QInputMethodEvent / QKeyEvent),
//   - the last pointer events Qt saw (to check where injected pen/touch input lands).
//
// Commands arrive on the abstract unix socket "@rmpp-remote" (one request line, reply until close). The tablet-side
// `rmpp-remote ui <command>` binary is the client. Everything runs on the GUI thread (QSocketNotifier), so only
// QtCore/QtGui/QtQuick are needed.
#include <atomic>
#include <functional>

#include <dlfcn.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <fcntl.h>
#include <cerrno>
#include <cstring>

#include <QtCore/QCoreApplication>
#include <QtCore/QCryptographicHash>
#include <QtCore/QDateTime>
#include <QtCore/QDir>
#include <QtCore/QElapsedTimer>
#include <QtCore/QFile>
#include <QtCore/QFileInfo>
#include <QtCore/QMetaMethod>
#include <QtCore/QMetaProperty>
#include <QtCore/QMetaType>
#include <QtCore/QPointer>
#include <QtCore/QSocketNotifier>
#include <QtCore/QTextStream>
#include <QtCore/QTimer>
#include <QtGui/QGuiApplication>
#include <QtGui/QImage>
#include <QtGui/QInputMethodEvent>
#include <QtGui/QKeyEvent>
#include <QtGui/QKeySequence>
#include <QtGui/QPixmap>
#include <QtGui/QPointingDevice>
#include <QtGui/QScreen>
#include <QtGui/QWindow>
#include <QtQuick/QQuickItem>
#include <QtQuick/QQuickWindow>

// ---------- watch xochitl's EPFramebuffer through its signals ----------
// xochitl's e-paper framebuffer (EPFramebuffer, the source Screen Share reads from) has no parent and is not in the
// object tree. Every signal emission goes through QMetaObject::activate(sender, metaObject, index, argv), which
// xochitl calls through the dynamic linker, so this preloaded library interposes it: one pointer compare per
// signal, then the real function.
namespace rmpptester {
std::atomic<QObject *> g_epfb{nullptr};
std::atomic<const QMetaObject *> g_epfbMeta{nullptr};
std::atomic<int> g_lookups{0};
std::atomic<long> g_signalCount[64];
}

void QMetaObject::activate(QObject *sender, const QMetaObject *m, int local_signal_index, void **argv) {
    using Fn = void (*)(QObject *, const QMetaObject *, int, void **);
    static Fn real = reinterpret_cast<Fn>(dlsym(RTLD_NEXT, "_ZN11QMetaObject8activateEP7QObjectPKS_iPPv"));
    using namespace rmpptester;
    const QMetaObject *ep = g_epfbMeta.load(std::memory_order_relaxed);
    if (!ep && m) {   // until found: compare the class name (first letter first, so this stays cheap)
        const char *cn = m->className();
        if (cn[0] == 'E' && !qstrcmp(cn, "EPFramebuffer")) g_epfbMeta.store(ep = m);
    }
    if (ep && m == ep) {
        g_epfb.store(sender, std::memory_order_relaxed);
        if (local_signal_index >= 0 && local_signal_index < 64)
            g_signalCount[local_signal_index].fetch_add(1, std::memory_order_relaxed);
    }
    real(sender, m, local_signal_index, argv);
}

namespace {

const char kSockName[] = "rmpp-remote";   // abstract namespace

// ---------- helpers ----------

QQuickWindow *mainWindow() {
    QQuickWindow *best = nullptr;
    for (QWindow *w : QGuiApplication::allWindows()) {
        auto *qw = qobject_cast<QQuickWindow *>(w);
        if (!qw || !qw->isVisible()) continue;
        if (!best || qw->width() * qw->height() > best->width() * best->height()) best = qw;
    }
    return best;
}

QString itemText(QQuickItem *i) {
    for (const char *p : {"text", "label", "title", "placeholderText"}) {
        const QVariant v = i->property(p);
        if (v.isValid() && v.canConvert<QString>()) {
            const QString s = v.toString();
            if (!s.isEmpty()) return s;
        }
    }
    return QString();
}

QString itemIcon(QQuickItem *i) {
    for (const char *p : {"iconSource", "icon", "source"}) {
        const QVariant v = i->property(p);
        if (v.isValid() && (v.typeId() == QMetaType::QUrl || v.typeId() == QMetaType::QString)) {
            const QString s = v.toString();
            if (!s.isEmpty()) return s;
        }
    }
    return QString();
}

bool effectivelyVisible(QQuickItem *i) {
    for (QQuickItem *p = i; p; p = p->parentItem())
        if (!p->isVisible() || p->opacity() <= 0.01) return false;
    return true;
}

QRectF sceneRect(QQuickItem *i) { return i->mapRectToScene(QRectF(0, 0, i->width(), i->height())); }

QString describe(QQuickItem *i) {
    const QRectF r = sceneRect(i);
    QString cls = QString::fromLatin1(i->metaObject()->className());
    cls = cls.section(QStringLiteral("_QML"), 0, 0);
    QString s = QStringLiteral("%1,%2 %3x%4 %5").arg(qRound(r.x())).arg(qRound(r.y())).arg(qRound(r.width()))
                    .arg(qRound(r.height())).arg(cls);
    if (!i->objectName().isEmpty()) s += QStringLiteral(" #") + i->objectName();
    const QString t = itemText(i);
    if (!t.isEmpty()) s += QStringLiteral(" \"") + t.left(60).replace(QLatin1Char('\n'), QLatin1Char(' ')) + QLatin1Char('"');
    const QString ic = itemIcon(i);
    if (!ic.isEmpty()) s += QStringLiteral(" icon=") + ic.section(QLatin1Char('/'), -1);
    if (i->hasActiveFocus()) s += QStringLiteral(" [focus]");
    return s;
}

void walk(QQuickItem *root, const std::function<void(QQuickItem *, int)> &fn, int depth = 0) {
    if (!root || depth > 300 || !root->isVisible() || root->opacity() <= 0.01) return;
    fn(root, depth);
    // children in paint order, so later entries are on top
    QList<QQuickItem *> kids = root->childItems();
    std::stable_sort(kids.begin(), kids.end(), [](QQuickItem *a, QQuickItem *b) { return a->z() < b->z(); });
    for (QQuickItem *k : kids) walk(k, fn, depth + 1);
}

// ---------- pointer log (calibration / debugging) ----------

struct PointerLog : QObject {
    QStringList lines;
    bool eventFilter(QObject *o, QEvent *e) override {
        const char *kind = nullptr;
        switch (e->type()) {
        case QEvent::TabletPress: kind = "tablet-press"; break;
        case QEvent::TabletRelease: kind = "tablet-release"; break;
        case QEvent::TouchBegin: kind = "touch-begin"; break;
        case QEvent::TouchEnd: kind = "touch-end"; break;
        case QEvent::MouseButtonPress: kind = "mouse-press"; break;
        case QEvent::MouseButtonRelease: kind = "mouse-release"; break;
        default: break;
        }
        if (kind && qobject_cast<QWindow *>(o)) {
            // never log the passcode screen (PinKeyboard has the focus there)
            auto *qw = qobject_cast<QQuickWindow *>(o);
            if (qw && qw->activeFocusItem() && QByteArray(qw->activeFocusItem()->metaObject()->className()).contains("Pin")) {
                lines.clear();
                return false;
            }
            auto *pe = static_cast<QPointerEvent *>(e);
            QString s = QStringLiteral("%1 %2").arg(QDateTime::currentMSecsSinceEpoch()).arg(QLatin1String(kind));
            for (const QEventPoint &p : pe->points())
                s += QStringLiteral(" %1,%2 p=%3").arg(p.scenePosition().x(), 0, 'f', 1).arg(p.scenePosition().y(), 0, 'f', 1)
                         .arg(p.pressure(), 0, 'f', 2);
            if (pe->pointingDevice()) s += QStringLiteral(" dev=") + pe->pointingDevice()->name();
            lines << s;
            while (lines.size() > 40) lines.removeFirst();
        }
        return false;
    }
};
PointerLog *g_log = nullptr;

// ---------- capture ----------

// xochitl's Qt has no PNG writer plugin, so encode PNG here (zlib via qCompress): 8-bit RGB (the Paper Pro has a
// colour panel) or 8-bit grayscale (smaller files).
quint32 crc32(const QByteArray &a) {
    static quint32 table[256];
    static bool init = false;
    if (!init) {
        for (quint32 n = 0; n < 256; ++n) {
            quint32 c = n;
            for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
            table[n] = c;
        }
        init = true;
    }
    quint32 c = 0xffffffffu;
    for (char ch : a) c = table[(c ^ quint8(ch)) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

void be32(QByteArray &a, quint32 v) {
    a.append(char(v >> 24)).append(char(v >> 16)).append(char(v >> 8)).append(char(v));
}

void chunk(QByteArray &out, const char *type, const QByteArray &data) {
    be32(out, quint32(data.size()));
    QByteArray td = QByteArray(type, 4) + data;
    out += td;
    be32(out, crc32(td));
}

bool savePng(const QImage &img, const QString &path, int level = 3) {
    const bool rgb = img.format() == QImage::Format_RGB888;
    const int w = img.width(), h = img.height(), bpp = rgb ? 3 : 1;
    QByteArray raw;
    raw.reserve((w * bpp + 1) * h);
    for (int y = 0; y < h; ++y) {
        raw.append('\0');   // filter: none
        raw.append(reinterpret_cast<const char *>(img.constScanLine(y)), w * bpp);
    }
    QByteArray z = qCompress(raw, level).mid(4);   // drop Qt's length prefix -> plain zlib stream
    QByteArray ihdr;
    be32(ihdr, quint32(w));
    be32(ihdr, quint32(h));
    ihdr.append(char(8)).append(char(rgb ? 2 : 0)).append(char(0)).append(char(0)).append(char(0));   // 8-bit RGB / gray
    QByteArray png("\x89PNG\r\n\x1a\n", 8);
    chunk(png, "IHDR", ihdr);
    chunk(png, "IDAT", z);
    chunk(png, "IEND", QByteArray());
    QFile f(path + QStringLiteral(".part"));
    if (!f.open(QIODevice::WriteOnly) || f.write(png) != png.size()) return false;
    f.close();
    QFile::remove(path);
    return QFile::rename(path + QStringLiteral(".part"), path);
}

// Capture source:
//   "fb"     (default) copy xochitl's e-paper framebuffer: the RGB32 QImage inside EPFramebuffer (found through the
//            QMetaObject::activate hook above). No extra render, so it cannot stall the e-paper pipeline.
//   "window" QQuickWindow::grabWindow() renders the scene again; frequent use stalls xochitl's e-paper updates
//            (README "Known issue"). Used for one shot when the framebuffer is not known yet.
//   "screen" QScreen::grabWindow(): returns nothing with the epaper platform plugin (kept for reference).
QString g_source = QStringLiteral("fb");

// the EPFramebuffer's RGB32 framebuffer image: found by comparing the words of the object with QImage's vtable
const QImage *framebufferImage() {
    static QObject *cachedFor = nullptr;
    static const QImage *cached = nullptr;
    QObject *fb = rmpptester::g_epfb.load();
    if (!fb) return nullptr;
    if (fb == cachedFor) return cached;
    const int w = fb->property("width").toInt(), h = fb->property("height").toInt();
    QImage probe(4, 4, QImage::Format_RGB32);
    const uintptr_t vtbl = *reinterpret_cast<const uintptr_t *>(&probe);
    const uintptr_t base = reinterpret_cast<uintptr_t>(fb);
    cached = nullptr;
    for (size_t off = 16; off < 1024; off += 8) {
        if (*reinterpret_cast<const uintptr_t *>(base + off) != vtbl) continue;
        const QImage *img = reinterpret_cast<const QImage *>(base + off);
        if (img->width() == w && img->height() == h && img->depth() == 32) { cached = img; break; }
    }
    cachedFor = fb;
    return cached;
}

// copy without touching the shared data's reference count (another thread owns the image)
bool copyFramebuffer(QImage *out, bool gray) {
    const QImage *src = framebufferImage();
    if (!src || src->isNull()) return false;
    QImage copy(src->width(), src->height(), src->format());
    const qsizetype bpl = qMin(src->bytesPerLine(), copy.bytesPerLine());
    for (int y = 0; y < src->height(); ++y) memcpy(copy.scanLine(y), src->constScanLine(y), bpl);
    *out = copy.convertToFormat(gray ? QImage::Format_Grayscale8 : QImage::Format_RGB888);
    return true;
}

long framebufferUpdates() {
    return rmpptester::g_signalCount[0].load(std::memory_order_relaxed);   // signal 0 = framebufferUpdated(QRect)
}

bool grab(QImage *out, bool gray = false) {
    if (g_source == QLatin1String("fb") && copyFramebuffer(out, gray)) return true;
    QQuickWindow *w = mainWindow();
    if (!w) return false;
    QImage img;
    if (g_source == QLatin1String("screen")) {
        QScreen *sc = w->screen() ? w->screen() : QGuiApplication::primaryScreen();
        if (sc) img = sc->grabWindow(0).toImage();
    } else {
        img = w->grabWindow();
    }
    if (img.isNull()) return false;
    *out = img.convertToFormat(gray ? QImage::Format_Grayscale8 : QImage::Format_RGB888);
    return true;
}

struct Recorder : QObject {
    QTimer timer;
    QString dir;
    QFile index;
    QByteArray lastHash;
    long lastUpdates = -1;
    int frames = 0, written = 0;
    qint64 t0 = 0;
    QString lastError;
    bool gray = false;

    Recorder() { connect(&timer, &QTimer::timeout, this, &Recorder::tick); }

    QString start(const QString &d, double fps, bool grayFrames = false) {
        if (timer.isActive()) return QStringLiteral("error: already recording to ") + dir;
        dir = d;
        QDir().mkpath(dir);
        index.setFileName(dir + QStringLiteral("/frames.txt"));
        if (!index.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text))
            return QStringLiteral("error: cannot write ") + index.fileName();
        frames = written = 0;
        gray = grayFrames;
        lastHash.clear();
        lastUpdates = -1;
        t0 = QDateTime::currentMSecsSinceEpoch();
        timer.start(qMax(50, int(1000.0 / qMax(0.1, fps))));
        tick();
        return QStringLiteral("ok recording %1 fps (%2) to %3").arg(fps).arg(gray ? "gray" : "color").arg(dir);
    }

    // one line per sample: "<ms since start> <file>" (file repeats when the screen did not change)
    void tick() {
        const qint64 t = QDateTime::currentMSecsSinceEpoch() - t0;
        if (g_source == QLatin1String("fb") && framebufferImage() && written > 0 && framebufferUpdates() == lastUpdates) {
            ++frames;   // nothing reached the panel since the last frame: repeat it without copying
            QTextStream(&index) << t << ' ' << QStringLiteral("f%1.png").arg(written - 1, 6, 10, QLatin1Char('0')) << '\n';
            index.flush();
            return;
        }
        lastUpdates = framebufferUpdates();
        QImage img;
        if (!grab(&img, gray)) return;
        const QByteArray h = QCryptographicHash::hash(
            QByteArrayView(reinterpret_cast<const char *>(img.constBits()), img.sizeInBytes()), QCryptographicHash::Md5);
        if (h != lastHash) {
            lastHash = h;
            const QString name = QStringLiteral("f%1.png").arg(written, 6, 10, QLatin1Char('0'));
            savePng(img, dir + QLatin1Char('/') + name, 1);   // fast level: frames are pulled and re-encoded
            ++written;
        }
        ++frames;
        QTextStream(&index) << t << ' ' << QStringLiteral("f%1.png").arg(written - 1, 6, 10, QLatin1Char('0')) << '\n';
        index.flush();
    }

    // "<ms> # <text>" in frames.txt: a caption (or any note) from this moment on; empty text clears it
    QString mark(const QString &text) {
        if (!timer.isActive()) return QStringLiteral("error: not recording");
        tick();
        QTextStream(&index) << (QDateTime::currentMSecsSinceEpoch() - t0) << " # " << text << '\n';
        index.flush();
        return QStringLiteral("ok");
    }

    QString stop() {
        if (!timer.isActive()) return QStringLiteral("error: not recording");
        tick();
        timer.stop();
        index.close();
        return QStringLiteral("ok %1 samples, %2 images in %3 (%4 s)").arg(frames).arg(written).arg(dir)
            .arg((QDateTime::currentMSecsSinceEpoch() - t0) / 1000.0, 0, 'f', 1);
    }
};
Recorder *g_rec = nullptr;

// ---------- input to the focused item ----------

QObject *focusTarget() {
    QQuickWindow *w = mainWindow();
    if (w && w->activeFocusItem()) return w->activeFocusItem();
    return QGuiApplication::focusObject();
}

QString sendText(const QString &text) {
    QObject *t = focusTarget();
    if (!t) return QStringLiteral("error: no focused item");
    QInputMethodEvent ev;
    ev.setCommitString(text);
    QCoreApplication::sendEvent(t, &ev);
    return QStringLiteral("ok sent %1 chars to %2").arg(text.size()).arg(QLatin1String(t->metaObject()->className()));
}

int keyCode(const QString &name) {
    static const QHash<QString, int> keys = {
        {"enter", Qt::Key_Return}, {"return", Qt::Key_Return}, {"backspace", Qt::Key_Backspace},
        {"delete", Qt::Key_Delete}, {"escape", Qt::Key_Escape}, {"esc", Qt::Key_Escape}, {"tab", Qt::Key_Tab},
        {"left", Qt::Key_Left}, {"right", Qt::Key_Right}, {"up", Qt::Key_Up}, {"down", Qt::Key_Down},
        {"home", Qt::Key_Home}, {"end", Qt::Key_End}, {"space", Qt::Key_Space}, {"pageup", Qt::Key_PageUp},
        {"pagedown", Qt::Key_PageDown}};
    const QString n = name.toLower();
    if (keys.contains(n)) return keys.value(n);
    if (n.size() == 1) return QKeySequence::fromString(n.toUpper())[0].key();
    return 0;
}

QString sendKey(const QString &spec) {
    QObject *t = focusTarget();
    if (!t) return QStringLiteral("error: no focused item");
    Qt::KeyboardModifiers mods;
    const QStringList parts = spec.split(QLatin1Char('+'));
    for (int i = 0; i + 1 < parts.size(); ++i) {
        const QString m = parts[i].toLower();
        if (m == QLatin1String("ctrl")) mods |= Qt::ControlModifier;
        else if (m == QLatin1String("shift")) mods |= Qt::ShiftModifier;
        else if (m == QLatin1String("alt")) mods |= Qt::AltModifier;
    }
    const int k = keyCode(parts.last());
    if (!k) return QStringLiteral("error: unknown key ") + parts.last();
    QString txt;
    if (k == Qt::Key_Return) txt = QStringLiteral("\r");
    else if (k == Qt::Key_Tab) txt = QStringLiteral("\t");
    else if (k == Qt::Key_Space) txt = QStringLiteral(" ");
    else if (parts.last().size() == 1 && !(mods & Qt::ControlModifier)) txt = parts.last();
    QKeyEvent press(QEvent::KeyPress, k, mods, txt), release(QEvent::KeyRelease, k, mods, txt);
    QCoreApplication::sendEvent(t, &press);
    QCoreApplication::sendEvent(t, &release);
    return QStringLiteral("ok key ") + spec;
}

// ---------- commands ----------

// "find" query: words separated by spaces must all match (case-insensitive) in the item's description;
// "#name" matches objectName exactly, "\"text\"" matches the text exactly.
QList<QQuickItem *> findItems(const QString &query) {
    QList<QQuickItem *> hits;
    QQuickWindow *w = mainWindow();
    if (!w) return hits;
    const QString q = query.trimmed();
    walk(w->contentItem(), [&](QQuickItem *i, int) {
        const QRectF r = sceneRect(i);
        if (r.width() < 1 || r.height() < 1) return;
        bool ok;
        if (q.startsWith(QLatin1Char('#'))) ok = i->objectName() == q.mid(1);
        else if (q.size() > 1 && q.startsWith(QLatin1Char('"')) && q.endsWith(QLatin1Char('"'))) ok = itemText(i) == q.mid(1, q.size() - 2);
        else {
            const QString d = describe(i);
            ok = true;
            for (const QString &word : q.split(QLatin1Char(' '), Qt::SkipEmptyParts))
                if (!d.contains(word, Qt::CaseInsensitive)) { ok = false; break; }
        }
        if (ok) hits << i;
    });
    return hits;
}

// visible items containing a scene point, top-most (last painted) first; full-window containers are left out
QList<QQuickItem *> itemsAt(const QPointF &p) {
    QList<QQuickItem *> out;
    QQuickWindow *w = mainWindow();
    if (!w) return out;
    walk(w->contentItem(), [&](QQuickItem *i, int) {
        const QRectF r = sceneRect(i);
        if (r.contains(p) && !(r.width() >= w->width() && r.height() >= w->height())) out.prepend(i);
    });
    return out;
}

QString command(const QString &line) {
    const QString cmd = line.section(QLatin1Char(' '), 0, 0);
    const QString arg = line.section(QLatin1Char(' '), 1).trimmed();
    QQuickWindow *w = mainWindow();
    if (cmd == QLatin1String("ping")) return QStringLiteral("ok");
    if (cmd == QLatin1String("pen")) {   // the active writing tool, so a PC preview can draw ink like the tablet
        if (!w) return QStringLiteral("error: no window");
        const auto menu = [&](const char *name) -> QQuickItem * {
            const auto hits = findItems(QStringLiteral("#") + QLatin1String(name));
            return hits.isEmpty() ? nullptr : hits.last();
        };
        for (const char *name : {"primaryPenMenu", "secondaryPenMenu"}) {
            QQuickItem *m = menu(name);
            if (!m || !m->property("selected").toBool()) continue;
            QObject *pen = m->property("pen").value<QObject *>();
            if (!pen) continue;
            return QStringLiteral("ok menu=%1 tool=%2 color=%3 code=%4 thickness=%5")
                .arg(QLatin1String(name).chopped(7))
                .arg(pen->property("tool").toString(), pen->property("color").toString())
                .arg(pen->property("colorCode").toUInt(), 8, 16, QLatin1Char('0'))
                .arg(pen->property("thickness").toDouble());
        }
        for (const char *name : {"eraserMenu", "selectionButton", "typingMenu"}) {
            QQuickItem *m = menu(name);
            if (m && m->property("selected").toBool())
                return QStringLiteral("ok menu=%1 tool=none").arg(QLatin1String(name));
        }
        return QStringLiteral("ok menu=none tool=none");
    }
    if (cmd == QLatin1String("epfb")) {   // what is known about xochitl's EPFramebuffer
        using namespace rmpptester;
        const QMetaObject *mo = g_epfbMeta.load();
        if (!mo) return QStringLiteral("error: no EPFramebuffer signal seen yet (draw something)");
        QString out = QStringLiteral("ok EPFramebuffer meta %1, instance %2\n")
                          .arg(quintptr(mo), 0, 16).arg(quintptr(g_epfb.load()), 0, 16);
        for (const QMetaObject *m = mo; m && qstrcmp(m->className(), "QObject"); m = m->superClass()) {
            out += QStringLiteral("[class %1]\n").arg(QLatin1String(m->className()));
            for (int i = m->propertyOffset(); i < m->propertyCount(); ++i)
                out += QStringLiteral("  prop %1 %2\n").arg(QLatin1String(m->property(i).typeName()),
                                                          QLatin1String(m->property(i).name()));
            int sig = 0;
            for (int i = m->methodOffset(); i < m->methodCount(); ++i) {
                const QMetaMethod mm = m->method(i);
                static const char *k[] = {"method", "signal", "slot", "ctor"};
                QString line = QStringLiteral("  %1 %2 %3").arg(QLatin1String(k[mm.methodType()]),
                                                               QLatin1String(mm.typeName()),
                                                               QLatin1String(mm.methodSignature()));
                if (mm.methodType() == QMetaMethod::Signal && m == mo) {
                    line += QStringLiteral("  (emitted %1x)").arg(sig < 64 ? g_signalCount[sig].load() : -1);
                    ++sig;
                }
                out += line + QLatin1Char('\n');
            }
        }
        return out;
    }
    if (cmd == QLatin1String("source")) {   // source [window|screen]
        if (arg == QLatin1String("fb") || arg == QLatin1String("window") || arg == QLatin1String("screen")) g_source = arg;
        else if (!arg.isEmpty()) return QStringLiteral("error: source fb|window|screen");
        return QStringLiteral("ok source ") + g_source;
    }
    if (cmd == QLatin1String("load")) {   // load <path.so> [arg]: run an experiment's rmpp_remote_exp(arg) in xochitl
        const QString so = arg.section(QLatin1Char(' '), 0, 0);
        void *h = dlopen(so.toUtf8().constData(), RTLD_NOW | RTLD_LOCAL);
        if (!h) return QStringLiteral("error: ") + QString::fromUtf8(dlerror());
        auto fn = reinterpret_cast<const char *(*)(const char *)>(dlsym(h, "rmpp_remote_exp"));
        if (!fn) return QStringLiteral("error: no rmpp_remote_exp in ") + so;
        const char *r = fn(arg.section(QLatin1Char(' '), 1).toUtf8().constData());
        return r ? QString::fromUtf8(r) : QStringLiteral("ok");
    }
    if (cmd == QLatin1String("info")) {
        if (!w) return QStringLiteral("error: no window");
        return QStringLiteral("ok window %1x%2 dpr %3 source %6 focus %4 recording %5")
            .arg(w->width()).arg(w->height()).arg(w->devicePixelRatio())
            .arg(w->activeFocusItem() ? describe(w->activeFocusItem()) : QStringLiteral("-"))
            .arg(g_rec->timer.isActive() ? g_rec->dir : QStringLiteral("no")).arg(g_source);
    }
    if (cmd == QLatin1String("shot")) {
        const bool gray = arg.endsWith(QLatin1String(" gray")) || arg == QLatin1String("gray");
        QString path = gray ? arg.chopped(4).trimmed() : arg;
        if (path.isEmpty()) path = QStringLiteral("/tmp/rmpp-remote/shot.png");
        QDir().mkpath(QFileInfo(path).absolutePath());
        QElapsedTimer et;
        et.start();
        QImage img;
        if (!grab(&img, gray)) return QStringLiteral("error: grab failed");
        const qint64 tg = et.elapsed();
        if (!savePng(img, path)) return QStringLiteral("error: cannot save ") + path;
        return QStringLiteral("ok %1 %2x%3 grab %4 ms total %5 ms").arg(path).arg(img.width()).arg(img.height())
            .arg(tg).arg(et.elapsed());
    }
    if (cmd == QLatin1String("rec")) {
        const QString sub = arg.section(QLatin1Char(' '), 0, 0);
        if (sub == QLatin1String("start")) {
            const QString dir = arg.section(QLatin1Char(' '), 1, 1);
            const double fps = arg.section(QLatin1Char(' '), 2, 2).toDouble();
            const bool gray = arg.section(QLatin1Char(' '), 3, 3) == QLatin1String("gray");
            return g_rec->start(dir.isEmpty() ? QStringLiteral("/tmp/rmpp-remote/rec") : dir, fps > 0 ? fps : 4, gray);
        }
        if (sub == QLatin1String("stop")) return g_rec->stop();
        if (sub == QLatin1String("mark")) return g_rec->mark(arg.section(QLatin1Char(' '), 1));
        return QStringLiteral("error: rec start [dir] [fps] | rec mark <text> | rec stop");
    }
    if (cmd == QLatin1String("tree") || cmd == QLatin1String("find")) {
        if (!w) return QStringLiteral("error: no window");
        QString out;
        if (cmd == QLatin1String("tree")) {
            const int maxDepth = arg.isEmpty() ? 300 : arg.toInt();
            walk(w->contentItem(), [&](QQuickItem *i, int d) {
                if (d <= maxDepth) out += QString(d, QLatin1Char(' ')) + describe(i) + QLatin1Char('\n');
            });
        } else {
            for (QQuickItem *i : findItems(arg)) out += describe(i) + QLatin1Char('\n');
            if (out.isEmpty()) return QStringLiteral("error: no match");
        }
        return out;
    }
    if (cmd == QLatin1String("center")) {
        // center of the top-most (last painted) visible match, only if nothing unrelated is painted over that point
        const auto hits = findItems(arg);
        if (hits.isEmpty()) return QStringLiteral("error: no match");
        QQuickItem *m = hits.last();
        const QPointF c = sceneRect(m).center();
        const auto under = itemsAt(c);
        if (!under.isEmpty() && under.first() != m && !m->isAncestorOf(under.first()) && !under.first()->isAncestorOf(m))
            return QStringLiteral("error: %1 is covered by %2").arg(describe(m), describe(under.first()));
        return QStringLiteral("%1 %2").arg(qRound(c.x())).arg(qRound(c.y()));
    }
    if (cmd == QLatin1String("prop")) {   // prop <name> <query>: property of the top-most match
        const QString name = arg.section(QLatin1Char(' '), 0, 0);
        const auto hits = findItems(arg.section(QLatin1Char(' '), 1));
        if (hits.isEmpty()) return QStringLiteral("error: no match");
        const QVariant v = hits.last()->property(name.toUtf8().constData());
        if (!v.isValid()) return QStringLiteral("error: no property ") + name;
        if (QObject *o = v.value<QObject *>()) return QLatin1String(o->metaObject()->className());
        return v.toString();
    }
    if (cmd == QLatin1String("props")) {   // props <query>: all properties of the top-most match
        const auto hits = findItems(arg);
        if (hits.isEmpty()) return QStringLiteral("error: no match");
        QQuickItem *m = hits.last();
        QString out;
        const QMetaObject *mo = m->metaObject();
        for (int i = QQuickItem::staticMetaObject.propertyCount(); i < mo->propertyCount(); ++i) {
            const QMetaProperty p = mo->property(i);
            out += QStringLiteral("%1 %2 = %3\n").arg(QLatin1String(p.typeName()), QLatin1String(p.name()),
                                                     p.read(m).toString().left(80));
        }
        return out;
    }
    if (cmd == QLatin1String("hit")) {   // items under a point, top-most first
        if (!w) return QStringLiteral("error: no window");
        const QPointF p(arg.section(QLatin1Char(' '), 0, 0).toDouble(), arg.section(QLatin1Char(' '), 1, 1).toDouble());
        QString out;
        for (QQuickItem *i : itemsAt(p)) out += describe(i) + QLatin1Char('\n');
        return out.isEmpty() ? QStringLiteral("error: nothing") : out;
    }
    if (cmd == QLatin1String("text")) return sendText(arg);
    if (cmd == QLatin1String("key")) return sendKey(arg);
    if (cmd == QLatin1String("pointers")) return g_log->lines.join(QLatin1Char('\n'));
    if (cmd == QLatin1String("help"))
        return QStringLiteral("ping | info | pen | source [fb|window|screen] | load <exp.so> [arg] | shot [path.png] [gray] | rec start [dir] [fps] [gray] | rec mark <text> | rec stop | tree [depth] | "
                              "find <query> | center <query> | hit <x> <y> | prop <name> <query> | props <query> | text <utf8> | key [ctrl+]<name> | pointers");
    return QStringLiteral("error: unknown command ") + cmd;
}

// ---------- socket server ----------

void serveClient(int fd) {
    // short requests: read until newline (blocking with a timeout, the client writes the line at once)
    timeval tv{2, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    QByteArray req;
    char buf[4096];
    while (!req.contains('\n') && req.size() < 65536) {
        const ssize_t n = read(fd, buf, sizeof buf);
        if (n <= 0) break;
        req.append(buf, n);
    }
    const QString line = QString::fromUtf8(req.left(req.indexOf('\n') < 0 ? req.size() : req.indexOf('\n'))).trimmed();
    QByteArray reply = command(line).toUtf8();
    if (!reply.endsWith('\n')) reply += '\n';
    for (qsizetype off = 0; off < reply.size();) {
        const ssize_t n = write(fd, reply.constData() + off, reply.size() - off);
        if (n <= 0) break;
        off += n;
    }
    close(fd);
}

void startServer() {
    const int s = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (s < 0) return;
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    memcpy(addr.sun_path + 1, kSockName, sizeof kSockName - 1);   // abstract: leading NUL
    const socklen_t len = offsetof(sockaddr_un, sun_path) + 1 + sizeof kSockName - 1;
    if (bind(s, reinterpret_cast<sockaddr *>(&addr), len) < 0 || listen(s, 8) < 0) {
        qWarning("[rmpp-remote] cannot listen: %s", strerror(errno));
        close(s);
        return;
    }
    auto *n = new QSocketNotifier(s, QSocketNotifier::Read, QCoreApplication::instance());
    QObject::connect(n, &QSocketNotifier::activated, n, [s] {
        const int c = accept4(s, nullptr, nullptr, SOCK_CLOEXEC);
        if (c < 0) return;
        const int fl = fcntl(c, F_GETFL);
        fcntl(c, F_SETFL, fl & ~O_NONBLOCK);
        serveClient(c);
    });
}

void init() {
    auto *app = QCoreApplication::instance();
    g_log = new PointerLog;
    g_log->setParent(app);
    app->installEventFilter(g_log);
    g_rec = new Recorder;
    g_rec->setParent(app);
    startServer();
    qWarning("[rmpp-remote] loaded");
}

} // namespace

Q_COREAPP_STARTUP_FUNCTION(init)
