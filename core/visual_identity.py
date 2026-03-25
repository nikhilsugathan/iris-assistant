from __future__ import annotations

import ctypes
import sys

from PySide6 import QtCore, QtGui


WINDOWS_APP_ID = "Aletheia.IRIS"


def render_orb_image(size: int = 256, glyph: str = "A") -> QtGui.QImage:
    image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

    canvas = QtCore.QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88)
    radius = size * 0.21
    center = canvas.center()

    plate = QtGui.QPainterPath()
    plate.addRoundedRect(canvas, radius, radius)

    base_gradient = QtGui.QLinearGradient(canvas.topLeft(), canvas.bottomRight())
    base_gradient.setColorAt(0.0, QtGui.QColor("#07111B"))
    base_gradient.setColorAt(0.52, QtGui.QColor("#0D2B3F"))
    base_gradient.setColorAt(1.0, QtGui.QColor("#041926"))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(base_gradient)
    painter.drawPath(plate)

    haze = QtGui.QRadialGradient(
        QtCore.QPointF(canvas.left() + canvas.width() * 0.26, canvas.top() + canvas.height() * 0.24),
        size * 0.62,
    )
    haze.setColorAt(0.0, QtGui.QColor(77, 222, 255, 95))
    haze.setColorAt(0.36, QtGui.QColor(18, 111, 176, 58))
    haze.setColorAt(1.0, QtGui.QColor(6, 22, 34, 0))
    painter.setBrush(haze)
    painter.drawPath(plate)

    painter.save()
    painter.setClipPath(plate)
    grid_pen = QtGui.QPen(QtGui.QColor(181, 244, 255, 26), max(1.0, size * 0.0032))
    painter.setPen(grid_pen)
    step = max(10, int(size * 0.12))
    for offset in range(-size, size * 2, step):
        painter.drawLine(
            QtCore.QPointF(canvas.left() + offset, canvas.top()),
            QtCore.QPointF(canvas.left() + offset + canvas.height(), canvas.bottom()),
        )
    painter.restore()

    border_pen = QtGui.QPen(QtGui.QColor("#73E8FF"))
    border_pen.setWidthF(max(1.6, size * 0.012))
    border_pen.setColor(QtGui.QColor(115, 232, 255, 78))
    painter.setPen(border_pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawPath(plate)

    glow = QtGui.QRadialGradient(center, size * 0.29)
    glow.setColorAt(0.0, QtGui.QColor(97, 248, 255, 185))
    glow.setColorAt(0.42, QtGui.QColor(48, 177, 241, 112))
    glow.setColorAt(1.0, QtGui.QColor(15, 66, 101, 0))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(center, size * 0.29, size * 0.29)

    ring_pen = QtGui.QPen(QtGui.QColor("#7AF6FF"))
    ring_pen.setWidthF(max(2.0, size * 0.028))
    painter.setPen(ring_pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawEllipse(center, size * 0.205, size * 0.205)

    inner_ring_pen = QtGui.QPen(QtGui.QColor(250, 251, 255, 135))
    inner_ring_pen.setWidthF(max(1.2, size * 0.010))
    painter.setPen(inner_ring_pen)
    painter.drawEllipse(center, size * 0.148, size * 0.148)

    iris_core = QtGui.QRadialGradient(center, size * 0.13)
    iris_core.setColorAt(0.0, QtGui.QColor("#FBFFFF"))
    iris_core.setColorAt(0.28, QtGui.QColor("#C7FDFF"))
    iris_core.setColorAt(0.68, QtGui.QColor("#46D9F7"))
    iris_core.setColorAt(1.0, QtGui.QColor("#0A3148"))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(iris_core)
    painter.drawEllipse(center, size * 0.13, size * 0.13)

    pupil_path = QtGui.QPainterPath()
    pupil_width = size * 0.09
    pupil_height = size * 0.30
    pupil_path.moveTo(center.x(), center.y() - pupil_height * 0.58)
    pupil_path.lineTo(center.x() + pupil_width * 0.34, center.y() - pupil_height * 0.12)
    pupil_path.lineTo(center.x() + pupil_width * 0.23, center.y() + pupil_height * 0.52)
    pupil_path.lineTo(center.x(), center.y() + pupil_height * 0.70)
    pupil_path.lineTo(center.x() - pupil_width * 0.23, center.y() + pupil_height * 0.52)
    pupil_path.lineTo(center.x() - pupil_width * 0.34, center.y() - pupil_height * 0.12)
    pupil_path.closeSubpath()

    beam_gradient = QtGui.QLinearGradient(center.x(), center.y() - pupil_height * 0.7, center.x(), center.y() + pupil_height * 0.7)
    beam_gradient.setColorAt(0.0, QtGui.QColor("#FFF7F2"))
    beam_gradient.setColorAt(0.38, QtGui.QColor("#FFBC7F"))
    beam_gradient.setColorAt(1.0, QtGui.QColor("#F36B3D"))
    painter.setBrush(beam_gradient)
    painter.drawPath(pupil_path)

    beam_pen = QtGui.QPen(QtGui.QColor(255, 248, 236, 168), max(1.0, size * 0.007))
    painter.setPen(beam_pen)
    painter.drawPath(pupil_path)

    orbit_pen = QtGui.QPen(QtGui.QColor(108, 240, 255, 110), max(1.4, size * 0.012))
    orbit_pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(orbit_pen)
    orbit_a = QtCore.QRectF(center.x() - size * 0.29, center.y() - size * 0.19, size * 0.58, size * 0.38)
    orbit_b = QtCore.QRectF(center.x() - size * 0.33, center.y() - size * 0.24, size * 0.66, size * 0.48)
    painter.drawArc(orbit_a, 26 * 16, 118 * 16)
    painter.drawArc(orbit_b, 208 * 16, 112 * 16)

    node_color = QtGui.QColor("#FFC27A")
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(node_color)
    painter.drawEllipse(QtCore.QPointF(center.x() + size * 0.24, center.y() - size * 0.15), size * 0.026, size * 0.026)
    painter.drawEllipse(QtCore.QPointF(center.x() - size * 0.22, center.y() + size * 0.17), size * 0.019, size * 0.019)

    sparkle = QtGui.QPainterPath()
    sparkle_center = QtCore.QPointF(center.x() + size * 0.19, center.y() - size * 0.24)
    sparkle.moveTo(sparkle_center.x(), sparkle_center.y() - size * 0.034)
    sparkle.lineTo(sparkle_center.x() + size * 0.012, sparkle_center.y() - size * 0.010)
    sparkle.lineTo(sparkle_center.x() + size * 0.036, sparkle_center.y())
    sparkle.lineTo(sparkle_center.x() + size * 0.012, sparkle_center.y() + size * 0.010)
    sparkle.lineTo(sparkle_center.x(), sparkle_center.y() + size * 0.034)
    sparkle.lineTo(sparkle_center.x() - size * 0.012, sparkle_center.y() + size * 0.010)
    sparkle.lineTo(sparkle_center.x() - size * 0.036, sparkle_center.y())
    sparkle.lineTo(sparkle_center.x() - size * 0.012, sparkle_center.y() - size * 0.010)
    sparkle.closeSubpath()
    painter.setBrush(QtGui.QColor("#FFF4E5"))
    painter.drawPath(sparkle)

    scan_pen = QtGui.QPen(QtGui.QColor(240, 252, 255, 160), max(1.0, size * 0.007))
    scan_pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(scan_pen)
    painter.drawLine(
        QtCore.QPointF(canvas.left() + size * 0.18, canvas.bottom() - size * 0.12),
        QtCore.QPointF(canvas.right() - size * 0.16, canvas.top() + size * 0.14),
    )

    painter.end()
    return image


def create_app_icon(size: int = 256, glyph: str = "A") -> QtGui.QIcon:
    icon = QtGui.QIcon()
    for icon_size in (16, 24, 32, 48, 64, 128, 256):
        image = render_orb_image(icon_size, glyph=glyph)
        icon.addPixmap(QtGui.QPixmap.fromImage(image))
    return icon


def apply_windows_app_user_model_id(app_id: str = WINDOWS_APP_ID) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass
