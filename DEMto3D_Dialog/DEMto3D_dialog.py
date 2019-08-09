# -*- coding: utf-8 -*-

"""
/***************************************************************************
 DEMto3D
                                 A QGIS plugin
 Impresión 3D de MDE
                              -------------------
        begin                : 2015-08-02
        git sha              : $Format:%H$
        copyright            : (C) 2015 by Francisco Javier Venceslá Simón
        email                : demto3d@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from __future__ import absolute_import
import os
import math
from qgis.PyQt.QtWidgets import QDialog, QMessageBox, QFileDialog, QApplication
from qgis.PyQt.QtGui import QColor, QCursor
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsRubberBand, QgsMapTool
from osgeo import gdal
import struct
from . import Export_dialog
from . import SelectLayer_dialog
from .DEMto3D_dialog_base import Ui_DEMto3DDialogBase
from qgis.core import QgsPointXY, QgsPoint, QgsRectangle, QgsProject, QgsGeometry, QgsCoordinateTransform, Qgis

from ..model_builder.Model_Builder import Model


def get_layer(layer_name):
    layermap = QgsProject.instance().mapLayers()
    for name, layer in list(layermap.items()):
        if layer.name() == layer_name:
            if layer.isValid():
                return layer
            else:
                return None


class DEMto3DDialog(QDialog, Ui_DEMto3DDialogBase):
    """ Layer to print. """
    layer = None

    ''' Region of interest properties '''
    map_crs = None
    units = None
    roi_x_max = 0
    roi_x_min = 0
    roi_y_max = 0
    roi_y_min = 0
    z_max = 0
    z_min = 0

    ''' Model dimensions '''
    height = 0
    width = 0
    scale_h = 0
    scale_w = 0
    scale = 0
    z_scale = 0

    ''' Raster properties '''
    cell_size = 0
    cols = 0
    rows = 0
    raster_x_max = 0
    raster_x_min = 0
    raster_y_max = 0
    raster_y_min = 0

    rect_map_tool = None
    lastSavingPath = ''

    def __init__(self, iface):
        """Constructor."""
        QDialog.__init__(self)
        self.ui = Ui_DEMto3DDialogBase()
        self.ui.setupUi(self)
        self.iface = iface
        self.canvas = iface.mapCanvas()

        self.canvas.destinationCrsChanged.connect(self.setCanvasCRS)
        self.setCanvasCRS()

        self.units = self.map_crs.mapUnits()
        # 0 Meters. 1 Kilometers. 2 feet. 3 miles. 4 yards. 5 miles. 6 Degrees. 7 Centimeters. 8 Millimeters. 9 Unknown
        if self.units != 0 and self.units != 6:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Units not supported"))

        # region LAYER ACTION
        # fill layer combobox with raster visible layers in mapCanvas
        self.viewLayers = self.canvas.layers()
        self.ui.LayerComboBox.clear()
        for layer in self.viewLayers:
            if layer.type() == 1:
                self.ui.LayerComboBox.addItem(layer.name())
        self.layer = get_layer(self.ui.LayerComboBox.currentText())
        self.get_raster_properties()
        self.ui.LayerComboBox.currentTextChanged.connect(self.get_layer)
        # endregion

        # region EXTENSION ACTION
        self.extent = None
        self.ui.FullExtToolButton.clicked.connect(self.full_extent)
        self.ui.LayerExtToolButton.clicked.connect(self.layer_extent)
        self.ui.CustomExtToolButton.clicked.connect(self.custom_extent)

        self.ui.XMinLineEdit.returnPressed.connect(self.upload_extent)
        self.ui.XMaxLineEdit.returnPressed.connect(self.upload_extent)
        self.ui.YMaxLineEdit.returnPressed.connect(self.upload_extent)
        self.ui.YMinLineEdit.returnPressed.connect(self.upload_extent)
        # endregion

        # region DIMENSION ACTION
        self.ui.HeightLineEdit.textEdited.connect(self.upload_size_from_height)
        self.ui.WidthLineEdit.textEdited.connect(self.upload_size_from_width)
        self.ui.ScaleLineEdit.textEdited.connect(self.upload_size_from_scale)
        # endregion

        self.ui.ZScaleDoubleSpinBox.valueChanged.connect(self.get_height_model)
        self.ui.BaseHeightLineEdit.returnPressed.connect(self.get_height_model)

        # region BOTTOM BUTTONS ACTION
        self.ui.CancelToolButton.clicked.connect(self.reject)
        self.ui.STLToolButton.clicked.connect(self.do_export)
        self.rejected.connect(self.reject_func)
        # endregion

    def setCanvasCRS(self):
        try:
            self.map_crs = self.canvas.mapSettings().destinationCrs()
        except BaseException:
            self.map_crs = self.canvas.mapRenderer().destinationCrs()

    def reject_func(self):
        if self.rect_map_tool is not None:
            self.rect_map_tool.reset()
            self.rect_map_tool.deactivate()
            self.iface.actionPan().trigger()

    def do_export(self):
        parameters = self.get_parameters()
        layer_name = self.ui.LayerComboBox.currentText() + '_model.stl'
        if parameters != 0:
            if parameters["spacing_mm"] < 0.5 and self.height > 100 and self.width > 100:
                reply = QMessageBox.question(self, self.tr('Export to STL'),
                                             self.tr('The construction of the STL file could takes several minutes. Do you want to continue?'),
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply == QMessageBox.Yes:
                    stl_file = QFileDialog.getSaveFileName(self, self.tr('Export to STL'), self.lastSavingPath + layer_name, filter=".stl")
                    if stl_file[0] != '':
                        self.lastSavingPath = os.path.dirname(stl_file[0]) + '//'
                        export_dlg = Export_dialog.Dialog(parameters, stl_file[0])
                        if export_dlg.exec_():
                            QMessageBox.information(self, self.tr("Attention"), self.tr("STL model generated"))
                        else:
                            QMessageBox.information(self, self.tr("Attention"), self.tr("Process canceled"))
            else:
                stl_file = QFileDialog.getSaveFileName(self, self.tr('Export to STL'), self.lastSavingPath + layer_name, filter=".stl")
                if stl_file[0] != '':
                    self.lastSavingPath = os.path.dirname(stl_file[0]) + '//'
                    export_dlg = Export_dialog.Dialog(parameters, stl_file[0])
                    if export_dlg.exec_():
                        QMessageBox.information(self, self.tr("Attention"), self.tr("STL model generated"))
                    else:
                        QMessageBox.information(self, self.tr("Attention"), self.tr("Process canceled"))
        else:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Fill the data correctly"))

    def get_layer(self, layer_name):
        if self.layer.name() != layer_name:
            self.ini_dialog()
        layermap = QgsProject.instance().mapLayers()
        for name, layer in list(layermap.items()):
            if layer.name() == layer_name:
                if layer.isValid():
                    self.layer = layer
                    self.get_raster_properties()
                else:
                    self.layer = None

    def ini_dialog(self):
        self.ui.XMaxLineEdit.clear()
        self.ui.XMinLineEdit.clear()
        self.ui.YMaxLineEdit.clear()
        self.ui.YMinLineEdit.clear()
        if self.extent:
            self.canvas.scene().removeItem(self.extent)
            self.extent = None
        self.ini_dimensions()
        self.ui.ZMaxLabel.setText('0 m')
        self.ui.ZMinLabel.setText('0 m')

    def ini_dimensions(self):
        self.ui.HeightLineEdit.clear()
        self.height = 0
        self.ui.WidthLineEdit.clear()
        self.width = 0
        self.ui.ScaleLineEdit.clear()
        self.scale_h = 0
        self.scale_w = 0
        self.scale = 0
        self.ui.RecomSpacinglabel.setText('0.2 mm')
        self.ui.BaseHeightLineEdit.clear()
        self.ui.HeightModelLabel.setText('0 mm')

    def get_raster_properties(self):
        self.cell_size = self.layer.rasterUnitsPerPixelX()
        self.rows = self.layer.height()
        self.cols = self.layer.width()
        rec = self.layer.extent()
        self.raster_x_max = rec.xMaximum()
        self.raster_x_min = rec.xMinimum()
        self.raster_y_max = rec.yMaximum()
        self.raster_y_min = rec.yMinimum()

    # region Extension functions

    def full_extent(self):
        rec = self.layer.extent()
        canvasCRS = self.map_crs
        layerCRS = self.layer.crs()
        if canvasCRS != layerCRS:
            transform = QgsCoordinateTransform(layerCRS, canvasCRS, QgsProject.instance())
            rec = transform.transform(rec)
        self.paint_extent(rec)
        self.get_z_max_z_min()
        self.ini_dimensions()

    def layer_extent(self):
        layers = self.canvas.layers()
        select_layer_dialog = SelectLayer_dialog.Dialog(layers)
        if select_layer_dialog.exec_():
            layerName = select_layer_dialog.get_layer()
            if layerName:
                layer = get_layer(layerName)
                rec = layer.extent()
                canvasCRS = self.map_crs
                layerCRS = layer.crs()
                if canvasCRS != layerCRS:
                    transform = QgsCoordinateTransform(layerCRS, canvasCRS, QgsProject.instance())
                    rec = transform.transform(rec)
                self.get_custom_extent(rec)

    def custom_extent(self):
        self.iface.messageBar().pushMessage("Info", self.tr("Click and drag the mouse to draw print extent"), level=Qgis.Info, duration=3)
        if self.extent:
            self.canvas.scene().removeItem(self.extent)
            self.extent = None
        self.rect_map_tool = RectangleMapTool(self.canvas, self.get_custom_extent)
        self.canvas.setMapTool(self.rect_map_tool)

    def get_custom_extent(self, rec):
        layer_extension = self.layer.extent()
        dataCRS = self.layer.crs()
        canvasCRS = self.map_crs
        if dataCRS != canvasCRS:
            transform = QgsCoordinateTransform(dataCRS, canvasCRS, QgsProject.instance())
            layer_extension = transform.transform(layer_extension)
        if rec.intersects(layer_extension):
            extension = rec.intersect(layer_extension)
            self.paint_extent(extension)
            self.iface.actionPan().trigger()
            self.get_z_max_z_min()
            self.ini_dimensions()
        else:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Print extent defined outside layer extent"))

    def upload_extent(self):
        try:
            self.roi_x_max = float(self.ui.XMaxLineEdit.text())
            self.roi_x_min = float(self.ui.XMinLineEdit.text())
            self.roi_y_max = float(self.ui.YMaxLineEdit.text())
            self.roi_y_min = float(self.ui.YMinLineEdit.text())
            rec = QgsRectangle(self.roi_x_min, self.roi_y_min, self.roi_x_max, self.roi_y_max)
            self.paint_extent(rec)
            self.get_z_max_z_min()
            self.ini_dimensions()
        except ValueError:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Value entered incorrect"))

    def paint_extent(self, rec):
        self.roi_x_max = rec.xMaximum()
        self.ui.XMaxLineEdit.setText(str(round(rec.xMaximum(), 3)))
        self.roi_y_min = rec.yMinimum()
        self.ui.YMinLineEdit.setText(str(round(rec.yMinimum(), 3)))
        self.roi_x_min = rec.xMinimum()
        self.ui.XMinLineEdit.setText(str(round(rec.xMinimum(), 3)))
        self.roi_y_max = rec.yMaximum()
        self.ui.YMaxLineEdit.setText(str(round(rec.yMaximum(), 3)))

        if self.extent:
            self.canvas.scene().removeItem(self.extent)
            self.extent = None

        self.extent = QgsRubberBand(self.canvas, True)

        points = [QgsPoint(self.roi_x_max, self.roi_y_min), QgsPoint(self.roi_x_max, self.roi_y_max),
                  QgsPoint(self.roi_x_min, self.roi_y_max), QgsPoint(self.roi_x_min, self.roi_y_min),
                  QgsPoint(self.roi_x_max, self.roi_y_min)]

        self.extent.setToGeometry(QgsGeometry.fromPolyline(points), None)
        self.extent.setColor(QColor(227, 26, 28, 255))
        self.extent.setWidth(3)
        self.extent.setLineStyle(Qt.PenStyle(Qt.DashLine))
        self.canvas.refresh()

    def get_z_max_z_min(self):

        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        rec = QgsRectangle(self.roi_x_min, self.roi_y_min, self.roi_x_max, self.roi_y_max)
        canvasCRS = self.map_crs
        dataCRS = self.layer.crs()
        if canvasCRS != dataCRS:
            transform = QgsCoordinateTransform(canvasCRS, dataCRS, QgsProject.instance())
            rec = transform.transform(rec)

        x_max = rec.xMaximum()
        x_min = rec.xMinimum()
        y_max = rec.yMaximum()
        y_min = rec.yMinimum()
        x_off = int(math.floor((x_min - self.raster_x_min) * self.cols / (self.raster_x_max - self.raster_x_min)))
        y_off = int(math.floor((self.raster_y_max - y_max) * self.rows / (self.raster_y_max - self.raster_y_min)))
        col_size = int(math.floor((x_max - x_min) / self.cell_size))
        row_size = int(math.floor((y_max - y_min) / self.cell_size))

        if x_off < 0:
            x_off = 0
        if y_off < 0:
            y_off = 0
        if x_off >= self.cols:
            x_off = self.cols - 1
        if y_off >= self.rows:
            y_off = self.rows - 1
        if x_off + col_size > self.cols:
            col_size = self.cols - x_off
        if row_size + row_size > self.rows:
            row_size = self.rows - y_off

        provider = self.layer.dataProvider()
        path = provider.dataSourceUri()
        path_layer = path.split('|')
        dem_dataset = gdal.Open(path_layer[0])
        data = Model.get_dem_z(dem_dataset, x_off, y_off, col_size, row_size)

        if data is not None:
            self.z_max = max(data)
            self.z_min = self.z_max
            no_data = dem_dataset.GetRasterBand(1).GetNoDataValue()

            if min(data) == no_data:
                for z_cell in data:
                    if z_cell != no_data and z_cell < self.z_min:
                        self.z_min = z_cell
            elif math.isnan(min(data)):
                self.z_max = 0
                self.z_min = 0
                for z_cell in data:
                    if not math.isnan(z_cell):
                        if self.z_min > z_cell:
                            self.z_min = z_cell
                        if self.z_max < z_cell:
                            self.z_max = z_cell
            else:
                self.z_min = min(data)

            self.z_max = round(self.z_max, 3)
            self.z_min = round(self.z_min, 3)
            self.ui.ZMaxLabel.setText(str(self.z_max) + ' m')
            self.ui.ZMinLabel.setText(str(self.z_min) + ' m')

        dem_dataset = None
        QApplication.restoreOverrideCursor()

    # endregion

    # region Dimensions function

    def get_min_spacing(self):
        min_spacing = 0
        if self.units == 0:  # Meters
            if self.layer.crs().mapUnits() == 0:
                width_roi = self.roi_x_max - self.roi_x_min
                min_spacing = round(self.cell_size * self.width / width_roi, 2)
            elif self.layer.crs().mapUnits() == 2:
                width_roi = self.roi_x_max - self.roi_x_min
                cell_size_m = self.cell_size * math.pi / 180 * math.cos(self.roi_y_max * math.pi / 180) * 6371000
                min_spacing = round(cell_size_m * self.width / width_roi, 2)
            # min_spacing = self.cell_size/self.scale
        elif self.units == 6:  # Degree
            if self.layer.crs().mapUnits() == 0:
                width_roi = self.roi_x_max - self.roi_x_min
                cell_size_deg = self.cell_size / math.pi * 180 / math.cos(self.roi_y_max * math.pi / 180) / 6371000
                min_spacing = round(cell_size_deg * self.width / width_roi, 2)
            elif self.layer.crs().mapUnits() == 2:
                width_roi = self.roi_x_max - self.roi_x_min
                min_spacing = round(self.cell_size * self.width / width_roi, 2)
        if min_spacing < 0.2:
            self.ui.RecomSpacinglabel.setText('0.2 mm')
        else:
            self.ui.RecomSpacinglabel.setText(str(min_spacing) + ' mm')

    def upload_size_from_height(self):
        try:
            width_roi = self.roi_x_max - self.roi_x_min
            height_roi = self.roi_y_max - self.roi_y_min
            self.height = float(self.ui.HeightLineEdit.text())
            self.width = round(width_roi * self.height / height_roi, 2)
            self.ui.WidthLineEdit.setText(str(self.width))
            if self.units == 0:  # Meters
                self.scale_h = height_roi / self.height * 1000
                self.scale_w = width_roi / self.width * 1000
                self.scale = round((self.scale_h + self.scale_w) / 2, 6)
                self.ui.ScaleLineEdit.setText(str(int(self.scale)))
            elif self.units == 6:  # Degree
                dist = width_roi * math.pi / 180 * math.cos(self.roi_y_max * math.pi / 180) * 6371000 * 1000
                self.scale = round(dist / self.width, 6)
                self.scale_h = self.scale
                self.scale_w = self.scale
                self.ui.ScaleLineEdit.setText(str(int(self.scale)))
            self.get_min_spacing()
            self.get_height_model()
        except ZeroDivisionError:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Define print extent"))
            self.ui.HeightLineEdit.clear()
        except ValueError:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Value entered incorrect"))
            self.ui.HeightLineEdit.clear()

    def upload_size_from_width(self):
        try:
            width_roi = self.roi_x_max - self.roi_x_min
            height_roi = self.roi_y_max - self.roi_y_min
            self.width = float(self.ui.WidthLineEdit.text())
            self.height = round(height_roi * self.width / width_roi, 2)
            self.ui.HeightLineEdit.setText(str(self.height))
            if self.units == 0:  # Meters
                self.scale_h = height_roi / self.height * 1000
                self.scale_w = width_roi / self.width * 1000
                self.scale = round((self.scale_h + self.scale_w) / 2, 6)
                self.ui.ScaleLineEdit.setText(str(int(self.scale)))
            elif self.units == 6:  # Degree
                dist = width_roi * math.pi / 180 * math.cos(self.roi_y_max * math.pi / 180) * 6371000 * 1000
                self.scale = round(dist / self.width, 6)
                self.scale_h = self.scale
                self.scale_w = self.scale
                self.ui.ScaleLineEdit.setText(str(int(self.scale)))
            self.get_min_spacing()
            self.get_height_model()
        except ZeroDivisionError:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Define size model"))
            self.ui.WidthLineEdit.clear()
        except ValueError:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Value entered incorrect"))
            self.ui.WidthLineEdit.clear()

    def upload_size_from_scale(self):
        try:
            width_roi = self.roi_x_max - self.roi_x_min
            height_roi = self.roi_y_max - self.roi_y_min
            self.scale = float(self.ui.ScaleLineEdit.text())
            self.scale_h = self.scale
            self.scale_w = self.scale
            if self.units == 6:  # Degree
                dist = width_roi * math.pi / 180 * math.cos(self.roi_y_max * math.pi / 180) * 6371000 * 1000
                self.width = round(dist / self.scale, 2)
                self.ui.WidthLineEdit.setText(str(self.width))
                self.height = round(height_roi * self.width / width_roi, 2)
                self.ui.HeightLineEdit.setText(str(self.height))
            elif self.units == 0:  # Meters
                self.height = round(height_roi / self.scale * 1000, 2)
                self.ui.HeightLineEdit.setText(str(self.height))
                self.width = round(width_roi / self.scale * 1000, 2)
                self.ui.WidthLineEdit.setText(str(self.width))
            self.get_min_spacing()
            self.get_height_model()

        except ZeroDivisionError:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Define print extent"))
            self.ui.ScaleLineEdit.clear()
            self.scale = 0
            self.ui.WidthLineEdit.clear()
        except ValueError:
            QMessageBox.warning(self, self.tr("Attention"), self.tr("Value entered incorrect"))
            self.ui.ScaleLineEdit.clear()
            self.scale = 0
            self.ui.WidthLineEdit.clear()
            self.ui.HeightLineEdit.clear()

    # endregion

    def get_height_model(self):
        if self.ui.BaseHeightLineEdit.text() == '' or self.ui.BaseHeightLineEdit.text() == '-':
            return
        try:
            z_base = float(self.ui.BaseHeightLineEdit.text())
            self.z_scale = self.ui.ZScaleDoubleSpinBox.value()
            h_model = round((self.z_max - z_base) / self.scale * 1000 * self.z_scale + 2, 1)
            if h_model == float("inf"):
                QMessageBox.warning(self, self.tr("Attention"), self.tr("Define size model"))
                self.ui.BaseHeightLineEdit.clear()
                return
            if z_base <= self.z_max:
                self.ui.HeightModelLabel.setText(str(h_model) + ' mm')
            else:
                QMessageBox.warning(self, self.tr("Attention"), self.tr("Height of the base must be lower than DEM highest point"))
                self.ui.BaseHeightLineEdit.clear()
        except ZeroDivisionError:
            if self.scale == 0 and self.roi_x_max != 0:
                QMessageBox.warning(self, self.tr("Attention"), self.tr("Define size model"))
            else:
                QMessageBox.warning(self, self.tr("Attention"), self.tr("Define print extent"))
            self.ui.BaseHeightLineEdit.clear()

    def get_parameters(self):
        projected = True
        if self.units == 0:  # Meters
            projected = True
        elif self.units == 6:  # Degree
            projected = False

        provider = self.layer.dataProvider()
        path = provider.dataSourceUri()
        path_layer = path.split('|')
        self.z_scale = self.ui.ZScaleDoubleSpinBox.value()

        self.get_height_model()
        try:
            spacing_mm = float(self.ui.SpacingLineEdit.text())
            z_base = float(self.ui.BaseHeightLineEdit.text())
        except ValueError:
            return 0

        if self.ui.RevereseZCheckBox.isChecked():
            z_inv = True
        else:
            z_inv = False

        return {"layer": path_layer[0],
                "roi_x_max": self.roi_x_max, "roi_x_min": self.roi_x_min, "roi_y_max": self.roi_y_max, "roi_y_min": self.roi_y_min,
                "spacing_mm": spacing_mm, "height": self.height, "width": self.width,
                "z_scale": self.z_scale, "scale": self.scale, "scale_h": self.scale_h, "scale_w": self.scale_w,
                "z_inv": z_inv, "z_base": z_base,
                "projected": projected, "crs_layer": self.layer.crs(), "crs_map": self.map_crs}



class RectangleMapTool(QgsMapTool):
    startPoint = None
    endPoint = None
    isEmittingPoint = True

    def __init__(self, canvas, callback):
        self.canvas = canvas
        QgsMapTool.__init__(self, self.canvas)
        self.callback = callback
        self.rubberBand = QgsRubberBand(self.canvas, True)
        self.rubberBand.setColor(QColor(227, 26, 28, 255))
        self.rubberBand.setWidth(3)
        self.rubberBand.setLineStyle(Qt.PenStyle(Qt.DashLine))
        self.reset()

    def reset(self):
        self.startPoint = self.endPoint = None
        self.isEmittingPoint = False
        self.rubberBand.reset(True)

    def canvasPressEvent(self, e):
        self.startPoint = self.toMapCoordinates(e.pos())
        self.endPoint = self.startPoint
        self.isEmittingPoint = True
        self.showRect(self.startPoint, self.endPoint)

    def canvasReleaseEvent(self, e):
        self.isEmittingPoint = False
        r = self.rectangle()
        if r is not None:
            # print "Rectangle:", r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()
            self.rubberBand.hide()
            self.callback(r)
        return None

    def canvasMoveEvent(self, e):
        if not self.isEmittingPoint:
            return
        self.endPoint = self.toMapCoordinates(e.pos())
        self.showRect(self.startPoint, self.endPoint)

    def showRect(self, start_point, end_point):
        self.rubberBand.reset(True)
        if start_point.x() == end_point.x() or start_point.y() == end_point.y():
            return
        point1 = QgsPointXY(start_point.x(), start_point.y())
        point2 = QgsPointXY(start_point.x(), end_point.y())
        point3 = QgsPointXY(end_point.x(), end_point.y())
        point4 = QgsPointXY(end_point.x(), start_point.y())
        self.rubberBand.addPoint(point1, False)
        self.rubberBand.addPoint(point2, False)
        self.rubberBand.addPoint(point3, False)
        self.rubberBand.addPoint(point4, False)
        self.rubberBand.addPoint(point1, True)  # true to update canvas
        self.rubberBand.show()

    def rectangle(self):
        if self.startPoint is None or self.endPoint is None:
            return None
        elif self.startPoint.x() == self.endPoint.x() or self.startPoint.y() == self.endPoint.y():
            return None
        return QgsRectangle(self.startPoint, self.endPoint)

    def deactivate(self):
        super(RectangleMapTool, self).deactivate()
        # self.emit(QtCore.SIGNAL("deactivated()"))
