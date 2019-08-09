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

from qgis.PyQt.QtWidgets import QDialog

from .Export_dialog_base import Ui_ExportDialogBase
from ..model_builder.Model_Builder import Model
from ..model_builder.STL_Builder import STL


class Dialog(QDialog, Ui_ExportDialogBase):

    Model = None
    STL = None

    def __init__(self, parameters, file_name):
        """Constructor for the dialog."""
        QDialog.__init__(self)
        self.ui = Ui_ExportDialogBase()
        self.ui.setupUi(self)
        self.parameters = parameters

        self.stl_file = file_name
        self.do_model()

    def do_model(self):
        self.ui.ProgressLabel.setText(self.tr("Building STL geometry ..."))
        self.Model = Model(self.ui.progressBar, self.ui.ProgressLabel, self.ui.cancelButton, self.parameters)
        self.Model.updateProgress.connect(lambda: self.ui.progressBar.setValue(self.ui.progressBar.value() + 1))
        self.Model.finished.connect(self.do_stl_model)
        self.Model.start()

    def do_stl_model(self):
        if self.Model.quit:
            self.reject()
        else:
            self.ui.ProgressLabel.setText(self.tr("Creating STL file ..."))
            dem_matrix = self.Model.get_model()
            self.STL = STL(self.ui.progressBar, self.ui.ProgressLabel, self.ui.cancelButton, self.parameters,
                           self.stl_file, dem_matrix)
            self.STL.updateProgress.connect(lambda: self.ui.progressBar.setValue(self.ui.progressBar.value() + 1))
            self.STL.finished.connect(self.finish_model)
            self.STL.start()

    def finish_model(self):
        if self.STL.quit:
            os.remove(self.stl_file)
            self.reject()
        else:
            self.accept()
