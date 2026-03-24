from __future__ import annotations

from PySide6 import QtCore, QtGui


def render_orb_image(size: int = 256, glyph: str = "A") -> QtGui.QImage:
    image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    center = QtCore.QPointF(size / 2, size / 2)
    radius = size * 0.28

    halo = QtGui.QRadialGradient(center, radius * 2.1)
    halo.setColorAt(0.0, QtGui.QColor(244, 176, 102, 180))
    halo.setColorAt(0.42, QtGui.QColor(44, 110, 119, 120))
    halo.setColorAt(1.0, QtGui.QColor(44, 110, 119, 0))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(halo)
    painter.drawEllipse(center, radius * 2.1, radius * 2.1)

    orbit_pen = QtGui.QPen(QtGui.QColor(217, 162, 95, 140), max(1.6, size * 0.02))
    orbit_pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(orbit_pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    for idx, scale in enumerate((1.35, 1.75)):
        rect = QtCore.QRectF(
            center.x() - radius * scale,
            center.y() - radius * scale,
            radius * scale * 2,
            radius * scale * 2,
        )
        painter.drawArc(rect, (idx * 110 + 30) * 16, 150 * 16)

    core = QtGui.QRadialGradient(center, radius)
    core.setColorAt(0.0, QtGui.QColor("#FFF9F0"))
    core.setColorAt(0.35, QtGui.QColor("#F4B066"))
    core.setColorAt(1.0, QtGui.QColor("#2C6E77"))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(core)
    painter.drawEllipse(center, radius, radius)

    inner_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 115), max(1.0, size * 0.01))
    painter.setPen(inner_pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawEllipse(center, radius * 0.70, radius * 0.70)

    font = QtGui.QFont("Bahnschrift SemiBold", max(6, int(size * 0.10)))
    painter.setFont(font)
    painter.setPen(QtGui.QColor("#F7F3EA"))
    painter.drawText(
        QtCore.QRectF(0, center.y() - size * 0.11, size, size * 0.22),
        QtCore.Qt.AlignCenter,
        glyph,
    )
    painter.end()
    return image


def create_app_icon(size: int = 256, glyph: str = "A") -> QtGui.QIcon:
    icon = QtGui.QIcon()
    for icon_size in (16, 24, 32, 48, 64, 128, size):
        image = render_orb_image(icon_size, glyph=glyph)
        icon.addPixmap(QtGui.QPixmap.fromImage(image))
    return icon
