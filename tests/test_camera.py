import ctypes as C
import errno
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sentio import camera as cam


def negotiated():
    fmt, parm = cam.Format(type=1), cam.StreamParameters(type=1)
    fmt.fmt.pix = cam.PixelFormat(width=640, height=480, pixelformat=cam.YUYV,
                                  field=1, bytesperline=1280, sizeimage=614400)
    parm.parm.capture.timeperframe = cam.Fraction(1, 30)
    return fmt, parm


class CameraTests(unittest.TestCase):
    def test_strict_mode_negotiation(self):
        fmt, parm = negotiated()
        self.assertEqual(cam.validate_mode(fmt, parm)["fps"], 30)
        for name, value in (("pixelformat", int.from_bytes(b"MJPG", "little")),
                            ("width", 320), ("height", 240), ("field", 4),
                            ("bytesperline", 1279), ("sizeimage", 10)):
            fmt, parm = negotiated()
            setattr(fmt.fmt.pix, name, value)
            with self.assertRaises(ValueError):
                cam.validate_mode(fmt, parm)
        fmt, parm = negotiated()
        parm.parm.capture.timeperframe.denominator = 15
        with self.assertRaises(ValueError):
            cam.validate_mode(fmt, parm)

    def test_no_implicit_wrong_camera_or_ambiguous_identity(self):
        with patch.object(cam, "devices", return_value=[dict(card="Other", path="/dev/video0")]):
            with self.assertRaises(ValueError):
                cam.choose_device()
        with patch.object(cam, "devices", return_value=[dict(card="C922 Pro", path="/dev/v4l/by-id/one")]):
            self.assertEqual(cam.choose_device(), "/dev/v4l/by-id/one")
        self.assertEqual(cam.choose_device("/dev/video8"), "/dev/video8")

    def test_drains_newest_counts_gaps_bad_frames_and_requeues(self):
        camera = cam.V4L2Camera.__new__(cam.V4L2Camera)
        camera.fd = 10
        camera.buffers = [bytes([120, 50])*640*480 for _ in range(3)]
        camera.mode = dict(stride=1280)
        camera.frames = camera.driver_drops = camera.discarded = camera.bad_frames = 0
        camera.previous_sequence = 4
        pending = [cam.Buffer(index=0, sequence=6, bytesused=614400, flags=0x2000),
                   cam.Buffer(index=1, sequence=7, bytesused=614400, flags=0x40),
                   cam.Buffer(index=2, sequence=8, bytesused=614400, flags=0x2000)]
        requeued = []
        def fake_ioctl(fd, code, value):
            if code == cam.DQBUF:
                if not pending:
                    raise BlockingIOError(errno.EAGAIN, "empty")
                return pending.pop(0)
            requeued.append(value.index)
            return value
        with patch.object(cam.select, "select", return_value=([10], [], [])), patch.object(cam, "ioctl", side_effect=fake_ioctl):
            y, _, sequence = camera.read()
        self.assertEqual(sequence, 8)
        self.assertEqual(int(y[0, 0]), 120)
        self.assertEqual(camera.driver_drops, 1)
        self.assertEqual(camera.bad_frames, 1)
        self.assertEqual(camera.discarded, 1)
        self.assertEqual(requeued, [0, 1, 2])

    def test_mode_failure_restores_controls_and_closes_descriptor(self):
        restored = []
        def fake_ioctl(fd, code, value):
            if code == cam.G_CTRL:
                value.value = 7
            elif code == cam.S_CTRL and value.value == 7:
                restored.append(value.id)
            elif code == cam.G_FMT:
                value.fmt.pix.pixelformat = int.from_bytes(b"MJPG", "little")
            return value
        with patch.object(cam.os, "open", return_value=20), patch.object(cam.os, "close") as close, \
             patch.object(cam, "identity", return_value={}), patch.object(cam, "ioctl", side_effect=fake_ioctl):
            with self.assertRaises(ValueError):
                cam.V4L2Camera("/dev/fake")
        close.assert_called_once_with(20)
        self.assertEqual(len(restored), 6)
        self.assertEqual(restored[-1], 0x009A0901)

    @unittest.skipUnless(shutil.which("cc") and Path("/usr/include/linux/videodev2.h").exists(), "C compiler/Linux headers unavailable")
    def test_ctypes_abi_matches_installed_linux_headers(self):
        structures = [("v4l2_capability", cam.Capability), ("v4l2_format", cam.Format),
                      ("v4l2_pix_format", cam.PixelFormat), ("v4l2_streamparm", cam.StreamParameters),
                      ("v4l2_requestbuffers", cam.RequestBuffers), ("v4l2_buffer", cam.Buffer),
                      ("v4l2_control", cam.Control)]
        names = ("QUERYCAP", "G_FMT", "S_FMT", "REQBUFS", "QUERYBUF", "QBUF", "DQBUF",
                 "STREAMON", "STREAMOFF", "G_PARM", "S_PARM", "G_CTRL", "S_CTRL")
        source = '#include <stdio.h>\n#include <time.h>\n#include <linux/videodev2.h>\nint main(void){\n'
        source += "".join(f'printf("%lu\\n", (unsigned long)sizeof(struct {name}));\n' for name, _ in structures)
        source += "".join(f'printf("%lu\\n", (unsigned long)VIDIOC_{name});\n' for name in names)
        source += "return 0;}"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/"abi.c").write_text(source)
            subprocess.run(["cc", str(path/"abi.c"), "-o", str(path/"abi")], check=True, capture_output=True)
            values = list(map(int, subprocess.check_output([str(path/"abi")], text=True).split()))
        self.assertEqual(values, [C.sizeof(kind) for _, kind in structures] + [getattr(cam, name) for name in names])
