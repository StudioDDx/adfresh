"""Analog night clock over a dim sky."""

from __future__ import annotations

import math
from datetime import datetime

import pygame

from adfresh.drawutil import font, radial, vertical_gradient
from adfresh.modules.base import Module


class Clock(Module):
    id = "clock"
    title = "Clock"

    def draw(self, surf: pygame.Surface) -> None:
        sky = vertical_gradient(
            self.w,
            self.h,
            [(0.0, (6, 8, 18)), (0.6, (10, 14, 28)), (1.0, (8, 8, 14))],
        )
        surf.blit(sky, (0, 0))
        cx, cy = self.w / 2, self.h * 0.46
        radius = min(self.w, self.h) * 0.30
        glow = radial(int(radius * 3.2), (80, 100, 150), 70)
        surf.blit(glow, (int(cx - glow.get_width() / 2), int(cy - glow.get_height() / 2)))
        pygame.draw.circle(surf, (20, 22, 32), (int(cx), int(cy)), int(radius - 6))
        for i in range(60):
            angle = i / 60 * math.tau
            inner = radius * (0.86 if i % 5 else 0.78)
            outer = radius * 0.92
            x0, y0 = cx + math.sin(angle) * inner, cy - math.cos(angle) * inner
            x1, y1 = cx + math.sin(angle) * outer, cy - math.cos(angle) * outer
            color = (236, 230, 214) if i % 5 == 0 else (120, 124, 136)
            width = 2 if i % 5 == 0 else 1
            pygame.draw.line(surf, color, (x0, y0), (x1, y1), width)
        pygame.draw.circle(surf, (232, 226, 210), (int(cx), int(cy)), int(radius), 2)
        now = datetime.now()
        sec = now.second + now.microsecond / 1_000_000
        minute = now.minute + sec / 60
        hour = (now.hour % 12) + minute / 60
        self._hand(surf, cx, cy, hour / 12 * math.tau, radius * 0.48, radius * 0.035, (236, 230, 214))
        self._hand(surf, cx, cy, minute / 60 * math.tau, radius * 0.70, radius * 0.02, (236, 230, 214))
        self._hand(surf, cx, cy, sec / 60 * math.tau, radius * 0.78, radius * 0.008, (232, 150, 86))
        pygame.draw.circle(surf, (236, 230, 214), (int(cx), int(cy)), max(3, int(radius * 0.03)))
        scale = max(0.7, self.h / 1080)
        digital = font("mono", int(54 * scale)).render(now.strftime("%H:%M"), True, (236, 230, 214))
        date = font("regular", int(22 * scale)).render(now.strftime("%A  ·  %d %B"), True, (176, 180, 196))
        surf.blit(digital, (int(cx - digital.get_width() / 2), int(cy + radius + 28 * scale)))
        surf.blit(date, (int(cx - date.get_width() / 2), int(cy + radius + 28 * scale + digital.get_height() + 6)))

    def _hand(self, surf, cx, cy, angle, length, width, color) -> None:
        dx, dy = math.sin(angle), -math.cos(angle)
        px, py = -dy * width, dx * width
        tip = (cx + dx * length, cy + dy * length)
        tail = (cx - dx * length * 0.14, cy - dy * length * 0.14)
        pts = [
            (tail[0] + px, tail[1] + py),
            (tip[0] + px * 0.2, tip[1] + py * 0.2),
            (tail[0] - px, tail[1] - py),
        ]
        pygame.draw.polygon(surf, color, pts)
