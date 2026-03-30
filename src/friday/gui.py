from __future__ import annotations

import math
import random
import threading
import time
import tkinter as tk
from dataclasses import dataclass


@dataclass(slots=True)
class Particle:
    theta: float
    phi: float
    base_radius: float
    size: float


class ParticleSphereGUI:
    def __init__(
        self,
        *,
        particle_count: int = 850,
        width: int = 720,
        height: int = 480,
        speaking_event: threading.Event | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.speaking_event = speaking_event or threading.Event()

        self.root = tk.Tk()
        self.root.title("F.R.I.D.A.Y")
        self.root.configure(bg="#000000")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            bg="#000000",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.center_x = self.width / 2
        self.center_y = self.height / 2
        self.base_radius = min(self.width, self.height) * 0.22
        self.fov = 380

        self.particles: list[Particle] = []
        self.items: list[int] = []

        rng = random.Random(7)
        for _ in range(max(60, int(particle_count))):
            u = rng.random()
            v = rng.random()
            theta = 2 * math.pi * u
            phi = math.acos(2 * v - 1)
            base_radius = self.base_radius * (0.92 + 0.12 * rng.random())
            size = 1.0 + 1.6 * rng.random()
            self.particles.append(
                Particle(theta=theta, phi=phi, base_radius=base_radius, size=size)
            )
            item = self.canvas.create_oval(0, 0, 0, 0, fill="#7b3cff", outline="")
            self.items.append(item)

        self._last_frame = time.perf_counter()
        self._rotation = 0.0
        self._pulse_phase = 0.0

        self.root.bind("<Escape>", lambda _e: self.root.destroy())

    def run(self) -> None:
        self._tick()
        self.root.mainloop()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.05, now - self._last_frame)
        self._last_frame = now

        self._rotation += dt * 0.7
        self._pulse_phase += dt * (6.0 if self.speaking_event.is_set() else 1.3)

        pulse_strength = 0.10 if self.speaking_event.is_set() else 0.02
        pulse = 1.0 + pulse_strength * (0.5 + 0.5 * math.sin(self._pulse_phase))

        sin_r = math.sin(self._rotation)
        cos_r = math.cos(self._rotation)

        for idx, p in enumerate(self.particles):
            x = math.sin(p.phi) * math.cos(p.theta)
            y = math.cos(p.phi)
            z = math.sin(p.phi) * math.sin(p.theta)

            xr = x * cos_r + z * sin_r
            zr = -x * sin_r + z * cos_r
            yr = y

            radius = p.base_radius * pulse
            X = xr * radius
            Y = yr * radius
            Z = zr * radius

            scale = self.fov / (self.fov + (Z + self.base_radius * 1.6))
            sx = self.center_x + X * scale
            sy = self.center_y + Y * scale

            depth = max(0.0, min(1.0, (Z / (self.base_radius * 1.4) + 1.0) / 2.0))
            color = _lerp_hex("#3b00ff", "#c07bff", depth)

            size = p.size * (0.9 + 1.2 * scale)
            x0 = sx - size
            y0 = sy - size
            x1 = sx + size
            y1 = sy + size

            item = self.items[idx]
            self.canvas.coords(item, x0, y0, x1, y1)
            self.canvas.itemconfig(item, fill=color)

        self.root.after(16, self._tick)


def _lerp_hex(a: str, b: str, t: float) -> str:
    a = a.lstrip("#")
    b = b.lstrip("#")
    ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
    br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
    rr = int(ar + (br - ar) * t)
    rg = int(ag + (bg - ag) * t)
    rb = int(ab + (bb - ab) * t)
    return f"#{rr:02x}{rg:02x}{rb:02x}"
