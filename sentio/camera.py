"""Linux single-plane V4L2 MMAP capture. No conversion, recording, or fallback.

The small ctypes ABI follows linux/videodev2.h; tests compare it with the
installed C header. Only YUYV 640x480 at 30 FPS is accepted.
"""

import ctypes as C
import errno
import fcntl
import glob
import mmap
import os
import select
import time

from .inputs import extract_y

U32 = C.c_uint32


class Capability(C.Structure):
    _fields_ = [("driver", C.c_char * 16), ("card", C.c_char * 32),
                ("bus_info", C.c_char * 32), ("version", U32), ("capabilities", U32),
                ("device_caps", U32), ("reserved", U32 * 3)]


class PixelFormat(C.Structure):
    _fields_ = [(x, U32) for x in ("width", "height", "pixelformat", "field", "bytesperline",
                                  "sizeimage", "colorspace", "priv", "flags", "ycbcr_enc",
                                  "quantization", "xfer_func")]


class FormatUnion(C.Union):
    _fields_ = [("pix", PixelFormat), ("raw", C.c_uint8 * 200), ("alignment", C.c_void_p)]


class Format(C.Structure):
    _fields_ = [("type", U32), ("fmt", FormatUnion)]


class Fraction(C.Structure):
    _fields_ = [("numerator", U32), ("denominator", U32)]


class CaptureParameters(C.Structure):
    _fields_ = [("capability", U32), ("capturemode", U32), ("timeperframe", Fraction),
                ("extendedmode", U32), ("readbuffers", U32), ("reserved", U32 * 4)]


class StreamUnion(C.Union):
    _fields_ = [("capture", CaptureParameters), ("raw", C.c_uint8 * 200)]


class StreamParameters(C.Structure):
    _fields_ = [("type", U32), ("parm", StreamUnion)]


class RequestBuffers(C.Structure):
    _fields_ = [("count", U32), ("type", U32), ("memory", U32), ("capabilities", U32),
                ("flags", C.c_uint8), ("reserved", C.c_uint8 * 3)]


class Timeval(C.Structure):
    _fields_ = [("seconds", C.c_long), ("microseconds", C.c_long)]


class Timecode(C.Structure):
    _fields_ = [("type", U32), ("flags", U32), ("frames", C.c_uint8),
                ("seconds", C.c_uint8), ("minutes", C.c_uint8), ("hours", C.c_uint8),
                ("userbits", C.c_uint8 * 4)]


class Memory(C.Union):
    _fields_ = [("offset", U32), ("userptr", C.c_ulong), ("planes", C.c_void_p), ("fd", C.c_int32)]


class Buffer(C.Structure):
    _fields_ = [("index", U32), ("type", U32), ("bytesused", U32), ("flags", U32),
                ("field", U32), ("timestamp", Timeval), ("timecode", Timecode),
                ("sequence", U32), ("memory", U32), ("m", Memory), ("length", U32),
                ("reserved2", U32), ("request_fd", C.c_int32)]


class Control(C.Structure):
    _fields_ = [("id", U32), ("value", C.c_int32)]


def request(number, structure, direction=3):
    return (direction << 30) | (C.sizeof(structure) << 16) | (ord("V") << 8) | number


QUERYCAP = request(0, Capability, 2)
G_FMT, S_FMT = request(4, Format), request(5, Format)
REQBUFS = request(8, RequestBuffers)
QUERYBUF, QBUF, DQBUF = (request(n, Buffer) for n in (9, 15, 17))
STREAMON, STREAMOFF = (request(n, C.c_int, 1) for n in (18, 19))
G_PARM, S_PARM = request(21, StreamParameters), request(22, StreamParameters)
G_CTRL, S_CTRL = request(27, Control), request(28, Control)
YUYV = int.from_bytes(b"YUYV", "little")
CONTROL_IDS = dict(brightness=0x00980900, contrast=0x00980901, saturation=0x00980902,
                   gain=0x00980913, power_line_frequency=0x00980918,
                   sharpness=0x0098091B, backlight_compensation=0x0098091C,
                   exposure_auto=0x009A0901, exposure_auto_priority=0x009A0903,
                   exposure_absolute=0x009A0902, focus_auto=0x009A090C,
                   focus_absolute=0x009A090A, white_balance_auto=0x0098090C,
                   white_balance_temperature=0x0098091A, zoom_absolute=0x009A090D,
                   pan_absolute=0x009A0908, tilt_absolute=0x009A0909)


def ioctl(fd, code, value):
    fcntl.ioctl(fd, code, value, True)
    return value


def identity(fd, path):
    cap = ioctl(fd, QUERYCAP, Capability())
    flags = cap.device_caps if cap.capabilities & 0x80000000 else cap.capabilities
    if not flags & 1 or not flags & 0x04000000:
        raise ValueError("device does not support single-plane streaming video capture")
    return dict(path=path, card=cap.card.decode(errors="replace"),
                bus=cap.bus_info.decode(errors="replace"), driver=cap.driver.decode(errors="replace"))


def devices():
    result, seen = [], set()
    for path in sorted(glob.glob("/dev/v4l/by-id/*")) + sorted(glob.glob("/dev/video*")):
        real = os.path.realpath(path)
        if real in seen:
            continue
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            try:
                result.append(identity(fd, path))
                seen.add(real)
            finally:
                os.close(fd)
        except (OSError, ValueError):
            continue
    return result


def choose_device(path=None):
    if path:
        return path
    candidates = [d for d in devices() if "c922" in d["card"].lower()]
    if len(candidates) != 1:
        raise ValueError("Select a capture device with --device; use --list-devices (no unique C922 found)")
    return candidates[0]["path"]


def validate_mode(fmt, parm):
    pix, rate = fmt.fmt.pix, parm.parm.capture.timeperframe
    fps = rate.denominator / rate.numerator if rate.numerator else 0
    if (pix.width, pix.height, pix.pixelformat) != (640, 480, YUYV) or abs(fps - 30) > 0.01:
        fourcc = int(pix.pixelformat).to_bytes(4, "little").decode(errors="replace")
        raise ValueError(f"Requested YUYV 640x480 @30; negotiated {fourcc} {pix.width}x{pix.height} @{fps:g}. Refusing fallback.")
    if pix.bytesperline < 1280 or pix.sizeimage < pix.bytesperline * 480 or pix.field != 1:
        raise ValueError("invalid stride/size or non-progressive negotiated format")
    return dict(width=640, height=480, fourcc="YUYV", fps=fps, stride=pix.bytesperline,
                sizeimage=pix.sizeimage, colorspace=pix.colorspace,
                quantization=pix.quantization, transfer=pix.xfer_func)


class V4L2Camera:
    def __init__(self, path=None, exposure=156):
        if type(exposure) is not int or not 1 <= exposure <= 300:
            raise ValueError("exposure must be 1..300 units of 100 microseconds")
        self.fd = None
        self.buffers = []
        self.streaming = False
        self.saved_controls = []
        self.warnings = []
        self.controls = {}
        self.frames = self.driver_drops = self.discarded = self.bad_frames = 0
        self.previous_sequence = None
        self.timestamp_kind = "unobserved"
        try:
            self.path = choose_device(path)
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
            self.info = identity(self.fd, self.path)
            # Restore changed controls in reverse order on every exit path.
            for name, cid, value in (
                ("exposure_auto", 0x009A0901, 1),
                ("exposure_auto_priority", 0x009A0903, 0),
                ("exposure_absolute", 0x009A0902, exposure),
                ("focus_auto", 0x009A090C, 0),
                ("white_balance_auto", 0x0098090C, 0),
                ("white_balance_temperature", 0x0098091A, 4500),
            ):
                try:
                    old = ioctl(self.fd, G_CTRL, Control(cid, 0)).value
                    # Save before attempting SET: partial driver failures can mutate.
                    self.saved_controls.append((name, cid, old))
                    ioctl(self.fd, S_CTRL, Control(cid, value))
                    actual = ioctl(self.fd, G_CTRL, Control(cid, 0)).value
                    self.controls[name] = dict(requested=value, actual=actual, original=old)
                    if actual != value:
                        self.warnings.append(f"{name}: requested {value}, actual {actual}")
                except OSError as exc:
                    self.warnings.append(f"{name}: {exc}")
            fmt = Format(type=1)
            fmt.fmt.pix = PixelFormat(width=640, height=480, pixelformat=YUYV, field=1)
            ioctl(self.fd, S_FMT, fmt)
            parm = StreamParameters(type=1)
            parm.parm.capture.timeperframe = Fraction(1, 30)
            ioctl(self.fd, S_PARM, parm)
            ioctl(self.fd, G_FMT, fmt)
            ioctl(self.fd, G_PARM, parm)
            self.mode = validate_mode(fmt, parm)
            req = ioctl(self.fd, REQBUFS, RequestBuffers(count=3, type=1, memory=1))
            if not 2 <= req.count <= 8:
                raise ValueError(f"unbounded/insufficient capture buffer allocation: {req.count}")
            for index in range(req.count):
                buf = ioctl(self.fd, QUERYBUF, Buffer(index=index, type=1, memory=1))
                self.buffers.append(mmap.mmap(self.fd, buf.length, flags=mmap.MAP_SHARED,
                                             prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=buf.m.offset))
                ioctl(self.fd, QBUF, buf)
            ioctl(self.fd, STREAMON, C.c_int(1))
            self.streaming = True
        except BaseException:
            self.close()
            raise

    def read(self, timeout=0.1):
        """Drain at most the bounded kernel queue, returning only its newest Y."""
        if not select.select([self.fd], [], [], timeout)[0]:
            return None
        newest = None
        for _ in range(len(self.buffers)):
            try:
                buf = ioctl(self.fd, DQBUF, Buffer(type=1, memory=1))
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    break
                raise
            try:
                seq = int(buf.sequence)
                if self.previous_sequence is not None:
                    gap = (seq - self.previous_sequence) & 0xFFFFFFFF
                    if 0 < gap < 0x80000000:
                        self.driver_drops += gap - 1
                self.previous_sequence = seq
                self.frames += 1
                if buf.index >= len(self.buffers):
                    raise ValueError("driver returned invalid buffer index")
                if buf.flags & 0x40 or buf.bytesused < self.mode["stride"] * 480:
                    self.bad_frames += 1
                    continue
                stamp = time.monotonic()
                if buf.flags & 0xE000 == 0x2000:
                    stamp = buf.timestamp.seconds + buf.timestamp.microseconds / 1e6
                    self.timestamp_kind = "driver-monotonic"
                else:
                    self.timestamp_kind = "receipt-time (driver age unknown)"
                y = extract_y(self.buffers[buf.index], 640, 480, self.mode["stride"])
                if newest is not None:
                    self.discarded += 1
                newest = (y, stamp, seq)
            finally:
                ioctl(self.fd, QBUF, buf)
        return newest

    def stats(self):
        return dict(frames=self.frames, driver_drops=self.driver_drops,
                    drained_discards=self.discarded, bad_frames=self.bad_frames,
                    timestamp_kind=self.timestamp_kind)

    def read_controls(self):
        """Firmware can change effective controls after STREAMON; observe again."""
        values = {}
        for name, cid in CONTROL_IDS.items():
            try:
                values[name] = ioctl(self.fd, G_CTRL, Control(cid, 0)).value
            except OSError:
                values[name] = None  # Unsupported / disconnected, explicitly unknown.
        return values

    def close(self):
        if self.fd is None:
            return
        if self.streaming:
            try:
                ioctl(self.fd, STREAMOFF, C.c_int(1))
            except OSError as exc:
                self.warnings.append(f"stream cleanup: {exc}")
            self.streaming = False
        for buffer in self.buffers:
            buffer.close()
        self.buffers.clear()
        for name, cid, old in reversed(self.saved_controls):
            try:
                ioctl(self.fd, S_CTRL, Control(cid, old))
            except OSError as exc:
                self.warnings.append(f"restore {name}: {exc}")
        self.saved_controls.clear()
        os.close(self.fd)
        self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
