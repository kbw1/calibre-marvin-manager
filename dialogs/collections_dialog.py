#!/usr/bin/env python
# coding: utf-8

from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2010, Gregory Riker'
__docformat__ = 'restructuredtext en'

import os, sqlite3, sys
from functools import partial

from calibre import strftime
from calibre.devices.usbms.driver import debug_print
from calibre.utils.icu import sort_key
from calibre.utils.magick.draw import add_borders_to_image, thumbnail

from calibre_plugins.marvin_manager.book_status import dialog_resources_path
from calibre_plugins.marvin_manager.common_utils import SizePersistedDialog

from PyQt4.Qt import (Qt, QAbstractItemModel, QAbstractListModel, QColor,
                      QDialog, QDialogButtonBox, QIcon,
                      QModelIndex, QPalette, QPixmap, QSize, QSizePolicy, QVariant,
                      pyqtSignal)

# Import Ui_Form from form generated dynamically during initialization
if True:
    sys.path.insert(0, dialog_resources_path)
    from collections_ui import Ui_Dialog
    sys.path.remove(dialog_resources_path)

class MyListModel(QAbstractListModel):

    def __init__(self, datain, parent=None, *args):
        '''
        datain: a list where each item is a row
        '''
        QAbstractItemModel.__init__(self, parent, *args)
        self.listdata = datain

    def rowCount(self, parent=QModelIndex()):
        return len(self.listdata)

    def data(self, index, role):
        if index.isValid() and role == Qt.DisplayRole:
            return QVariant(self.listdata[index.row()])
        else:
            return QVariant()

class CollectionsManagementDialog(SizePersistedDialog, Ui_Dialog):
    LOCATION_TEMPLATE = "{cls}:{func}({arg1}) {arg2}"

    marvin_device_status_changed = pyqtSignal(str)

    def accept(self):
        self._log_location()
        super(CollectionsManagementDialog, self).accept()

    def close(self):
        self._log_location()
        super(CollectionsManagementDialog, self).close()

    def dispatch_button_click(self, button):
        '''
        BUTTON_ROLES = ['AcceptRole', 'RejectRole', 'DestructiveRole', 'ActionRole',
                        'HelpRole', 'YesRole', 'NoRole', 'ApplyRole', 'ResetRole']
        '''
        self._log_location()
        if self.bb.buttonRole(button) == QDialogButtonBox.AcceptRole:
            self._log("AcceptRole")
            self.accept()

        elif self.bb.buttonRole(button) == QDialogButtonBox.RejectRole:
            self._log("RejectRole")
            self.close()

    def esc(self, *args):
        self.close()

    def export_to_marvin(self):
        self._log_location()

    def import_from_marvin(self):
        self._log_location()

    def initialize(self, parent, book_title, calibre_collections, marvin_collections, connected_device):
        '''
        __init__ is called on SizePersistedDialog()
        '''
        self.setupUi(self)
        self.calibre_collections = calibre_collections
        self.marvin_collections = marvin_collections
        self.opts = parent.opts
        self.parent = parent
        self.stored_command = None
        self.verbose = parent.verbose

        self._log_location(book_title)
        self.setWindowTitle(book_title)

        # Subscribe to Marvin driver change events
        connected_device.marvin_device_signals.reader_app_status_changed.connect(
            self.marvin_status_changed)

        # ~~~~~~~~ Export to Marvin button ~~~~~~~~
        self.export_to_marvin_tb.setIcon(QIcon(os.path.join(self.opts.resources_path,
                                                   'icons',
                                                   'from_calibre.png')))
        self.export_to_marvin_tb.clicked.connect(partial(self.store_command, 'export_collections'))

        # ~~~~~~~~ Import from Marvin button ~~~~~~~~
        self.import_from_marvin_tb.setIcon(QIcon(os.path.join(self.opts.resources_path,
                                                   'icons',
                                                   'from_marvin.png')))
        self.import_from_marvin_tb.clicked.connect(partial(self.store_command, 'import_collections'))

        # ~~~~~~~~ Synchronize collections button ~~~~~~~~
        self.synchronize_collections_tb.setIcon(QIcon(os.path.join(self.opts.resources_path,
                                                          'icons',
                                                          'sync_collections.png')))
        self.synchronize_collections_tb.clicked.connect(partial(self.store_command, 'synchronize_collections'))

        # ~~~~~~~~ Clear all collections button ~~~~~~~~
        self.clear_all_collections_tb.setIcon(QIcon(os.path.join(self.opts.resources_path,
                                                          'icons',
                                                          'clear_all.png')))
        self.clear_all_collections_tb.clicked.connect(partial(self.store_command, 'clear_all_collections'))

        # Populate collection models
        self._populate_collection_models()

        # Remind the user of calibre's custom column, disable buttons if no calibre field
        calibre_cf = self.prefs.get('collection_field_comboBox', '')
        if calibre_cf:
            self.calibre_gb.setTitle("Calibre collections (%s)" % calibre_cf)
        else:
            self.calibre_gb.setTitle("Calibre (no collections field)")
            self.calibre_gb.setEnabled(False)
            # Disable import/export/sync
            self.export_to_marvin_tb.setEnabled(False)
            self.import_from_marvin_tb.setEnabled(False)
            self.synchronize_collections_tb.setEnabled(False)

        # If collections already equal, disable import/export/sync
        if self.calibre_collections == self.marvin_collections:
            self.export_to_marvin_tb.setEnabled(False)
            self.import_from_marvin_tb.setEnabled(False)
            self.synchronize_collections_tb.setEnabled(False)

        # Set the bg color of the description text fields to the dialog bg color
        bgcolor = self.palette().color(QPalette.Background)
        palette = QPalette()
        palette.setColor(QPalette.Base, bgcolor)
        self.calibre_lw.setPalette(palette)
        self.marvin_lw.setPalette(palette)

        # Hook the button events
        self.bb.clicked.connect(self.dispatch_button_click)

        # Restore position
        self.resize_dialog()

    def marvin_status_changed(self, command):
        '''

        '''
        self.marvin_device_status_changed.emit(command)

        self._log_location(command)

        if command in ['disconnected', 'yanked']:
            self._log("closing dialog: %s" % command)
            self.close()

    def store_command(self, command):
        '''
        Save the requested operation
        '''
        self._log_location(command)
        self.stored_command = command
        self.close()

    def _populate_collection_models(self):
        '''
        Populate the data model with current collection assignments
        '''
        self._log_location()
        self.marvin_lw.setModel(MyListModel(self.marvin_collections))
        self.calibre_lw.setModel(MyListModel(self.calibre_collections))

    def _log(self, msg=None):
        '''
        Print msg to console
        '''
        if not self.verbose:
            return

        if msg:
            debug_print(" %s" % msg)
        else:
            debug_print()

    def _log_location(self, *args):
        '''
        Print location, args to console
        '''
        if not self.verbose:
            return

        arg1 = arg2 = ''

        if len(args) > 0:
            arg1 = args[0]
        if len(args) > 1:
            arg2 = args[1]

        debug_print(self.LOCATION_TEMPLATE.format(
            cls=self.__class__.__name__,
            func=sys._getframe(1).f_code.co_name,
            arg1=arg1, arg2=arg2))

