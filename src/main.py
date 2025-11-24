import logging

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt

import qtpynodeeditor
from qtpynodeeditor import NodeData, NodeDataModel, NodeDataType, PortType


class PixmapData(NodeData):
    data_type = NodeDataType(id='Pixmap', name='PixmapData')

    def __init__(self, pixmap):
        self.pixmap = pixmap


class ImageLoaderModel(NodeDataModel):
    caption = 'Image Source'
    num_ports = {PortType.input: 0,
                 PortType.output: 1,
                 }
    data_type = PixmapData

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pixmap = None
        self._label = QtWidgets.QLabel('Click to load image')
        self._label.setAlignment(Qt.AlignVCenter | Qt.AlignCenter)

        font = self._label.font()
        font.setBold(True)
        font.setItalic(True)
        self._label.setFont(font)

        self._label.setFixedSize(200, 200)
        self._label.installEventFilter(self)

    def eventFilter(self, obj, event):
        label = getattr(self, "_label", None)

        if label is None or obj is not label:
            return False

        def set_pixmap():
            w, h = label.width(), label.height()
            label.setPixmap(self._pixmap.scaled(w, h, Qt.KeepAspectRatio))

        if event.type() == QtCore.QEvent.MouseButtonPress:
            file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
                None, "Open Image", QtCore.QDir.homePath(),
                "Image files (*.png *.jpg *.bmp)")
            try:
                self._pixmap = QtGui.QPixmap(file_name)
            except Exception as ex:
                print(f'Failed to load image {file_name}: {ex}')
                return False

            set_pixmap()
            self.data_updated.emit(0)
            return True

        elif event.type() == QtCore.QEvent.Resize:
            if self._pixmap is not None:
                set_pixmap()

        return False

    def resizable(self):
        return True

    def out_data(self, port):
        return PixmapData(self._pixmap)

    def embedded_widget(self):
        return self._label


class ImageShowModel(NodeDataModel):
    caption = 'Image Display'
    num_ports = {PortType.input: 1,
                 PortType.output: 1,
                 }
    data_type = PixmapData

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._node_data = None
        self._label = QtWidgets.QLabel('Image will appear here')
        self._label.setAlignment(Qt.AlignVCenter | Qt.AlignCenter)

        font = self._label.font()
        font.setBold(True)
        font.setItalic(True)
        self._label.setFont(font)

        self._label.setFixedSize(200, 200)
        self._label.installEventFilter(self)

    def resizable(self):
        return True

    def eventFilter(self, obj, event):
        if obj is self._label and event.type() == QtCore.QEvent.Resize:
            if (self._node_data and
                    self._node_data.data_type == PixmapData.data_type and
                    self._node_data.pixmap):
                w, h = self._label.width(), self._label.height()
                pixmap = self._node_data.pixmap
                self._label.setPixmap(pixmap.scaled(w, h, Qt.KeepAspectRatio))

        return False

    def set_in_data(self, node_data, port):
        self._node_data = node_data
        if (self._node_data and
                self._node_data.data_type == PixmapData.data_type and
                self._node_data.pixmap):
            w, h = self._label.width(), self._label.height()
            pixmap = node_data.pixmap.scaled(w, h, Qt.KeepAspectRatio)
        else:
            pixmap = QtGui.QPixmap()

        self._label.setPixmap(pixmap)
        self.data_updated.emit(0)

    def out_data(self, port):
        return self._node_data

    def embedded_widget(self):
        return self._label


class ImageContrastModel(NodeDataModel):
    """
    Image Adjust node: takes an input image (PixmapData) and a numeric
    value for contrast.
    Outputs an adjusted PixmapData.

    Contrast is a multiplicative factor (1.0 = no change). Brightness is
    an additive offset applied to each channel (0 = no change).
    """
    caption = 'Contrast'
    num_ports = {PortType.input: 1,
                 PortType.output: 1,
                 }
    data_type = PixmapData

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._in_data = None

        # Main widget holds preview + controls
        self._widget = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(self._widget)
        vbox.setContentsMargins(2, 2, 2, 2)

        # Preview label
        self._preview = QtWidgets.QLabel('Preview')
        self._preview.setAlignment(Qt.AlignVCenter | Qt.AlignCenter)
        font = self._preview.font()
        font.setBold(True)
        self._preview.setFont(font)
        self._preview.setFixedSize(200, 200)
        self._preview.installEventFilter(self)
        vbox.addWidget(self._preview)

        # Controls: contrast and brightness (inline editable text fields)
        ctrl_widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(ctrl_widget)
        h.setContentsMargins(0, 0, 0, 0)

        # Contrast control
        ctr_label = QtWidgets.QLabel("Contrast:")
        self.ctr_edit = QtWidgets.QLineEdit("1.0")
        self.ctr_edit.setValidator(QtGui.QDoubleValidator(-10.0, 10.0, 3))
        self.ctr_edit.setFixedWidth(80)
        self.ctr_edit.setToolTip("Contrast multiplier (1.0 = no change).")

        # Connect signals: update on editing finished and on text change (debounced)
        self.ctr_edit.editingFinished.connect(self._on_params_changed)


        # Optionally handle live updates while typing
        self.ctr_edit.textChanged.connect(self._on_params_changed)

        h.addWidget(ctr_label)
        h.addWidget(self.ctr_edit)
        h.addSpacing(6)
        h.addStretch(1)

        vbox.addWidget(ctrl_widget)

        # internal adjusted pixmap cache
        self._adjusted_pixmap = None

        # small timer to debounce frequent updates while typing
        self._debounce_timer = QtCore.QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(120)
        self._debounce_timer.timeout.connect(self._apply_adjustment)

    def resizable(self):
        return True

    def embedded_widget(self):
        return self._widget

    def eventFilter(self, obj, event):
        # keep preview scaled on resize of the embedded widget/preview
        if obj is self._preview and event.type() == QtCore.QEvent.Resize:
            if self._adjusted_pixmap and not self._adjusted_pixmap.isNull():
                w, h = self._preview.width(), self._preview.height()
                self._preview.setPixmap(self._adjusted_pixmap.scaled(w, h, Qt.KeepAspectRatio))
        return False

    def _read_params(self):
        try:
            contrast = float(self.ctr_edit.text())
        except Exception:
            contrast = 1.0

        return contrast

    def _on_params_changed(self):
        # start/reset debounce timer and schedule update
        self._debounce_timer.start()

    def _apply_adjustment(self):
        # Apply adjustment to _in_data.pixmap if present
        if not (self._in_data and self._in_data.data_type == PixmapData.data_type and self._in_data.pixmap):
            self._adjusted_pixmap = QtGui.QPixmap()
            self._preview.setPixmap(QtGui.QPixmap())
            self.data_updated.emit(0)
            return

        pixmap = self._in_data.pixmap
        contrast = self._read_params()

        adjusted = self._adjust_pixmap(pixmap, contrast)
        self._adjusted_pixmap = adjusted

        # update preview scaled to label
        w, h = self._preview.width(), self._preview.height()
        if not adjusted.isNull():
            self._preview.setPixmap(adjusted.scaled(w, h, Qt.KeepAspectRatio))
        else:
            self._preview.setPixmap(QtGui.QPixmap())

        # notify downstream nodes that data changed
        self.data_updated.emit(0)

    def set_in_data(self, node_data, port):
        # store input and immediately apply adjustment
        self._in_data = node_data
        # apply with debounce to avoid locking UI on big images when multiple changes occur
        self._debounce_timer.start()

    def out_data(self, port):
        # return adjusted pixmap (if any) as PixmapData
        return PixmapData(self._adjusted_pixmap)

    def _adjust_pixmap(self, pixmap, contrast):
        """
        Adjust contrast and brightness of a QPixmap and return a new QPixmap.
        Contrast is multiplicative factor applied around midpoint 128:
            new = contrast*(v - 128) + 128 + brightness
        brightness is additive offset.

        Operates on ARGB32 image. This is not the fastest approach but is simple
        and dependency-free for example purposes.
        """
        if pixmap is None or pixmap.isNull():
            return QtGui.QPixmap()

        qimg = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)

        width = qimg.width()
        height = qimg.height()

        # prepare an output image
        out = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)

        # localize frequently used functions
        clamp = lambda v: 0 if v < 0 else (255 if v > 255 else int(v))
        for y in range(height):
            for x in range(width):
                c = QtGui.QColor(qimg.pixel(x, y))
                a = c.alpha()
                r = c.red()
                g = c.green()
                b = c.blue()

                # apply contrast and brightness
                nr = clamp(contrast * (r - 128) + 128)
                ng = clamp(contrast * (g - 128) + 128)
                nb = clamp(contrast * (b - 128) + 128)

                out.setPixel(x, y, QtGui.qRgba(nr, ng, nb, a))

        return QtGui.QPixmap.fromImage(out)


# def _adjust_contrast(self, pixmap, contrast):
#         """
#         Adjust contrast of a QPixmap and return a new QPixmap.
#         Contrast is multiplicative factor applied around midpoint 128:
#             new = contrast*(v - 128) + 128 .

#         Operates on ARGB32 image. This is not the fastest approach but is simple
#         and dependency-free for example purposes.
#         """
#         if pixmap is None or pixmap.isNull():
#             return QtGui.QPixmap()

#         qimg = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)

#         width = qimg.width()
#         height = qimg.height()

#         # prepare an output image
#         out = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)

#         # localize frequently used functions
#         clamp = lambda v: 0 if v < 0 else (255 if v > 255 else int(v))
#         for y in range(height):
#             for x in range(width):
#                 c = QtGui.QColor(qimg.pixel(x, y))
#                 a = c.alpha()
#                 r = c.red()
#                 g = c.green()
#                 b = c.blue()

#                 # apply contrast and brightness
#                 nr = clamp(contrast * (r - 128) + 128)
#                 ng = clamp(contrast * (g - 128) + 128)
#                 nb = clamp(contrast * (b - 128) + 128)

#                 out.setPixel(x, y, QtGui.qRgba(nr, ng, nb, a))

#         return QtGui.QPixmap.fromImage(out)



class ImageBrightnesstModel(NodeDataModel):
    """
    Image Adjust node: takes an input image (PixmapData) and a numeric
    value for contrast and brightness entered in-line (like a numbersource).
    Outputs an adjusted PixmapData.

    Contrast is a multiplicative factor (1.0 = no change). Brightness is
    an additive offset applied to each channel (0 = no change).
    """
    caption = 'Brightness'
    num_ports = {PortType.input: 1,
                 PortType.output: 1,
                 }
    data_type = PixmapData

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._in_data = None

        # Main widget holds preview + controls
        self._widget = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(self._widget)
        vbox.setContentsMargins(2, 2, 2, 2)

        # Preview label
        self._preview = QtWidgets.QLabel('Preview')
        self._preview.setAlignment(Qt.AlignVCenter | Qt.AlignCenter)
        font = self._preview.font()
        font.setBold(True)
        self._preview.setFont(font)
        self._preview.setFixedSize(200, 200)
        self._preview.installEventFilter(self)
        vbox.addWidget(self._preview)

        # Controls: contrast and brightness (inline editable text fields)
        ctrl_widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(ctrl_widget)
        h.setContentsMargins(0, 0, 0, 0)

        # Brightness control
        br_label = QtWidgets.QLabel("Brightness:")
        self.br_edit = QtWidgets.QLineEdit("0")
        self.br_edit.setValidator(QtGui.QDoubleValidator(-255.0, 255.0, 1))
        self.br_edit.setFixedWidth(80)
        self.br_edit.setToolTip("Brightness offset (-255..255).")

        # Connect signals: update on editing finished and on text change (debounced)
        self.br_edit.editingFinished.connect(self._on_params_changed)

        # Optionally handle live updates while typing
        self.br_edit.textChanged.connect(self._on_params_changed)

        h.addWidget(br_label)
        h.addWidget(self.br_edit)
        h.addStretch(1)

        vbox.addWidget(ctrl_widget)

        # internal adjusted pixmap cache
        self._adjusted_pixmap = None

        # small timer to debounce frequent updates while typing
        self._debounce_timer = QtCore.QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(120)
        self._debounce_timer.timeout.connect(self._apply_adjustment)

    def resizable(self):
        return True

    def embedded_widget(self):
        return self._widget

    def eventFilter(self, obj, event):
        # keep preview scaled on resize of the embedded widget/preview
        if obj is self._preview and event.type() == QtCore.QEvent.Resize:
            if self._adjusted_pixmap and not self._adjusted_pixmap.isNull():
                w, h = self._preview.width(), self._preview.height()
                self._preview.setPixmap(self._adjusted_pixmap.scaled(w, h, Qt.KeepAspectRatio))
        return False

    def _read_params(self):
        try:
            brightness = float(self.br_edit.text())
        except Exception:
            brightness = 0.0
        return brightness

    def _on_params_changed(self):
        # start/reset debounce timer and schedule update
        self._debounce_timer.start()

    def _apply_adjustment(self):
        # Apply adjustment to _in_data.pixmap if present
        if not (self._in_data and self._in_data.data_type == PixmapData.data_type and self._in_data.pixmap):
            self._adjusted_pixmap = QtGui.QPixmap()
            self._preview.setPixmap(QtGui.QPixmap())
            self.data_updated.emit(0)
            return

        pixmap = self._in_data.pixmap
        brightness = self._read_params()

        adjusted = self._adjust_pixmap(pixmap, brightness)
        self._adjusted_pixmap = adjusted

        # update preview scaled to label
        w, h = self._preview.width(), self._preview.height()
        if not adjusted.isNull():
            self._preview.setPixmap(adjusted.scaled(w, h, Qt.KeepAspectRatio))
        else:
            self._preview.setPixmap(QtGui.QPixmap())

        # notify downstream nodes that data changed
        self.data_updated.emit(0)

    def set_in_data(self, node_data, port):
        # store input and immediately apply adjustment
        self._in_data = node_data
        # apply with debounce to avoid locking UI on big images when multiple changes occur
        self._debounce_timer.start()

    def out_data(self, port):
        # return adjusted pixmap (if any) as PixmapData
        return PixmapData(self._adjusted_pixmap)

    def _adjust_pixmap(self, pixmap, brightness):
        """
        Adjust brightness of a QPixmap and return a new QPixmap.
        Contrast is multiplicative factor applied around midpoint 128:
            new = v + brightness
        brightness is additive offset.

        Operates on ARGB32 image. This is not the fastest approach but is simple
        and dependency-free for example purposes.
        """
        if pixmap is None or pixmap.isNull():
            return QtGui.QPixmap()

        qimg = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)

        width = qimg.width()
        height = qimg.height()

        # prepare an output image
        out = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)

        # localize frequently used functions
        clamp = lambda v: 0 if v < 0 else (255 if v > 255 else int(v))
        for y in range(height):
            for x in range(width):
                c = QtGui.QColor(qimg.pixel(x, y))
                a = c.alpha()
                r = c.red()
                g = c.green()
                b = c.blue()

                # apply contrast and brightness
                nr = clamp(r + brightness)
                ng = clamp(g + brightness)
                nb = clamp(b + brightness)

                out.setPixel(x, y, QtGui.qRgba(nr, ng, nb, a))

        return QtGui.QPixmap.fromImage(out)

def main(app):
    registry = qtpynodeeditor.DataModelRegistry()
    registry.register_model(ImageShowModel, category='My Category')
    registry.register_model(ImageLoaderModel, category='My Category')
    registry.register_model(ImageBrightnesstModel, category='My Category')
    registry.register_model(ImageContrastModel, category='My Category')
    scene = qtpynodeeditor.FlowScene(registry=registry)

    view = qtpynodeeditor.FlowView(scene)
    view.setWindowTitle("Image example")
    view.resize(800, 600)

    node_loader = scene.create_node(ImageLoaderModel)
    node_show = scene.create_node(ImageShowModel)
    node_adjust = scene.create_node(ImageBrightnesstModel)

    # wire loader -> adjust -> show
    scene.create_connection(
        node_loader[PortType.output][0],
        node_adjust[PortType.input][0],
    )
    scene.create_connection(
        node_adjust[PortType.output][0],
        node_show[PortType.input][0],
    )

    return scene, view, [node_loader, node_adjust, node_show]


if __name__ == '__main__':
    logging.basicConfig(level='DEBUG')
    app = QtWidgets.QApplication([])
    scene, view, nodes = main(app)
    view.show()
    app.exec_()
