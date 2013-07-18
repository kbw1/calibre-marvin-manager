#!/usr/bin/env python
# coding: utf-8
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2013, Greg Riker <griker@hotmail.com>'
__docformat__ = 'restructuredtext en'

import hashlib, importlib, locale, operator, os, re, sqlite3, sys, time
from datetime import datetime
from functools import partial
from lxml import etree
from threading import Timer


from PyQt4 import QtCore, QtGui
from PyQt4.Qt import (Qt, QAbstractTableModel,
                      QApplication, QBrush,
                      QCheckBox, QColor, QCursor, QDialog, QDialogButtonBox, QFont, QIcon,
                      QLabel, QMenu, QModelIndex, QPainter, QPixmap, QString,
                      QTableView, QTableWidgetItem, QTimer,
                      QVariant, QVBoxLayout, QWidget,
                      SIGNAL, pyqtSignal)
from PyQt4.QtWebKit import QWebView

from calibre import prints, strftime
from calibre.constants import cache_dir as _cache_dir, islinux, isosx, iswindows
from calibre.devices.errors import UserFeedback
from calibre.devices.usbms.driver import debug_print
from calibre.ebooks.BeautifulSoup import BeautifulStoneSoup, Tag
from calibre.ebooks.oeb.iterator import EbookIterator
from calibre.gui2 import Application
from calibre.gui2.dialogs.message_box import MessageBox
from calibre.gui2.progress_indicator import ProgressIndicator
from calibre.utils.config import config_dir, JSONConfig
from calibre.utils.icu import sort_key
from calibre.utils.magick.draw import thumbnail
from calibre.utils.wordcount import get_wordcount_obj
from calibre.utils.zipfile import ZipFile

from calibre_plugins.marvin_manager.common_utils import (
    AbortRequestException, Book, HelpView, InventoryCollections, MyAbstractItemModel,
    MyBlockingBusy, ProgressBar, SizePersistedDialog, Struct)

dialog_resources_path = os.path.join(config_dir, 'plugins', 'Marvin_Mangler_resources', 'dialogs')


class MyTableView(QTableView):
    def __init__(self, parent):
        super(MyTableView, self).__init__(parent)
        self.parent = parent

    def contextMenuEvent(self, event):

        index = self.indexAt(event.pos())
        col = index.column()
        row = index.row()
        selected_books = self.parent._selected_books()
        menu = QMenu(self)

        if col == self.parent.ANNOTATIONS_COL:
            no_annotations = not selected_books[row]['has_annotations']
            ac = menu.addAction("View annotations && highlights")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'annotations.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "show_highlights", row))
            if len(selected_books) > 1 or no_annotations:
                ac.setEnabled(False)

        elif col == self.parent.ARTICLES_COL:
            no_articles = not selected_books[row]['has_articles']
            ac = menu.addAction("View articles")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'articles.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "show_articles", row))
            if len(selected_books) > 1 or no_articles:
                ac.setEnabled(False)

        elif col == self.parent.COLLECTIONS_COL:
            cfl = self.parent.prefs.get('collection_field_lookup', '')
            ac = menu.addAction("View collection assignments")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'update_metadata.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "show_collections", row))
            if len(selected_books) > 1:
                ac.setEnabled(False)

            ac = menu.addAction("Export calibre collections to Marvin")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'from_calibre.png')))
            if cfl:
                ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "export_collections", row))
            else:
                ac.setEnabled(False)

            ac = menu.addAction("Import Marvin collections to calibre")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'from_marvin.png')))
            if cfl:
                ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "import_collections", row))
            else:
                ac.setEnabled(False)

            ac = menu.addAction("Merge collections")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'sync_collections.png')))
            if cfl:
                ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "synchronize_collections", row))
            else:
                ac.setEnabled(False)

            ac = menu.addAction("Remove from all collections")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'clear_all.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "clear_all_collections", row))

            menu.addSeparator()

            ac = menu.addAction("Manage collections")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'edit_collections.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "manage_collections", row))

        elif col == self.parent.DEEP_VIEW_COL:
            ac = menu.addAction("Generate Deep View content")
            ac.setIcon(QIcon(I('exec.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "create_deep_view", row))

            menu.addSeparator()

            no_dv_content = not selected_books[row]['has_dv_content']

            ac = menu.addAction("Deep View content sorted alphabetically")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'deep_view.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event,
                                         "show_deep_view_alphabetically", row))
            if len(selected_books) > 1 or no_dv_content:
                ac.setEnabled(False)

            ac = menu.addAction("Deep View content sorted by importance")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'deep_view.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event,
                                         "show_deep_view_by_importance", row))
            if len(selected_books) > 1 or no_dv_content:
                ac.setEnabled(False)

            ac = menu.addAction("Deep View content sorted by order of appearance")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'deep_view.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event,
                                         "show_deep_view_by_appearance", row))
            if len(selected_books) > 1 or no_dv_content:
                ac.setEnabled(False)

            ac = menu.addAction("Deep View content with annotations")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'deep_view.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event,
                                         "show_deep_view_by_annotations", row))
            if len(selected_books) > 1 or no_dv_content:
                ac.setEnabled(False)

        elif col == self.parent.FLAGS_COL:
            ac = menu.addAction("Clear All")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'clear_all.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "clear_all_flags", row))
            ac = menu.addAction("Clear New")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'clear_new.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "clear_new_flag", row))
            ac = menu.addAction("Clear Reading list")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'clear_reading.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "clear_reading_list_flag", row))
            ac = menu.addAction("Clear Read")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'clear_read.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "clear_read_flag", row))
            menu.addSeparator()
            ac = menu.addAction("Set New")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'set_new.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "set_new_flag", row))
            ac = menu.addAction("Set Reading list")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'set_reading.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "set_reading_list_flag", row))
            ac = menu.addAction("Set Read")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'set_read.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "set_read_flag", row))

        elif col == self.parent.LAST_OPENED_COL:
            date_read_field = self.parent.prefs.get('date_read_field_comboBox', None)

            # Test for calibre cids
            calibre_cids = False
            for row in selected_books:
                if selected_books[row]['cid'] is not None:
                    calibre_cids = True
                    break

            # Test for active Last Opened dates
            last_opened = False
            for row in selected_books:
                if selected_books[row]['last_opened'] > '':
                    last_opened = True
                    break

            title = "No 'Date read' custom field selected"
            if date_read_field:
                title = "Apply date to '%s' column" % date_read_field
            ac = menu.addAction(title)
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'from_marvin.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "apply_date_read", row))

            if (not date_read_field) or (not calibre_cids) or (not last_opened):
                ac.setEnabled(False)

        elif col in [self.parent.TITLE_COL, self.parent.AUTHOR_COL]:
            ac = menu.addAction("View metadata")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'update_metadata.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "show_metadata", row))
            if len(selected_books) > 1:
                ac.setEnabled(False)

            ac = menu.addAction("Export metadata from calibre to Marvin")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'from_calibre.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "export_metadata", row))

            ac = menu.addAction("Import metadata from Marvin to calibre")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'from_marvin.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "import_metadata", row))

        elif col == self.parent.VOCABULARY_COL:
            no_vocabulary = not selected_books[row]['has_vocabulary']

            ac = menu.addAction("View vocabulary for this book")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'vocabulary.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "show_vocabulary", row))
            if len(selected_books) > 1 or no_vocabulary:
                ac.setEnabled(False)

            ac = menu.addAction("View all vocabulary words")
            ac.setIcon(QIcon(I('books_in_series.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "show_global_vocabulary", row))

        elif col == self.parent.WORD_COUNT_COL:
            ac = menu.addAction("Calculate word count")
            ac.setIcon(QIcon(os.path.join(self.parent.opts.resources_path, 'icons', 'word_count.png')))
            ac.triggered.connect(partial(self.parent.dispatch_context_menu_event, "calculate_word_count", row))

        menu.exec_(event.globalPos())


class _SortableImageWidgetItem(QLabel):
    def __init__(self, parent, path, sort_key, column):
        super(SortableImageWidgetItem, self).__init__(parent=parent.tv)
        self.column = column
        self.parent = parent.tv
        self.picture = QPixmap(path)
        self.sort_key = sort_key
        self.width = self.picture.width()
        self.setAlignment(Qt.AlignCenter)
        self.setPixmap(self.picture)


class SortableImageWidgetItem(QWidget):
    def __init__(self, parent, path, sort_key, column):
        super(SortableImageWidgetItem, self).__init__(parent=parent.tv)
        self.column = column
        self.parent_tv = parent.tv
        self.picture = QPixmap(path)
        self.sort_key = sort_key
        self.width = self.picture.width()

    def __lt__(self, other):
        return self.sort_key < other.sort_key

    def _paintEvent(self, event):
        #print("column_width: %s" % (repr(self.parent_tv.columnWidth(self.column))))
        #print("picture_width: %s" % repr(self.width))
        #print("event: %s" % dir(event))
        #print("region: %s" % dir(event.region()))
        #print("region().boundingRect(): %s" % repr(event.region().boundingRect()))
        #print("boundingRect: %s" % dir(event.region().boundingRect()))
        #print("getCoords: %s" % repr(event.region().boundingRect().getCoords()))
        #print("getRect: %s" % repr(event.region().boundingRect().getRect()))
        #print("column_viewport_position: %d" % self.parent_tv.columnViewportPosition(self.column))
        #print("dir(self.parent_tv): %s" % dir(self.parent_tv))
        #cvp = self.parent_tv.columnViewportPosition(self.column)
        #painter = QPainter(self.parent_tv.viewport())
        painter = QPainter(self)
        x_off = 0
        col_width = self.parent_tv.columnWidth(self.column)
        if col_width > self.width:
            x_off = int((col_width - self.width) / 2)
        #print("x_off: %d" % x_off)
        #painter.drawPixmap(x_off, 0, self.picture)
        painter.drawPixmap(event.region().boundingRect(), self.picture)
        painter.end()
        #QWidget.paintEvent(self, event)


class SortableTableWidgetItem(QTableWidgetItem):
    """
    Subclass widget sortable by sort_key
    """
    def __init__(self, text, sort_key):
        super(SortableTableWidgetItem, self).__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other):
        return self.sort_key < other.sort_key


class MarkupTableModel(QAbstractTableModel):
    #http://www.saltycrane.com/blog/2007/12/pyqt-43-qtableview-qabstracttablemodel/

    SATURATION = 0.40
    HSVALUE = 1.0
    RED_HUE = 0.0
    ORANGE_HUE = 0.08325
    YELLOW_HUE = 0.1665
    GREEN_HUE = 0.333
    WHITE_HUE = 1.0

    def __init__(self, parent=None, centered_columns=[], right_aligned_columns=[], *args):
        """
        datain: a list of lists
        headerdata: a list of strings
        """
        QAbstractTableModel.__init__(self, parent, *args)
        self.parent = parent
        self.arraydata = parent.tabledata
        self.centered_columns = centered_columns
        self.right_aligned_columns = right_aligned_columns
        self.headerdata = parent.LIBRARY_HEADER
        self.show_match_colors = parent.show_match_colors

    def rowCount(self, parent):
        return len(self.arraydata)

    def columnCount(self, parent):
        return len(self.headerdata)

    def data(self, index, role):
        row, col = index.row(), index.column()
        if not index.isValid():
            return QVariant()

        elif role == Qt.BackgroundRole and self.show_match_colors:
            match_quality = self.arraydata[row][self.parent.MATCHED_COL]
            if match_quality == 4:
                return QVariant(QBrush(QColor.fromHsvF(self.GREEN_HUE, self.SATURATION, self.HSVALUE)))
            elif match_quality == 3:
                return QVariant(QBrush(QColor.fromHsvF(self.YELLOW_HUE, self.SATURATION, self.HSVALUE)))
            elif match_quality == 2:
                return QVariant(QBrush(QColor.fromHsvF(self.ORANGE_HUE, self.SATURATION, self.HSVALUE)))
            elif match_quality == 1:
                return QVariant(QBrush(QColor.fromHsvF(self.RED_HUE, self.SATURATION, self.HSVALUE)))
            else:
                return QVariant(QBrush(QColor.fromHsvF(self.WHITE_HUE, 0.0, self.HSVALUE)))

        elif role == Qt.DecorationRole and col == self.parent.FLAGS_COL:
            return self.arraydata[row][self.parent.FLAGS_COL].picture

        elif role == Qt.DecorationRole and col == self.parent.COLLECTIONS_COL:
            return self.arraydata[row][self.parent.COLLECTIONS_COL].picture

        elif (role == Qt.DisplayRole and
              col == self.parent.PROGRESS_COL
              and self.parent.prefs.get('show_progress_as_percentage', False)):
            return self.arraydata[row][self.parent.PROGRESS_COL].text()
        elif (role == Qt.DecorationRole and
              col == self.parent.PROGRESS_COL
              and not self.parent.prefs.get('show_progress_as_percentage', False)):
            return self.arraydata[row][self.parent.PROGRESS_COL].picture

        elif role == Qt.DisplayRole and col == self.parent.TITLE_COL:
            return self.arraydata[row][self.parent.TITLE_COL].text()
        elif role == Qt.DisplayRole and col == self.parent.AUTHOR_COL:
            return self.arraydata[row][self.parent.AUTHOR_COL].text()
        elif role == Qt.DisplayRole and col == self.parent.LAST_OPENED_COL:
            return self.arraydata[row][self.parent.LAST_OPENED_COL].text()
        elif role == Qt.TextAlignmentRole and (col in self.centered_columns):
            return Qt.AlignHCenter
        elif role == Qt.TextAlignmentRole and (col in self.right_aligned_columns):
            return Qt.AlignRight

        elif role == Qt.ToolTipRole and col in [self.parent.TITLE_COL,
                                                self.parent.AUTHOR_COL]:
            return "<p>Double-click for metadata<br/>Right-click for more options</p>"
        elif role == Qt.ToolTipRole and col in [self.parent.ANNOTATIONS_COL,
                                                self.parent.ARTICLES_COL,
                                                self.parent.COLLECTIONS_COL,
                                                self.parent.VOCABULARY_COL]:
            return "<p>Double-click to view<br/>Right-click for more options</p>"
        elif role == Qt.ToolTipRole and col in [self.parent.FLAGS_COL]:
            return "<p>Right-click for options</p>"
        elif role == Qt.ToolTipRole and col in [self.parent.WORD_COUNT_COL]:
            return "<p>Double-click to generate word count</p>"


        elif role != Qt.DisplayRole:
            return QVariant()


        return QVariant(self.arraydata[index.row()][index.column()])

    def refresh(self, show_match_colors):
        self.show_match_colors = show_match_colors
        self.dataChanged.emit(self.createIndex(0,0),
                              self.createIndex(self.rowCount(0), self.columnCount(0)))

    def headerData(self, col, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return QVariant(self.headerdata[col])
#         if role == Qt.ToolTipRole:
#             if orientation == Qt.Horizontal:
#                 return QString("Tooltip for col %d" % col)

        return QVariant()

    def setData(self, index, value, role):
        row, col = index.row(), index.column()
        self.emit(SIGNAL("dataChanged(QModelIndex,QModelIndex)"), index, index)
        return True

    def sort(self, Ncol, order):
        """
        Sort table by given column number.
        """
        self.emit(SIGNAL("layoutAboutToBeChanged()"))
        self.arraydata = sorted(self.arraydata, key=operator.itemgetter(Ncol))
        if order == Qt.DescendingOrder:
            self.arraydata.reverse()
        self.emit(SIGNAL("layoutChanged()"))


class BookStatusDialog(SizePersistedDialog):
    '''
    '''
    # Location reporting template
    LOCATION_TEMPLATE = "{cls}:{func}({arg1}) {arg2}"

    CHECKMARK = u"\u2713"

    # Flag constants
    if True:
        FLAGS = {
                'new': 'NEW',
                'read': 'READ',
                'reading_list': 'READING LIST'
                }

        # Binary values for flag updates
        NEW_FLAG = 4
        READING_FLAG = 2
        READ_FLAG = 1

    # Column assignments
    if True:
        LIBRARY_HEADER = ['uuid', 'cid', 'mid', 'path',
                          'Title', 'Author', 'Word Count', 'Progress', 'Last Opened',
                          'Collections', 'Flags',
                          'Annotations', 'Articles', 'Deep View', 'Vocabulary',
                          'Match Quality']
        ANNOTATIONS_COL = LIBRARY_HEADER.index('Annotations')
        ARTICLES_COL = LIBRARY_HEADER.index('Articles')
        AUTHOR_COL = LIBRARY_HEADER.index('Author')
        BOOK_ID_COL = LIBRARY_HEADER.index('mid')
        CALIBRE_ID_COL = LIBRARY_HEADER.index('cid')
        COLLECTIONS_COL = LIBRARY_HEADER.index('Collections')
        DEEP_VIEW_COL = LIBRARY_HEADER.index('Deep View')
        FLAGS_COL = LIBRARY_HEADER.index('Flags')
        LAST_OPENED_COL = LIBRARY_HEADER.index('Last Opened')
        MATCHED_COL = LIBRARY_HEADER.index('Match Quality')
        PATH_COL = LIBRARY_HEADER.index('path')
        PROGRESS_COL = LIBRARY_HEADER.index('Progress')
        TITLE_COL = LIBRARY_HEADER.index('Title')
        UUID_COL = LIBRARY_HEADER.index('uuid')
        VOCABULARY_COL = LIBRARY_HEADER.index('Vocabulary')
        WORD_COUNT_COL = LIBRARY_HEADER.index('Word Count')

        HIDDEN_COLUMNS =    [
                             UUID_COL,
                             CALIBRE_ID_COL,
                             BOOK_ID_COL,
                             PATH_COL,
                             MATCHED_COL,
                            ]
        CENTERED_COLUMNS =  [
                             ANNOTATIONS_COL,
                             COLLECTIONS_COL,
                             DEEP_VIEW_COL,
                             ARTICLES_COL,
                             LAST_OPENED_COL,
                             VOCABULARY_COL,
                             ]
        RIGHT_ALIGNED_COLUMNS = [
                             PROGRESS_COL,
                             WORD_COUNT_COL
                             ]

    # Marvin XML command template
    if True:
        COMMAND_XML = b'''\xef\xbb\xbf<?xml version='1.0' encoding='utf-8'?>
        <{0} timestamp=\'{1}\'>
        <manifest>
        </manifest>
        </{0}>'''

    marvin_device_status_changed = pyqtSignal(str)

    def accept(self):
        self._log_location()
        self._save_column_widths()
        super(BookStatusDialog, self).accept()

    def capture_sort_column(self, sort_column):
        sort_order = self.tv.horizontalHeader().sortIndicatorOrder()
        self.opts.prefs.set('marvin_library_sort_column', sort_column)
        self.opts.prefs.set('marvin_library_sort_order', sort_order)

    def close(self):
        self._log_location()
        self._save_column_widths()
        super(BookStatusDialog, self).close()

    def dispatch_button_click(self, button):
        '''
        BUTTON_ROLES = ['AcceptRole', 'RejectRole', 'DestructiveRole', 'ActionRole',
                        'HelpRole', 'YesRole', 'NoRole', 'ApplyRole', 'ResetRole']
        '''
        self._log_location()
        if self.dialogButtonBox.buttonRole(button) == QDialogButtonBox.AcceptRole:
            self.accept()

        elif self.dialogButtonBox.buttonRole(button) == QDialogButtonBox.ActionRole:
            if button.objectName() == 'match_colors_button':
                self.toggle_match_colors()
#             elif button.objectName() == 'calculate_word_count_button':
#                 self._calculate_word_count()
            elif button.objectName() == 'manage_collections_button':
                self.show_manage_collections_dialog()
            elif button.objectName() == 'view_collections_button':
                selected_rows = self._selected_rows()
                if selected_rows:
                    self.show_view_collections_dialog(selected_rows[0])
                else:
                    title = "View collections"
                    msg = "<p>Select a book.</p>"
                    MessageBox(MessageBox.INFO, title, msg,
                           show_copy_button=False).exec_()
            elif button.objectName() == 'view_global_vocabulary_button':
                self.show_assets_dialog('show_global_vocabulary', 0)
            elif button.objectName() == 'view_metadata_button':
                selected_rows = self._selected_rows()
                if selected_rows:
                    self.show_view_metadata_dialog(selected_rows[0])
                else:
                    title = "View metadata"
                    msg = "<p>Select a book.</p>"
                    MessageBox(MessageBox.INFO, title, msg,
                           show_copy_button=False).exec_()

        elif self.dialogButtonBox.buttonRole(button) == QDialogButtonBox.DestructiveRole:
            self._delete_books()

        elif self.dialogButtonBox.buttonRole(button) == QDialogButtonBox.HelpRole:
            self.show_help()

        elif self.dialogButtonBox.buttonRole(button) == QDialogButtonBox.RejectRole:
            self.close()

    def dispatch_context_menu_event(self, action, row):
        '''
        '''
        self._log_location("%s row: %s" % (repr(action), row))

        if action == 'apply_date_read':
            self._apply_date_read()
        elif action == 'calculate_word_count':
            self._calculate_word_count()
        elif action in ['clear_new_flag', 'clear_reading_list_flag',
                        'clear_read_flag', 'clear_all_flags',
                        'set_new_flag', 'set_reading_list_flag', 'set_read_flag']:
            self._update_flags(action)
        elif action in ['show_articles',
                        'show_deep_view_alphabetically', 'show_deep_view_by_importance',
                        'show_deep_view_by_appearance', 'show_deep_view_by_annotations',
                        'show_highlights', 'show_vocabulary']:
            self.show_assets_dialog(action, row)
        elif action == 'manage_collections':
            self.show_manage_collections_dialog()
        elif action == 'show_collections':
            self.show_view_collections_dialog(row)
        elif action == 'show_global_vocabulary':
            self.show_assets_dialog('show_global_vocabulary', row)
        elif action in ['clear_all_collections', 'export_collections',
                        'import_collections', 'synchronize_collections']:
            self._update_collections(action)
        elif action == 'show_metadata':
            self.show_view_metadata_dialog(row)
        elif action in ['export_metadata', 'import_metadata']:
            self._update_metadata(action)
        else:
            selected_books = self._selected_books()
            det_msg = ''
            for row in selected_books:
                det_msg += selected_books[row]['title'] + '\n'

            title = "Context menu event"
            msg = ("<p>{0}</p>".format(action) +
                    "<p>Click <b>Show details</b> for affected books</p>")

            MessageBox(MessageBox.INFO, title, msg, det_msg=det_msg,
                           show_copy_button=False).exec_()

    def dispatch_double_click(self, index):
        '''
        Display column data for selected book
        '''
        self._log_location()

        asset_actions = {
                        self.ANNOTATIONS_COL: 'show_highlights',
                        self.ARTICLES_COL: 'show_articles',
                        self.DEEP_VIEW_COL: 'show_deep_view',
                        self.VOCABULARY_COL: 'show_vocabulary'
                        }

        column = index.column()
        row = index.row()

        if column in [self.TITLE_COL, self.AUTHOR_COL]:
            self.show_view_metadata_dialog(row)
        elif column in [self.ANNOTATIONS_COL, self.DEEP_VIEW_COL,
                        self.ARTICLES_COL, self.VOCABULARY_COL]:
            self.show_assets_dialog(asset_actions[column], row)
        elif column == self.COLLECTIONS_COL:
            self.show_view_collections_dialog(row)
        elif column in [self.FLAGS_COL]:
            title = "Flag options"
            msg = "<p>Right-click in the Flags column for flag management options.</p>"
            MessageBox(MessageBox.INFO, title, msg,
                   show_copy_button=False).exec_()
        elif column == self.WORD_COUNT_COL:
            #self._calculate_word_count()
            pass
        else:
            self._log("no double-click handler for %s" % self.LIBRARY_HEADER[column])

    def esc(self, *args):
        '''
        Clear any active selections
        '''
        self._log_location()
        self._clear_selected_rows()

    def initialize(self, parent):
        self.archived_cover_hashes = JSONConfig('plugins/Marvin_Mangler_resources/cover_hashes')
        self.hash_cache = 'content_hashes.zip'
        self.ios = parent.ios
        self.opts = parent.opts
        self.parent = parent
        self.prefs = parent.opts.prefs
        self.library_scanner = parent.library_scanner
        self.library_title_map = None
        self.library_uuid_map = None
        self.local_cache_folder = self.parent.connected_device.temp_dir
        self.local_hash_cache = None
        #self.reconnect_request_pending = False
        self.remote_cache_folder = '/'.join(['/Library','calibre.mm'])
        self.remote_hash_cache = None
        self.show_match_colors = self.prefs.get('show_match_colors', False)
        self.verbose = parent.verbose

        # Subscribe to Marvin driver change events
        self.parent.connected_device.marvin_device_signals.reader_app_status_changed.connect(
            self.marvin_status_changed)

        self._log_location()

        self.installed_books = self._generate_booklist()

        # ~~~~~~~~ Create the dialog ~~~~~~~~
        self.setWindowTitle(u'Marvin Library: %d books' % len(self.installed_books))
        self.setWindowIcon(self.opts.icon)
        self.l = QVBoxLayout(self)
        self.setLayout(self.l)
        self.perfect_width = 0

        # ~~~~~~~~ Create the Table ~~~~~~~~
        self.tv = MyTableView(self)
        self.tabledata = self._construct_table_data()
        self._construct_table_view()

        # ~~~~~~~~ Create the ButtonBox ~~~~~~~~
        self.dialogButtonBox = QDialogButtonBox(QDialogButtonBox.Help)

        self.delete_button = self.dialogButtonBox.addButton(self.dialogButtonBox.Discard)
        self.delete_button.setText('Delete')

        self.done_button = self.dialogButtonBox.addButton(self.dialogButtonBox.Ok)
        self.done_button.setText('Close')

        self.dialogButtonBox.setOrientation(Qt.Horizontal)
        self.dialogButtonBox.setCenterButtons(False)

        # Show/Hide Match Quality
        self.show_match_colors_button = self.dialogButtonBox.addButton("undefined", QDialogButtonBox.ActionRole)
        self.show_match_colors_button.setObjectName('match_colors_button')
        self.show_match_colors = not self.show_match_colors
        self.toggle_match_colors()

        # Word count
        if False:
            self.wc_button = self.dialogButtonBox.addButton('Calculate word count', QDialogButtonBox.ActionRole)
            self.wc_button.setObjectName('calculate_word_count_button')
            self.wc_button.setIcon(QIcon(os.path.join(self.parent.opts.resources_path,
                                                       'icons',
                                                       'word_count.png')))

        # Generate DV content
        if False:
            self.gdv_button = self.dialogButtonBox.addButton('Generate Deep View', QDialogButtonBox.ActionRole)
            self.gdv_button.setObjectName('generate_deep_view_button')
            self.gdv_button.setIcon(QIcon(os.path.join(self.parent.opts.resources_path,
                                                       'icons',
                                                       'deep_view.png')))

        # View metadata
        self.vm_button = self.dialogButtonBox.addButton('View metadata', QDialogButtonBox.ActionRole)
        self.vm_button.setObjectName('view_metadata_button')
        self.vm_button.setIcon(QIcon(os.path.join(self.parent.opts.resources_path,
                                                   'icons',
                                                   'update_metadata.png')))

        # View collections
        self.vc_button = self.dialogButtonBox.addButton('View collection assignments', QDialogButtonBox.ActionRole)
        self.vc_button.setObjectName('view_collections_button')
        self.vc_button.setIcon(QIcon(os.path.join(self.parent.opts.resources_path,
                                                   'icons',
                                                   'update_metadata.png')))

        # Manage collections
        if True:
            self.mc_button = self.dialogButtonBox.addButton('Manage collections', QDialogButtonBox.ActionRole)
            self.mc_button.setObjectName('manage_collections_button')
            self.mc_button.setIcon(QIcon(os.path.join(self.parent.opts.resources_path,
                                                       'icons',
                                                       'edit_collections.png')))

        # View Global vocabulary
        if True:
            self.gv_button = self.dialogButtonBox.addButton('View vocabulary', QDialogButtonBox.ActionRole)
            self.gv_button.setObjectName('view_global_vocabulary_button')
            self.gv_button.setIcon(QIcon(I('books_in_series.png')))

        self.dialogButtonBox.clicked.connect(self.dispatch_button_click)

        self.l.addWidget(self.dialogButtonBox)

        # ~~~~~~~~ Connect signals ~~~~~~~~
        self.connect(self.tv, SIGNAL("doubleClicked(QModelIndex)"), self.dispatch_double_click)
        self.connect(self.tv.horizontalHeader(), SIGNAL("sectionClicked(int)"), self.capture_sort_column)

        self.resize_dialog()

    def launch_collections_scanner(self):
        '''
        Invoke InventoryCollections to identify cids with collection assignments
        After indexing, self.library_inventory.collection_ids is list of cids
        '''
        self._log_location()
        self.library_inventory = InventoryCollections(self)
        self.connect(self.library_inventory, self.library_inventory.signal, self.library_inventory_complete)
        QTimer.singleShot(0, self.start_library_inventory)

        if False:
            # Wait for scan to start
            while not self.library_inventory.isRunning():
                Application.processEvents()

    def library_inventory_complete(self):
        self._log_location(repr(self.library_inventory.collection_ids))

    def marvin_status_changed(self, command):
        '''

        '''
        self.marvin_device_status_changed.emit(command)

        self._log_location(command)

        """
        if self.reconnect_request_pending:
            self._log("reconnect_request_pending")
        else:
            if command in ['disconnected', 'yanked']:
                self._log("closing dialog: %s" % command)
                self.close()
        """
        if command in ['disconnected', 'yanked']:
            self._log("closing dialog: %s" % command)
            self.close()

    def show_assets_dialog(self, action, row):
        '''
        Display assets associated with book
        Articles, Annotations, Deep View, Vocabulary
        profile = {'title': <dlg title>,
                   'group_box_title':<gb title>,
                   'header': <header text>,
                   'content': <default content>,
                   'footer': <footer text>}
        '''
        self._log_location(action)

        book_id = self._selected_book_id(row)
        title = self.installed_books[book_id].title

        if action == 'show_articles':
            header = None
            group_box_title = 'Articles'
            articles = self.installed_books[book_id].articles
            if articles:
                default_content = ''
                if 'Pinned' in articles:
                    default_content += "<p><b>Pinned:</b><br/>"
                    default_content += '<br/>'.join(articles['Pinned'].keys()) + "</p>"
                if 'Wiki' in articles:
                    default_content += "<p><b>Wiki</b><br/>"
                    default_content += '<br/>'.join(articles['Wiki'].keys()) + "</p>"
            else:
                default_content = ("<p>No articles</p>")
            footer = None

        elif action in ['show_deep_view_alphabetically', 'show_deep_view_by_importance',
                        'show_deep_view_by_appearance', 'show_deep_view_by_annotations']:
            header = None
            if action == 'show_deep_view_alphabetically':
                group_box_title = "Alphabetically"

            elif action == 'show_deep_view_by_importance':
                group_box_title = "By importance"

            elif action == 'show_deep_view_by_appearance':
                group_box_title = "By appearance"

            elif action == 'show_deep_view_by_annotations':
                group_box_title = "With annotations"

            default_content = "Deep View '{0}' content to be provided by Marvin.".format(group_box_title)
            footer = None

        elif action == 'show_global_vocabulary':
            title = "All vocabulary words"
            header = None
            group_box_title = "Vocabulary words by book"
            default_content = "<p>Global vocabulary to be provided by Marvin.</p>"
            footer = None

        elif action == 'show_highlights':
            header = None
            group_box_title = 'Highlights and Annotations'
            if self.installed_books[book_id].highlights:
                default_content = '\n'.join(self.installed_books[book_id].highlights)
            else:
                default_content = "<p>No highlights</p>"
            footer = (
                        '<p>The <a href="http://www.mobileread.com/forums/showthread.php?t=205062" target="_blank">' +
                        'Annotations plugin</a> imports highlights and annotations from Marvin.</p>'
                     )

        elif action == 'show_vocabulary':
            header = None
            group_box_title = 'Vocabulary words'
            if self.installed_books[book_id].vocabulary:
                word_list = '<br/>'.join(sorted(self.installed_books[book_id].vocabulary, key=sort_key))
                default_content = "<p>{0}</p>".format(word_list)
            else:
                default_content = ("<p>No vocabulary words</p>")
            footer = None

        else:
            header = None
            group_box_title = action
            default_content = "Default content"
            footer = None

        content = {
                    'default_content': default_content,
                    'footer': footer,
                    'header': header,
                    'group_box_title': group_box_title,
                    'title': title
                  }

        klass = os.path.join(dialog_resources_path, 'html_viewer.py')
        if os.path.exists(klass):
            #self._log("importing metadata dialog from '%s'" % klass)
            sys.path.insert(0, dialog_resources_path)
            this_dc = importlib.import_module('html_viewer')
            sys.path.remove(dialog_resources_path)
            dlg = this_dc.HTMLViewerDialog(self, 'html_viewer')
            dlg.initialize(self,
                           content,
                           book_id,
                           self.installed_books[book_id],
                           self.parent.connected_device.local_db_path)
            dlg.exec_()

        else:
            self._log("ERROR: Can't import from '%s'" % klass)

    def show_help(self):
        '''
        Display help file
        '''
        self.parent.show_help()

    def show_manage_collections_dialog(self):
        '''
        Present all active collection names, allow edit/deletion
        Marvin changes applied immediately to mainDb.
        Returns a dict of original, changed so we can update custom column assignments,
        connected device
        '''
        self._log_location()

        # Build an inventory of cids with collection assignments
        self.launch_collections_scanner()

        current_collections = {}

        # Get all Marvin collection names
        con = sqlite3.connect(self.parent.connected_device.local_db_path)
        with con:
            con.row_factory = sqlite3.Row

            collections_cur = con.cursor()
            collections_cur.execute('''SELECT
                                        Name
                                       FROM Collections
                                    ''')
            rows = collections_cur.fetchall()
            collections_cur.close()
        marvin_collection_list = []
        if len(rows):
            marvin_collection_list = [row[b'Name'] for row in rows]
            marvin_collection_list = sorted(marvin_collection_list, key=sort_key)
            current_collections['Marvin'] = marvin_collection_list

        # Get all calibre collection names
        calibre_collection_list = []
        cfl = self.parent.prefs.get('collection_field_lookup', '')
        if cfl:
            db = self.opts.gui.current_db
            calibre_collection_list = db.all_custom(db.field_metadata.key_to_label(cfl))
            current_collections['calibre'] = sorted(calibre_collection_list, key=sort_key)

        if current_collections:
            if True:
                klass = os.path.join(dialog_resources_path, 'manage_collections.py')
                if os.path.exists(klass):
                    sys.path.insert(0, dialog_resources_path)
                    this_dc = importlib.import_module('manage_collections')
                    sys.path.remove(dialog_resources_path)

#                     dlg.initialize(self,
#                                    current_collections,
#                                    self.library_inventory.collection_ids,
#                                    self.parent.connected_device)

                    dlg = this_dc.MyDeviceCategoryEditor(self, tag_to_match=None,
                                                         data=current_collections, key=sort_key,
                                                         connected_device=self.parent.connected_device)
                    dlg.exec_()
                    if dlg.result() == dlg.Accepted:
                        if self.library_inventory.isRunning():
                            self.library_inventory.wait()
                        self._log("original: %s" % current_collections)
                        self._log("to_rename: %s" % dlg.to_rename)
                        self._log("to_delete %s" % dlg.to_delete)
                        self._log("collection_ids: %s" % self.library_inventory.collection_ids)
                else:
                    self._log("ERROR: Can't import from '%s'" % klass)

            else:
                klass = os.path.join(dialog_resources_path, 'manage_collections.py')
                if os.path.exists(klass):
                    sys.path.insert(0, dialog_resources_path)
                    this_dc = importlib.import_module('manage_collections')
                    sys.path.remove(dialog_resources_path)
                    dlg = this_dc.CollectionsManagementDialog(self, 'collections_manager')

                    if self.library_inventory.isRunning():
                        self.library_inventory.wait()

                    dlg.initialize(self,
                                   current_collections,
                                   self.library_inventory.collection_ids,
                                   self.parent.connected_device)
                    dlg.exec_()
                else:
                    self._log("ERROR: Can't import from '%s'" % klass)
        else:
            title = "Collection management"
            msg = "<p>No collections to manage.</p>"
            MessageBox(MessageBox.INFO, title, msg,
                   show_copy_button=False).exec_()

    def show_view_collections_dialog(self, row):
        '''
        Present collection assignments to user, get updates
        Updated calibre assignments need to be sent to custom column.
        Device model and cached_books updated with updated collections + current flags.
        Updated Marvin assignments need to be sent to Marvin
        '''
        self._log_location(row)
        cid = self._selected_cid(row)
        book_id = self._selected_book_id(row)

        original_calibre_collections = self._get_calibre_collections(cid)
        original_marvin_collections = self._get_marvin_collections(book_id)

        if original_calibre_collections == [] and original_marvin_collections == []:
            title = self.installed_books[book_id].title
            msg = "<p>This book is not assigned to any collections.</p>"
            MessageBox(MessageBox.INFO, title, msg,
                       show_copy_button=False).exec_()
        else:
            klass = os.path.join(dialog_resources_path, 'view_collections.py')
            if os.path.exists(klass):
                #self._log("importing metadata dialog from '%s'" % klass)
                sys.path.insert(0, dialog_resources_path)
                this_dc = importlib.import_module('view_collections')
                sys.path.remove(dialog_resources_path)
                dlg = this_dc.CollectionsViewerDialog(self, 'collections_viewer')
                cid = self._selected_cid(row)
                dlg.initialize(self,
                               self.installed_books[book_id].title,
                               original_calibre_collections,
                               original_marvin_collections,
                               self.parent.connected_device)
                dlg.exec_()
                if dlg.result() == dlg.Accepted:
                    updated_calibre_collections = dlg.results['updated_calibre_collections']
                    updated_marvin_collections = dlg.results['updated_marvin_collections']

                    if (original_calibre_collections == updated_calibre_collections and
                        original_marvin_collections == updated_marvin_collections):
                        self._log("no collection changes detected")
                    else:
                        if updated_calibre_collections != original_calibre_collections:
                            self._log("original_calibre_collections: %s" % original_calibre_collections)
                            self._log("updated_calibre_collections: %s" % updated_calibre_collections)
                            self._update_calibre_collections(cid, updated_calibre_collections)

                        if updated_marvin_collections != original_marvin_collections:
                            self._log("original_marvin_collections: %s" % original_marvin_collections)
                            self._log("updated_marvin_collections: %s" % updated_marvin_collections)
                            self._update_marvin_collections(book_id, updated_marvin_collections)
                else:
                    self._log("User cancelled Collections dialog")
            else:
                self._log("ERROR: Can't import from '%s'" % klass)

    def show_view_metadata_dialog(self, row):
        '''
        '''
        self._log_location(row)
        cid = self._selected_cid(row)
        klass = os.path.join(dialog_resources_path, 'view_metadata.py')
        if os.path.exists(klass):
            #self._log("importing metadata dialog from '%s'" % klass)
            sys.path.insert(0, dialog_resources_path)
            this_dc = importlib.import_module('view_metadata')
            sys.path.remove(dialog_resources_path)
            dlg = this_dc.MetadataComparisonDialog(self, 'metadata_comparison')
            book_id = self._selected_book_id(row)
            cid = self._selected_cid(row)
            mismatches = self.installed_books[book_id].metadata_mismatches

            dlg.initialize(self,
                           book_id,
                           cid,
                           self.installed_books[book_id],
                           self.parent.connected_device.local_db_path)
            dlg.exec_()
            if dlg.result() == dlg.Accepted and mismatches:
                action = dlg.stored_command
                self._update_metadata(action)
            else:
                self._log("User cancelled Metadata dialog")

        else:
            self._log("ERROR: Can't import from '%s'" % klass)

    def size_hint(self):
        return QtCore.QSize(self.perfect_width, self.height())

    def start_library_inventory(self):
        self.library_inventory.start()

    def toggle_match_colors(self):
        self.show_match_colors = not self.show_match_colors
        self.opts.prefs.set('show_match_colors', self.show_match_colors)
        if self.show_match_colors:
            self.show_match_colors_button.setText("Hide Matches")
            self.tv.sortByColumn(self.LIBRARY_HEADER.index('Match Quality'), Qt.DescendingOrder)
            self.capture_sort_column(self.LIBRARY_HEADER.index('Match Quality'))
            self.show_match_colors_button.setIcon(QIcon(os.path.join(self.parent.opts.resources_path,
                                                       'icons',
                                                       'matches_hide.png')))
        else:
            self.show_match_colors_button.setText("Show Matches")
            self.show_match_colors_button.setIcon(QIcon(os.path.join(self.parent.opts.resources_path,
                                                       'icons',
                                                       'matches_show.png')))
        self.tv.setAlternatingRowColors(not self.show_match_colors)
        self.tm.refresh(self.show_match_colors)

    # Helpers
    def _apply_date_read(self):
        '''
        Fetch the LAST_OPENED date, convert to datetime, apply to custom field
        '''
        self._log_location()
        lookup = self.parent.prefs.get('date_read_field_lookup', None)
        if lookup:
            selected_books = self._selected_books()
            for row in selected_books:
                cid = selected_books[row]['cid']
                if cid is not None:
                    # Get the current value from the lookup field
                    db = self.opts.gui.current_db
                    mi = db.get_metadata(cid, index_is_id=True)
                    old_date = mi.get_user_metadata(lookup, False)['#value#']
                    #self._log("Updating old date_read value: %s" % repr(old_date))

                    # Build a new datetime object from Last Opened
                    new_date = selected_books[row]['last_opened']
                    if new_date:
                        um = mi.metadata_for_field(lookup)
                        ndo = datetime.strptime(new_date, "%Y-%m-%d")
                        um['#value#'] = ndo.replace(hour=12)
                        mi.set_user_metadata(lookup, um)
                        db.set_metadata(cid, mi, set_title=False, set_authors=False)
                        db.commit()
                    else:
                        self._log("'%s' has no Last Opened date" % selected_books[row]['title'])
        else:
            self._log("No date_read_field_lookup specified")

    def _calculate_word_count(self):
        '''
        Calculate word count for each selected book
        selected_books: {row: {'book_id':, 'cid':, 'path':, 'title':}...}
        '''
        def _extract_body_text(data):
            '''
            Get the body text of this html content with any html tags stripped
            '''
            RE_HTML_BODY = re.compile(u'<body[^>]*>(.*)</body>', re.UNICODE | re.DOTALL | re.IGNORECASE)
            RE_STRIP_MARKUP = re.compile(u'<[^>]+>', re.UNICODE)

            body = RE_HTML_BODY.findall(data)
            if body:
                return RE_STRIP_MARKUP.sub('', body[0]).replace('.','. ')
            return ''

        self._log_location()

        selected_books = self._selected_books()
        if selected_books:
            stats = {}

            pb = ProgressBar(parent=self.opts.gui, window_title="Calculating word count",
                             on_top=True)
            total_books = len(selected_books)
            pb.set_maximum(total_books)
            pb.set_value(0)
            pb.set_label('{:^100}'.format("1 of %d" % (total_books)))
            pb.show()

            close_requested = False
            for i, row in enumerate(selected_books):
                if pb.close_requested:
                    close_requested = True
                    break

                pb.set_label('{:^100}'.format(selected_books[row]['title']))

                # Copy the remote epub to local storage
                path = selected_books[row]['path']
                rbp = '/'.join(['/Documents', path])
                lbp = os.path.join(self.local_cache_folder, path)

                with open(lbp, 'wb') as out:
                    self.ios.copy_from_idevice(str(rbp), out)

                # Open the file
                iterator = EbookIterator(lbp)
                iterator.__enter__(only_input_plugin=True, run_char_count=True,
                                   read_anchor_map=False)
                book_files = []
                strip_html = True
                for path in iterator.spine:
                    with open(path, 'rb') as f:
                        html = f.read().decode('utf-8', 'replace')
                        if strip_html:
                            html = unicode(_extract_body_text(html)).strip()
                            #print('FOUND HTML:', html)
                    book_files.append(html)
                book_text = ''.join(book_files)

                wordcount = get_wordcount_obj(book_text)

                self._log("%s: %d words" % (selected_books[row]['title'], wordcount.words))
                stats[selected_books[row]['title']] = wordcount.words

                # Delete the local copy
                os.remove(lbp)
                pb.increment()

                # Update the model
                wc = locale.format("%d", wordcount.words, grouping=True)
                self.tm.arraydata[row][self.WORD_COUNT_COL] = "{0} ".format(wc)

                # Update the spreadsheet for those watching at home
                self.repaint()

                # Update self.installed_books
                book_id = selected_books[row]['book_id']
                self.installed_books[book_id].word_count = wc

                # Update Marvin db
                self._log("DON'T FORGET TO TELL MARVIN")


            pb.hide()

            if close_requested:
                self._log("user cancelled, partial results delivered")

            if False:
                # Display a summary
                title = "Word count results"
                msg = ("<p>Calculated word count for {0} books.</p>".format(total_books) +
                       "<p>Click <b>Show details</b> for a summary.</p>")
                dl = ["%s: %s" % (stat, locale.format("%d", stats[stat], grouping=True))
                       for stat in stats]
                details = '\n'.join(dl)
                MessageBox(MessageBox.INFO, title, msg, det_msg=details,
                               show_copy_button=False).exec_()
        else:
            self._log("No selected books")
            # Display a summary
            title = "Word count"
            msg = ("<p>Select one or more books to calculate word count.</p>")
            MessageBox(MessageBox.INFO, title, msg,
                           show_copy_button=False).exec_()

    def _clear_flags(self, action):
        '''
        Clear specified flags for selected books
        sort_key is the bitfield representing current flag settings
        '''
        def _build_flag_list(flagbits):
            flags = []
            if flagbits & self.NEW_FLAG:
                flags.append(self.FLAGS['new'])
            if flagbits & self.READING_FLAG:
                flags.append(self.FLAGS['reading_list'])
            if flagbits & self.READ_FLAG:
                flags.append(self.FLAGS['read'])
            return flags

        self._log_location(action)
        if action == 'clear_new_flag':
            mask = self.NEW_FLAG
        elif action == 'clear_reading_list_flag':
            mask = self.READING_FLAG
        elif action == 'clear_read_flag':
            mask = self.READ_FLAG
        elif action == 'clear_all_flags':
            mask = 0

        selected_books = self._selected_books()
        for row in selected_books:
            book_id = selected_books[row]['book_id']
            flagbits = self.tm.arraydata[row][self.FLAGS_COL].sort_key
            if mask == 0:
                flagbits = 0
                basename = "flags0.png"
                new_flags_widget = SortableImageWidgetItem(self,
                                                       os.path.join(self.parent.opts.resources_path,
                                                         'icons', basename),
                                                       flagbits, self.FLAGS_COL)
                # Update the model
                self.tm.arraydata[row][self.FLAGS_COL] = new_flags_widget
                # Update self.installed_books flags list
                self.installed_books[book_id].flags = 0
                flags = []

                # Update Marvin db
                self._log("*** DON'T FORGET TO TELL MARVIN ABOUT THE CLEARED FLAGS ***")

            elif flagbits & mask:
                # Clear the bit with XOR
                flagbits = flagbits ^ mask
                basename = "flags%d.png" % flagbits
                new_flags_widget = SortableImageWidgetItem(self,
                                                       os.path.join(self.parent.opts.resources_path,
                                                         'icons', basename),
                                                       flagbits, self.FLAGS_COL)
                # Update the model
                self.tm.arraydata[row][self.FLAGS_COL] = new_flags_widget

                # Update self.installed_books flags list

                self.installed_books[book_id].flags = _build_flag_list(flagbits)

                # Update Marvin db
                self._log("*** DON'T FORGET TO TELL MARVIN ABOUT THE UPDATED FLAGS ***")

            path = selected_books[row]['path']
            self._update_device_flags(book_id, path, _build_flag_list(flagbits))

        self.repaint()

    def _clear_selected_rows(self):
        '''
        Clear any active selections
        '''
        self._log_location()
        self.tv.clearSelection()

    def _compute_epub_hash(self, zipfile):
        '''
        Generate a hash of all text and css files in epub
        '''
        if self.opts.prefs.get('development_mode', False):
            self._log_location(os.path.basename(zipfile))

        # Find the OPF file in the zipped ePub, extract a list of text files
        try:
            zf = ZipFile(zipfile, 'r')
            container = etree.fromstring(zf.read('META-INF/container.xml'))
            opf_tree = etree.fromstring(zf.read(container.xpath('.//*[local-name()="rootfile"]')[0].get('full-path')))

            text_hrefs = []
            manifest = opf_tree.xpath('.//*[local-name()="manifest"]')[0]
            for item in manifest.iterchildren():
                #self._log(etree.tostring(item, pretty_print=True))
                mt = item.get('media-type')
                if item.get('media-type') in ['application/xhtml+xml', 'text/css']:
                    text_hrefs.append(item.get('href').split('/')[-1])
            zf.close()
        except:
            if self.opts.prefs.get('development_mode', False):
                import traceback
                self._log(traceback.format_exc())
            return None

        m = hashlib.md5()
        zfi = ZipFile(zipfile).infolist()
        for zi in zfi:
            if False and self.opts.prefs.get('development_mode', False):
                self._log("evaluating %s" % zi.filename)

            if zi.filename.split('/')[-1] in text_hrefs:
                m.update(zi.filename)
                m.update(str(zi.file_size))
                if False and self.opts.prefs.get('development_mode', False):
                    self._log("adding filename %s" % (zi.filename))
                    self._log("adding file_size %s" % (zi.file_size))

        return m.hexdigest()

    def _construct_table_data(self):
        '''
        Populate the table data from self.installed_books
        '''
        def _generate_author(book_data):
            '''
            '''
            if not book_data.author_sort:
                book_data.author_sort = ', '.join(book_data.author)
            author = SortableTableWidgetItem(
                ', '.join(book_data.author),
                book_data.author_sort.upper())
            return author

        def _generate_collection_match_profile(book_data):
            '''
            If no custom collections field assigned, always return 0
            '''
            if (book_data.calibre_collections is None and
                book_data.device_collections == []):
                base_name = 'collections_empty.png'
                sort_value = 0
            elif (book_data.calibre_collections is None and
                book_data.device_collections > []):
                base_name = 'collections_info.png'
                sort_value = 0
            elif (book_data.device_collections == [] and
                  book_data.calibre_collections == []):
                base_name = 'collections_empty.png'
                sort_value = 0
            elif book_data.device_collections == book_data.calibre_collections:
                base_name = 'collections_equal.png'
                sort_value = 2
            else:
                base_name = 'collections_unequal.png'
                sort_value = 1
            collection_match = SortableImageWidgetItem(self,
                                                       os.path.join(self.parent.opts.resources_path,
                                                                    'icons', base_name),
                                                       sort_value, self.COLLECTIONS_COL)
            return collection_match

        def _generate_flags_profile(book_data):
            '''
            Figure out which flags image to use, assign sort value
            NEW = 4
            READING LIST = 2
            READ = 1
            '''
            flag_list = book_data.flags
            flagbits = 0
            if 'NEW' in flag_list:
                flagbits += 4
            if 'READING LIST' in flag_list:
                flagbits += 2
            if 'READ' in flag_list:
                flagbits += 1
            base_name = "flags%d.png" % flagbits
            flags = SortableImageWidgetItem(self,
                                            os.path.join(self.parent.opts.resources_path,
                                                         'icons', base_name),
                                            flagbits, self.FLAGS_COL)
            return flags

        def _generate_last_opened(book_data):
            '''
            last_opened sorts by timestamp
            '''
            last_opened_ts = ''
            last_opened_sort = 0
            if book_data.date_opened:
                last_opened_ts = time.strftime("%Y-%m-%d",
                                               time.localtime(book_data.date_opened))
                last_opened_sort = book_data.date_opened
            last_opened = SortableTableWidgetItem(
                last_opened_ts,
                last_opened_sort)
            return last_opened

        def _generate_match_quality(book_data):
            '''
            4: Marvin uuid matches calibre uuid (hard match): Green
            3: Marvin hash matches calibre hash (soft match): Yellow
            2: Marvin hash duplicates: Orange
            1: Calibre hash duplicates: Red
            0: Marvin only, single copy
            '''

            if self.opts.prefs.get('development_mode', False):
                self._log("%s uuid: %s matches: %s on_device: %s hash: %s" %
                            (book_data.title,
                             repr(book_data.uuid),
                             repr(book_data.matches),
                             repr(book_data.on_device),
                             repr(book_data.hash)))
                self._log("metadata_mismatches: %s" % repr(book_data.metadata_mismatches))
            match_quality = 0

            if (book_data.uuid > '' and
                [book_data.uuid] == book_data.matches and
                not book_data.metadata_mismatches):
                # GREEN: Hard match - uuid match, metadata match
                match_quality = 4

            elif ((book_data.on_device == 'Main' and
                   book_data.metadata_mismatches) or
                  ([book_data.uuid] == book_data.matches)):
                # YELLOW: Soft match - hash match,
                match_quality = 3

            elif (book_data.uuid in book_data.matches):
                # ORANGE: Duplicate of calibre copy
                match_quality = 2

            elif (book_data.hash in self.marvin_hash_map and
                  len(self.marvin_hash_map[book_data.hash]) > 1):
                # RED: Marvin-only duplicate
                match_quality = 1

            if self.opts.prefs.get('development_mode', False):
                self._log("%s match_quality: %s" % (book_data.title, match_quality))
            return match_quality

        def _generate_reading_progress(book_data):
            '''

            '''

            percent_read = ''
            if self.opts.prefs.get('show_progress_as_percentage', False):
                if book_data.progress < 0.01:
                    percent_read = ''
                else:
                    # Pad the right side for visual comfort, since this col is
                    # right-aligned
                    percent_read = "{:3.0f}%   ".format(book_data.progress * 100)
                progress = SortableTableWidgetItem(percent_read, book_data.progress)
            else:
                #base_name = "progress000.png"
                base_name = "progress_none.png"
                if book_data.progress >= 0.01 and book_data.progress < 0.11:
                    base_name = "progress010.png"
                elif book_data.progress >= 0.11 and book_data.progress < 0.22:
                    base_name = "progress020.png"
                elif book_data.progress >= 0.22 and book_data.progress < 0.33:
                    base_name = "progress030.png"
                elif book_data.progress >= 0.33 and book_data.progress < 0.44:
                    base_name = "progress040.png"
                elif book_data.progress >= 0.44 and book_data.progress < 0.55:
                    base_name = "progress050.png"
                elif book_data.progress >= 0.55 and book_data.progress < 0.66:
                    base_name = "progress060.png"
                elif book_data.progress >= 0.66 and book_data.progress < 0.77:
                    base_name = "progress070.png"
                elif book_data.progress >= 0.77 and book_data.progress < 0.88:
                    base_name = "progress080.png"
                elif book_data.progress >= 0.88 and book_data.progress < 0.95:
                    base_name = "progress090.png"
                elif book_data.progress >= 0.95:
                    base_name = "progress100.png"

                progress = SortableImageWidgetItem(self,
                                            os.path.join(self.parent.opts.resources_path,
                                                         'icons', base_name),
                                            book_data.progress,
                                            self.PROGRESS_COL)
            return progress

        def _generate_title(book_data):
            '''
            '''
            # Title, Author sort by title_sort, author_sort
            if not book_data.title_sort:
                book_data.title_sort = book_data.title_sort()
            title = SortableTableWidgetItem(
                book_data.title,
                book_data.title_sort.upper())
            return title

        tabledata = []

        for book in self.installed_books:
            book_data = self.installed_books[book]
            author = _generate_author(book_data)
            collection_match = _generate_collection_match_profile(book_data)
            flags = _generate_flags_profile(book_data)
            last_opened = _generate_last_opened(book_data)
            match_quality = _generate_match_quality(book_data)
            progress = _generate_reading_progress(book_data)
            title = _generate_title(book_data)

            article_count = 0
            if 'Wiki' in book_data.articles:
                article_count += len(book_data.articles['Wiki'])
            if 'Pinned' in book_data.articles:
                article_count += len(book_data.articles['Pinned'])

            # List order matches self.LIBRARY_HEADER
            this_book = [
                book_data.uuid,
                book_data.cid,
                book_data.mid,
                book_data.path,
                title,
                author,
                "{0} ".format(book_data.word_count) if book_data.word_count > '0' else '',
                progress,
                last_opened,
                collection_match,
                flags,
                len(book_data.highlights) if len(book_data.highlights) else '',
                article_count if article_count else '',
                self.CHECKMARK if book_data.deep_view_prepared else '',
                len(book_data.vocabulary) if len(book_data.vocabulary) else '',
                match_quality
                ]
            tabledata.append(this_book)
        return tabledata

    def _construct_table_view(self):
        '''
        '''
        #self.tv = QTableView(self)
        self._log_location()
        self.l.addWidget(self.tv)
        self.tm = MarkupTableModel(self, centered_columns=self.CENTERED_COLUMNS,
                                   right_aligned_columns=self.RIGHT_ALIGNED_COLUMNS)

        self.tv.setModel(self.tm)
        self.tv.setShowGrid(False)
        if self.parent.prefs.get('use_monospace_font', False):
            # Set row height
            nrows = len(self.tabledata)
            for row in xrange(nrows):
                self.tv.setRowHeight(row, 16)

            if isosx:
                FONT = QFont('Monaco', 11)
            elif iswindows:
                FONT = QFont('Lucida Console', 9)
            elif islinux:
                FONT = QFont('Monospace', 9)
                FONT.setStyleHint(QFont.TypeWriter)
            self.tv.setFont(FONT)
        else:
            # Set row height
            nrows = len(self.tabledata)
            for row in xrange(nrows):
                self.tv.setRowHeight(row, 18)

        self.tvSelectionModel = self.tv.selectionModel()
        self.tv.setAlternatingRowColors(not self.show_match_colors)
        self.tv.setShowGrid(False)
        self.tv.setWordWrap(False)
        self.tv.setSelectionBehavior(self.tv.SelectRows)

        # Hide the vertical self.header
        self.tv.verticalHeader().setVisible(False)

        # Hide hidden columns
        for index in self.HIDDEN_COLUMNS:
            self.tv.hideColumn(index)

        # Set horizontal self.header props
        self.tv.horizontalHeader().setStretchLastSection(True)

        # Set column width to fit contents
        self.tv.resizeColumnsToContents()

        # Restore saved widths if available
        saved_column_widths = self.opts.prefs.get('marvin_library_column_widths', False)
        if saved_column_widths:
            for i, width in enumerate(saved_column_widths):
                self.tv.setColumnWidth(i, width)

        self.tv.setSortingEnabled(True)

        sort_column = self.opts.prefs.get('marvin_library_sort_column',
                                          self.LIBRARY_HEADER.index('Match Quality'))
        sort_order = self.opts.prefs.get('marvin_library_sort_order',
                                         Qt.DescendingOrder)
        self.tv.sortByColumn(sort_column, sort_order)

    def _delete_books(self):
        '''
        '''
        self._log_location()

        btd = self._selected_books()
        books_to_delete = sorted([btd[b]['title'] for b in btd], key=sort_key)

        if books_to_delete:
            if True:
                ''' Under the skirts approach '''
                title = "Delete %s" % ("%d books?" % len(books_to_delete)
                                        if len(books_to_delete) > 1 else "1 book?")
                msg = ("<p>Click <b>Show details</b> for a list of books that will be deleted " +
                       "from your Marvin library.</p>" +
                       '<p><b><font style="color:#FF0000; ">{0}</font></b></p>'.format(title))
                det_msg = '\n'.join(books_to_delete)
                d = MessageBox(MessageBox.QUESTION, title, msg, det_msg=det_msg,
                               show_copy_button=False)
                if d.exec_():
                    model = self.parent.gui.memory_view.model()
                    paths_to_delete = [btd[b]['path'] for b in btd]
                    self._log("paths_to_delete: %s" % paths_to_delete)
                    sorted_map = model.sorted_map
                    delete_map = {}
                    for item in sorted_map:
                        book = model.db[item]
                        if book.path in paths_to_delete:
                            delete_map[book.path] = item
                            continue

                    # Delete the rows in MM spreadsheet
                    rows_to_delete = self._selected_rows()
                    for row in sorted(rows_to_delete, reverse=True):
                        self.tm.beginRemoveRows(QModelIndex(), row, row)
                        del self.tm.arraydata[row]
                        self.tm.endRemoveRows()

                    # Delete the books on Device
                    job = self.parent.gui.remove_paths(delete_map.keys())

                    # Delete books in the Device model
                    model.mark_for_deletion(job, delete_map.values(), rows_are_ids=True)
                    model.deletion_done(job, succeeded=True)
                    for rtd in delete_map.values():
                        del model.db[rtd]

                    # Put on a show while waiting for the delete job to finish
                    QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
                    blocking_busy = MyBlockingBusy(self.opts.gui, "Updating Marvin Library…", size=60)
                    blocking_busy.start()
                    blocking_busy.show()
                    while not job.is_finished:
                        Application.processEvents()
                    blocking_busy.stop()
                    blocking_busy.accept()
                    QApplication.restoreOverrideCursor()

                    # Remove from cached_paths in driver
                    if True:
                        for ptd in paths_to_delete:
                            self.parent.connected_device.cached_books.pop(ptd)
                    else:
                        # The book is not in booklists, how/when removed?
                        self.parent.connected_device.remove_books_from_metadata(paths_to_delete,
                            self.parent.gui.booklists())

                    # Update the visible Device model
                    model.paths_deleted(paths_to_delete)
                else:
                    self._log("delete cancelled")

            if False:
                ''' Reconnect approach '''
                title = "Delete %s" % ("%d books?" % len(books_to_delete)
                                                      if len(books_to_delete) > 1 else "1 book?")
                msg = ("<p>Click <b>Show details</b> for a list of books that will be deleted " +
                       "from your Marvin library.</p>" +
                       "<p>After clicking <b>Yes</b>, the Marvin Library window will disappear " +
                       "briefly while Marvin's Library is being updated.</p>" +
                       '<p><b><font style="color:#FF0000; ">{0}</font></b></p>'.format(title))
                det_msg = '\n'.join(books_to_delete)
                d = MessageBox(MessageBox.QUESTION, title, msg, det_msg=det_msg,
                               show_copy_button=False)
                if d.exec_():
                    QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

                    # Build the command file
                    command_name = 'delete_books'
                    command_element = 'deletebooks'
                    command_soup = BeautifulStoneSoup(self.COMMAND_XML.format(
                                                      command_element,
                                                      time.mktime(time.localtime())))
                    books_to_delete = self._selected_books()
                    for i, book_id in enumerate(books_to_delete):
                        book_tag = Tag(command_soup, 'book')
                        book_tag['author'] = books_to_delete[book_id]['author']
                        book_tag['title'] = books_to_delete[book_id]['title']
                        book_tag['uuid'] = books_to_delete[book_id]['uuid']
                        book_tag['filename'] = books_to_delete[book_id]['path']
                        command_soup.manifest.insert(i, book_tag)

                    if self.prefs.get('execute_marvin_commands', True):
                        # Call the Marvin driver to copy the command file to the staging folder
                        self._log("staging command file")
                        self._stage_command_file(command_name, command_soup,
                            show_command=self.prefs.get('development_mode', False))

                        # Wait for completion
                        self._log("waiting for completion")
                        self._wait_for_command_completion(command_name)

                    else:
                        self._log("{:*^80}".format(" command execution disabled in JSON file "))
                        if command_name == 'update_metadata':
                            soup = BeautifulStoneSoup(command_soup.renderContents())
                            # <descriptions>
                            descriptions = soup.findAll('description')
                            for description in descriptions:
                                d_tag = Tag(soup, 'description')
                                d_tag.insert(0, "(description removed for debug stream)")
                                description.replaceWith(d_tag)
                            # <covers>
                            covers = soup.findAll('cover')
                            for cover in covers:
                                cover_tag = Tag(soup, 'cover')
                                cover_tag.insert(0, "(cover removed for debug stream)")
                                cover.replaceWith(cover_tag)
                            self._log(soup.prettify())
                        else:
                            self._log("command_name: %s" % command_name)
                            self._log(command_soup.prettify())

                    # Set the reconnect_request flag in the driver
                    self.reconnect_request_pending = True
                    self.parent.connected_device.set_reconnect_request(True)

                    # Delete the rows in the visible model to reassure the user
                    rows_to_delete = self._selected_rows()
                    for row in sorted(rows_to_delete, reverse=True):
                        self.tm.beginRemoveRows(QModelIndex(), row, row)
                        del self.tm.arraydata[row]
                        self.tm.endRemoveRows()
                else:
                    self._log("delete cancelled")
        else:
            self._log("no books selected")
            title = "No selected books"
            msg = "<p>Select one or more books to delete.</p>"
            MessageBox(MessageBox.INFO, title, msg,
                   show_copy_button=False).exec_()

    def _fetch_marvin_content_hash(self, path):
        '''
        Given a Marvin path, compute/fetch a hash of its contents (excluding OPF)
        '''
        if self.opts.prefs.get('development_mode', False):
            self._log_location(path)

        # Try getting the hash from the cache
        try:
            zfr = ZipFile(self.local_hash_cache)
            hash = zfr.read(path)
        except:
            if self.opts.prefs.get('development_mode', False):
                self._log("opening local hash cache for appending")
            zfw = ZipFile(self.local_hash_cache, mode='a')
        else:
            if self.opts.prefs.get('development_mode', False):
                self._log("returning hash from cache: %s" % hash)
            zfr.close()
            return hash

        # Get a local copy, generate hash
        rbp = '/'.join(['/Documents', path])
        lbp = os.path.join(self.local_cache_folder, path)

        with open(lbp, 'wb') as out:
            self.ios.copy_from_idevice(str(rbp), out)

        hash = self._compute_epub_hash(lbp)
        zfw.writestr(path, hash)
        zfw.close()

        # Delete the local copy
        os.remove(lbp)
        return hash

    def _find_fuzzy_matches(self, library_scanner, installed_books):
        '''
        Compare computed hashes of installed books to library books.
        Look for potential dupes.
        Add .matches property to installed_books, a list of all Marvin uuids matching
        our hash
        '''
        self._log_location()

        library_hash_map = library_scanner.hash_map
        hard_matches = {}
        soft_matches = []
        for book in installed_books:
            #self._log("evaluating %s hash: %s uuid: %s" % (mb.title, mb.hash, mb.uuid))
            mb = installed_books[book]
            uuids = []
            if mb.hash in library_hash_map:
                if mb.uuid in library_hash_map[mb.hash]:
                    #self._log("%s matches hash + uuid" % mb.title)
                    hard_matches[mb.hash] = mb
                    uuids = library_hash_map[mb.hash]
                else:
                    #self._log("%s matches hash, but not uuid" % mb.title)
                    soft_matches.append(mb)
                    uuids = [mb.uuid]
            mb.matches = uuids

        # Review the soft matches against the hard matches
        if soft_matches:
            # Scan soft matches against hard matches for hash collision
            for mb in soft_matches:
                if mb.hash in hard_matches:
                    mb.matches += hard_matches[mb.hash].matches

    def _generate_booklist(self):
        '''
        '''
        self._log_location()

        # Scan library books for hashes
        if self.library_scanner.isRunning():
            self.library_scanner.wait()

        # Save a reference to the title, uuid map
        self.library_title_map = self.library_scanner.title_map
        self.library_uuid_map = self.library_scanner.uuid_map

        # Get the library hash_map
        library_hash_map = self.library_scanner.hash_map
        if library_hash_map is None:
            library_hash_map = self._scan_library_books(self.library_scanner)
        else:
            self._log("hash_map already generated")

        # Scan Marvin
        installed_books = self._get_installed_books()

        # Generate a map of Marvin hashes to book_ids
        self.marvin_hash_map = self._generate_marvin_hash_map(installed_books)

        # Update installed_books with library matches
        self._find_fuzzy_matches(self.library_scanner, installed_books)

        return installed_books

    def _generate_deep_view(self):
        '''
        '''
        self._log_location()
        title = "Generate Deep View"
        msg = ("<p>Not implemented</p>")
        MessageBox(MessageBox.INFO, title, msg,
                       show_copy_button=False).exec_()

    def _generate_marvin_hash_map(self, installed_books):
        '''
        Generate a map of book_ids to hash values
        {hash: [book_id, book_id,...], ...}
        '''
        self._log_location()
        hash_map = {}
        for book_id in installed_books:
            hash = installed_books[book_id].hash
            title = installed_books[book_id].title
#             self._log("%s: %s" % (title, hash))
            if hash in hash_map:
                hash_map[hash].append(book_id)
            else:
                hash_map[hash] = [book_id]

#         for hash in hash_map:
#             self._log("%s: %s" % (hash, hash_map[hash]))

        return hash_map

    def _get_calibre_collections(self, cid):
        '''
        Return a sorted list of current calibre collection assignments or
        None if no collection_field_lookup assigned or book does not exist in library
        '''
        cfl = self.prefs.get('collection_field_lookup', '')
        if cfl == '' or cid is None:
            return None
        else:
            lib_collections = []
            db = self.opts.gui.current_db
            mi = db.get_metadata(cid, index_is_id=True)
            lib_collections = mi.get(cfl)
            if lib_collections:
                if type(lib_collections) is not list:
                    lib_collections = [lib_collections]
            return sorted(lib_collections, key=sort_key)

    def _get_marvin_collections(self, book_id):
        return sorted(self.installed_books[book_id].device_collections, key=sort_key)

    def _get_installed_books(self):
        '''
        Build a profile of all installed books for display
        On Device
        Title
        Author
        Last read
        Bookmarks
        Highlights/annotations
        Deep View content
        Vocabulary
        Percent read
        Flags
        Collections
        Word count
        hard match: uuid - green
        soft match: author/title or md5 contents/size match excluding OPF - yellow
        PinnedArticles + Wiki articles

        {mid: Book, ...}
        '''
        def _get_articles(cur, book_id):
            '''
            Return True if PinnedArticles or Wiki entries exist for book_id
            '''
            articles = {}

            # Get PinnedArticles
            a_cur = con.cursor()
            a_cur.execute('''SELECT
                              BookID,
                              Title,
                              URL
                             FROM PinnedArticles
                             WHERE BookID = '{0}'
                          '''.format(book_id))
            pinned_article_rows = a_cur.fetchall()

            if len(pinned_article_rows):
                pinned_articles = {}
                for row in pinned_article_rows:
                    pinned_articles[row[b'Title']] = row[b'URL']
                articles['Pinned'] = pinned_articles

            # Get Wiki snippets
            a_cur.execute('''SELECT
                              BookID,
                              Title,
                              Snippet
                             FROM Wiki
                             WHERE BookID = '{0}'
                          '''.format(book_id))
            wiki_rows = a_cur.fetchall()

            if len(wiki_rows):
                wiki_snippets = {}
                for row in wiki_rows:
                    wiki_snippets[row[b'Title']] = row[b'Snippet']
                articles['Wiki'] = wiki_snippets

            return articles

        def _get_calibre_id(uuid, title, author):
            '''
            Find book in library, return cid, mi
            '''
            if self.opts.prefs.get('development_mode', False):
                self._log_location("%s %s" % (repr(title), repr(author)))
            cid = None
            mi = None
            db = self.opts.gui.current_db
            if uuid in self.library_uuid_map:
                cid = self.library_uuid_map[uuid]['id']
                mi = db.get_metadata(cid, index_is_id=True, get_cover=True, cover_as_data=True)
                if self.opts.prefs.get('development_mode', False):
                    self._log("UUID match")
            elif title in self.library_title_map:
                _cid = self.library_title_map[title]['id']
                _mi = db.get_metadata(_cid, index_is_id=True, get_cover=True, cover_as_data=True)
                authors = author.split(', ')
                if authors == _mi.authors:
                    cid = _cid
                    mi = _mi
                    if self.opts.prefs.get('development_mode', False):
                        self._log("TITLE/AUTHOR match")
            return cid, mi

        def _get_collections(cur, book_id):
            # Get the collection assignments
            ca_cur = con.cursor()
            ca_cur.execute('''SELECT
                                BookID,
                                CollectionID
                              FROM BookCollections
                              WHERE BookID = '{0}'
                           '''.format(book_id))
            collections = []
            collection_rows = ca_cur.fetchall()
            if collection_rows is not None:
                collection_assignments = [collection[b'CollectionID']
                                          for collection in collection_rows]
                collections += [collection_map[item] for item in collection_assignments]
                collections = sorted(collections, key=sort_key)
            ca_cur.close()
            return collections

        def _get_flags(cur, row):
            # Get the flag assignments
            flags = []
            if row[b'NewFlag']:
                flags.append(self.FLAGS['new'])
            if row[b'ReadingList']:
                flags.append(self.FLAGS['reading_list'])
            if row[b'IsRead']:
                flags.append(self.FLAGS['read'])
            return flags

        def _get_highlights(cur, book_id):
            '''
            Return highlight text/notes associated with book_id
            '''
            hl_cur = con.cursor()
            hl_cur.execute('''SELECT
                                Note,
                                Text
                              FROM Highlights
                              WHERE BookID = '{0}'
                           '''.format(book_id))
            hl_rows = hl_cur.fetchall()
            highlight_list = []
            if len(hl_rows):
                for row in hl_rows:
                    raw_text = row[b'Text']
                    text = "<p>{0}".format(raw_text)
                    if row[b'Note']:
                        raw_note = row[b'Note']
                        text += "<br/>&nbsp;<em>{0}</em></p>".format(raw_note)
                    else:
                        text += "</p>"
                    highlight_list.append(text)
            hl_cur.close()
            return highlight_list

        def _get_marvin_genres(book_id):
            # Return sorted genre(s) for this book
            genre_cur = con.cursor()
            genre_cur.execute('''SELECT
                                    Subject
                                 FROM BookSubjects
                                 WHERE BookID = '{0}'
                              '''.format(book_id))
            genres = []
            genre_rows = genre_cur.fetchall()
            if genre_rows is not None:
                genres = [genre[b'Subject'] for genre in genre_rows]
            genre_cur.close()
            genres = sorted(genres, key=sort_key)
            return genres

        def _get_metadata_mismatches(cur, book_id, row, mi, this_book):
            '''
            Return dict of metadata mismatches.
            author, author_sort, pubdate, publisher, series, series_index, title,
            title_sort, description, subjects, collections, cover
            '''
            def _get_cover_hash(mi, this_book):
                '''
                Retrieve cover_hash from archive, or create/store
                '''
                ach = self.archived_cover_hashes.get(str(this_book.cid), {})
                cover_last_modified = self.opts.gui.current_db.cover_last_modified(this_book.cid, index_is_id=True)
                if ('cover_last_modified' in ach and
                    ach['cover_last_modified'] == cover_last_modified):
                    return ach['cover_hash']

                # Generate calibre cover hash (same process used by driver when sending books)
                cover_hash = 0
                desired_thumbnail_height = self.parent.connected_device.THUMBNAIL_HEIGHT
                try:
                    sized_thumb = thumbnail(mi.cover_data[1],
                                            desired_thumbnail_height,
                                            desired_thumbnail_height)
                    cover_hash = hashlib.md5(sized_thumb[2]).hexdigest()
                    cover_last_modified = self.opts.gui.current_db.cover_last_modified(this_book.cid, index_is_id=True)
                    self.archived_cover_hashes.set(str(this_book.cid),
                        {'cover_hash': cover_hash, 'cover_last_modified': cover_last_modified})
                except:
                    self._log("error calculating cover_hash for cid %d (%s)" % (this_book.cid, this_book.title))
                return cover_hash

            #self._log_location(row[b'Title'])
            mismatches = {}
            if mi is not None:
                # ~~~~~~~~ authors ~~~~~~~~
                if mi.authors != this_book.authors:
                    mismatches['authors'] = {'calibre': mi.authors,
                                             'Marvin': this_book.authors}

                # ~~~~~~~~ author_sort ~~~~~~~~
                if mi.author_sort != row[b'AuthorSort']:
                    mismatches['author_sort'] = {'calibre': mi.author_sort,
                                                 'Marvin': row[b'AuthorSort']}

                # ~~~~~~~~ cover_hash ~~~~~~~~
                cover_hash = _get_cover_hash(mi, this_book)
                if cover_hash != row[b'CalibreCoverHash']:
                    mismatches['cover_hash'] = {'calibre':cover_hash,
                                                'Marvin': row[b'CalibreCoverHash']}

                # ~~~~~~~~ pubdate ~~~~~~~~
                if bool(row[b'DatePublished']) or bool(mi.pubdate):
                    try:
                        mb_pubdate = datetime.utcfromtimestamp(int(row[b'DatePublished']))
                        mb_pubdate = mb_pubdate.replace(hour=0, minute=0, second=0)
                    except:
                        mb_pubdate = None
                    naive = mi.pubdate.replace(hour=0, minute=0, second=0, tzinfo=None)

                    if naive and mb_pubdate:
                        td = naive - mb_pubdate
                        if abs(td.days) > 1:
                            mismatches['pubdate'] = {'calibre': naive,
                                                     'Marvin': mb_pubdate}
                    elif naive != mb_pubdate:
                        # One of them is None
                        mismatches['pubdate'] = {'calibre': naive,
                                                 'Marvin': mb_pubdate}

                # ~~~~~~~~ publisher ~~~~~~~~
                if mi.publisher != row[b'Publisher']:
                    mismatches['publisher'] = {'calibre': mi.publisher,
                                               'Marvin': row[b'Publisher']}

                # ~~~~~~~~ series, series_index ~~~~~~~~
                if bool(mi.series) or bool(row[b'CalibreSeries']):
                    if mi.series != row[b'CalibreSeries']:
                        mismatches['series'] = {'calibre': mi.series,
                                                'Marvin': row[b'CalibreSeries']}

                if bool(mi.series_index) or bool(float(row[b'CalibreSeriesIndex'])):
                    if mi.series_index != float(row[b'CalibreSeriesIndex']):
                        mismatches['series_index'] = {'calibre': mi.series_index,
                                                      'Marvin': row[b'CalibreSeriesIndex']}

                # ~~~~~~~~ title ~~~~~~~~
                if mi.title != row[b'Title']:
                    mismatches['title'] = {'calibre': mi.title,
                                           'Marvin': row[b'Title']}

                # ~~~~~~~~ title_sort ~~~~~~~~
                if mi.title_sort != row[b'CalibreTitleSort']:
                    mismatches['title_sort'] = {'calibre': mi.title_sort,
                                                'Marvin': row[b'CalibreTitleSort']}

                # ~~~~~~~~ comments ~~~~~~~~
                if bool(mi.comments) or bool(row[b'Description']):
                    if mi.comments != row[b'Description']:
                        mismatches['comments'] = {'calibre': mi.comments,
                                                  'Marvin': row[b'Description']}

                # ~~~~~~~~ tags ~~~~~~~~
                if sorted(mi.tags, key=sort_key) != _get_marvin_genres(book_id):
                    mismatches['tags'] = {'calibre': sorted(mi.tags, key=sort_key),
                                          'Marvin': _get_marvin_genres(book_id)}

                # ~~~~~~~~ uuid ~~~~~~~~
                if mi.uuid != row[b'UUID']:
                    mismatches['uuid'] = {'calibre': mi.uuid,
                                          'Marvin': row[b'UUID']}


            else:
                self._log("(no calibre metadata for %s)" % row[b'Title'])

            return mismatches

        def _get_on_device_status(cid):
            '''
            Given a uuid, return the on_device status of the book
            '''
            if self.opts.prefs.get('development_mode', False):
                self._log_location()

            ans = None
            if cid:
                db = self.opts.gui.current_db
                mi = db.get_metadata(cid, index_is_id=True)
                ans = mi.ondevice_col
            return ans

        def _get_pubdate(row):
            try:
                pubdate = datetime.utcfromtimestamp(int(row[b'DatePublished']))
            except:
                pubdate = None
            return pubdate

        def _get_vocabulary_list(cur, book_id):
            # Get the vocabulary content
            voc_cur = con.cursor()
            voc_cur.execute('''SELECT
                                BookID,
                                Word
                              FROM Vocabulary
                              WHERE BookID = '{0}'
                           '''.format(book_id))

            vocabulary_rows = voc_cur.fetchall()
            vocabulary_list = []
            if len(vocabulary_rows):
                vocabulary_list = [vocabulary_item[b'Word']
                                   for vocabulary_item in vocabulary_rows]
                vocabulary_list = sorted(vocabulary_list, key=sort_key)
            voc_cur.close()
            return vocabulary_list

        def _purge_cover_hash_orphans():
            '''
            Purge obsolete cover hashes
            '''
            self._log_location()
            # Get active cids
            active_cids = sorted([str(installed_books[book_id].cid) for book_id in installed_books])
            #self._log("active_cids: %s" % active_cids)

            # Get active cover_hash cids
            cover_hash_cids = sorted(self.archived_cover_hashes.keys())
            #self._log("cover_hash keys: %s" % cover_hash_cids)

            for ch_cid in cover_hash_cids:
                if ch_cid not in active_cids:
                    self._log("removing orphan cid %s from archived_cover_hashes" % ch_cid)
                    del self.archived_cover_hashes[ch_cid]

        self._log_location()

        if self.opts.prefs.get('development_mode', False):
            self._log("local_db_path: %s" % self.parent.connected_device.local_db_path)

        # Fetch/compute hashes
        cached_books = self.parent.connected_device.cached_books
        hashes = self._scan_marvin_books(cached_books)

        # Get the mainDb data
        installed_books = {}
        con = sqlite3.connect(self.parent.connected_device.local_db_path)
        with con:
            con.row_factory = sqlite3.Row

            # Build a collection map
            collections_cur = con.cursor()
            collections_cur.execute('''SELECT
                                        ID,
                                        Name
                                       FROM Collections
                                    ''')
            rows = collections_cur.fetchall()
            collection_map = {}
            for row in rows:
                collection_map[row[b'ID']] = row[b'Name']
            collections_cur.close()

            # Get the books
            cur = con.cursor()
            cur.execute('''SELECT
                            Author,
                            AuthorSort,
                            Books.ID as id_,
                            CalibreCoverHash,
                            CalibreSeries,
                            CalibreSeriesIndex,
                            CalibreTitleSort,
                            CoverFile,
                            DateOpened,
                            DatePublished,
                            DeepViewPrepared,
                            Description,
                            FileName,
                            IsRead,
                            NewFlag,
                            Progress,
                            Publisher,
                            ReadingList,
                            Title,
                            UUID,
                            WordCount
                          FROM Books
                        ''')

            rows = cur.fetchall()

            pb = ProgressBar(parent=self.opts.gui, window_title="Performing Marvin metadata magic", on_top=True)
            book_count = len(rows)
            pb.set_maximum(book_count)
            pb.set_value(0)
            pb.set_label('{:^100}'.format("1 of %d" % (book_count)))
            pb.show()

            for i, row in enumerate(rows):
                pb.set_label('{:^100}'.format("%d of %d" % (i+1, book_count)))

                cid, mi = _get_calibre_id(row[b'UUID'],
                                          row[b'Title'],
                                          row[b'Author'])

                book_id = row[b'id_']
                # Get the primary metadata from Books
                this_book = Book(row[b'Title'], row[b'Author'].split(', '))
                this_book.articles = _get_articles(cur, book_id)
                this_book.author_sort = row[b'AuthorSort']
                this_book.cid = cid
                this_book.calibre_collections = self._get_calibre_collections(this_book.cid)
                this_book.comments = row[b'Description']
                this_book.cover_file = row[b'CoverFile']
                this_book.device_collections = _get_collections(cur, book_id)
                this_book.date_opened = row[b'DateOpened']
                this_book.deep_view_prepared = row[b'DeepViewPrepared']
                this_book.flags = _get_flags(cur, row)
                this_book.hash = hashes[row[b'FileName']]['hash']
                this_book.highlights = _get_highlights(cur, book_id)
                this_book.metadata_mismatches = _get_metadata_mismatches(cur, book_id, row, mi, this_book)
                this_book.mid = book_id
                this_book.on_device = _get_on_device_status(this_book.cid)
                this_book.path = row[b'FileName']
                this_book.progress = row[b'Progress']
                this_book.pubdate = _get_pubdate(row)
                this_book.tags = _get_marvin_genres(book_id)
                this_book.title_sort = row[b'CalibreTitleSort']
                this_book.uuid = row[b'UUID']
                this_book.vocabulary = _get_vocabulary_list(cur, book_id)
                this_book.word_count = locale.format("%d", row[b'WordCount'], grouping=True)
                installed_books[book_id] = this_book

                pb.increment()

            pb.hide()

        # Remove orphan cover_hashes
        _purge_cover_hash_orphans()

        if self.opts.prefs.get('development_mode', False):
            self._log("%d cached books from Marvin:" % len(cached_books))
            for book in installed_books:
                self._log("%s word_count: %s" % (installed_books[book].title,
                                                 repr(installed_books[book].word_count)))
        return installed_books

    def _localize_hash_cache(self, cached_books):
        '''
        Check for existence of hash cache on iDevice. Confirm/create folder
        If existing cached, purge orphans
        '''
        self._log_location()

        # Existing hash cache?
        lhc = os.path.join(self.local_cache_folder, self.hash_cache)
        rhc = '/'.join([self.remote_cache_folder, self.hash_cache])

        cache_exists = (self.ios.exists(rhc) and
                        not self.opts.prefs.get('hash_caching_disabled'))
        if cache_exists:
            # Copy from existing remote cache to local cache
            self._log("copying remote hash cache")
            with open(lhc, 'wb') as out:
                self.ios.copy_from_idevice(str(rhc), out)
        else:
            # Confirm path to remote folder is valid store point
            folder_exists = self.ios.exists(self.remote_cache_folder)
            if not folder_exists:
                self._log("creating remote_cache_folder %s" % repr(self.remote_cache_folder))
                self.ios.mkdir(self.remote_cache_folder)
            else:
                self._log("remote_cache_folder exists")

            # Create a local cache
            self._log("creating new local hash cache: %s" % repr(lhc))
            zfw = ZipFile(lhc, mode='w')
            zfw.writestr('Marvin hash cache', '')
            zfw.close()

            # Clear the marvin_content_updated flag
            if self.parent.marvin_content_updated:
                self.parent.marvin_content_updated = False

        self.local_hash_cache = lhc
        self.remote_hash_cache = rhc

        # Purge cache orphans
        if cache_exists:
            self._purge_cached_orphans(cached_books)

    def _log(self, msg=None):
        '''
        Print msg to console
        '''
        if not self.verbose:
            return

        if msg:
            debug_print(" %s" % str(msg))
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
            arg1 = str(args[0])
        if len(args) > 1:
            arg2 = str(args[1])

        debug_print(self.LOCATION_TEMPLATE.format(cls=self.__class__.__name__,
            func=sys._getframe(1).f_code.co_name,
            arg1=arg1, arg2=arg2))

    def _purge_cached_orphans(self, cached_books):
        '''

        '''
        self._log_location()
        zfa = ZipFile(self.local_hash_cache, mode='a')
        zfi = zfa.infolist()
        for zi in zfi:
            if zi.filename == 'Marvin hash cache':
                continue
            if zi.filename not in cached_books:
                self._log("removing %s from hash cache" % repr(zi.filename))
                zfa.delete(zi.filename)
        zfa.close()

    def _save_column_widths(self):
        '''
        '''
        self._log_location()
        try:
            widths = []
            for (i, c) in enumerate(self.LIBRARY_HEADER):
                widths.append(self.tv.columnWidth(i))
            self.opts.prefs.set('marvin_library_column_widths', widths)
        except:
            pass

    def _scan_library_books(self, library_scanner):
        '''
        Generate hashes for library epubs
        '''
        # Scan library books for hashes
        if self.library_scanner.isRunning():
            self.library_scanner.wait()

        uuid_map = library_scanner.uuid_map
        self._log_location("%d epubs" % len(uuid_map))

        pb = ProgressBar(parent=self.opts.gui, window_title="Scanning library", on_top=True)
        total_books = len(uuid_map)
        pb.set_maximum(total_books)
        pb.set_value(0)
        pb.set_label('{:^100}'.format("1 of %d" % (total_books)))
        pb.show()

        db = self.opts.gui.current_db
        close_requested = False
        for i, uuid in enumerate(uuid_map):
            pb.set_label('{:^100}'.format("%d of %d" % (i+1, total_books)))

            path = db.format(uuid_map[uuid]['id'], 'epub', index_is_id=True,
                             as_path=True, preserve_filename=True)
            uuid_map[uuid]['hash'] = self._compute_epub_hash(path)
            os.remove(path)
            pb.increment()

            if pb.close_requested:
                close_requested = True
                break
        else:
            # Only build the hash map if we completed without a close request
            hash_map = library_scanner.build_hash_map()

        pb.hide()

        if close_requested:
            raise AbortRequestException("user cancelled library scan")

        return hash_map

    def _scan_marvin_books(self, cached_books):
        '''
        Create the initial dict of installed books with hash values
        '''
        self._log_location()

        # Fetch pre-existing hash cache from device
        self._localize_hash_cache(cached_books)

        # Set up the progress bar
        pb = ProgressBar(parent=self.opts.gui, window_title="Scanning Marvin", on_top=True)
        total_books = len(cached_books)
        pb.set_maximum(total_books)
        pb.set_value(0)
        pb.set_label('{:^100}'.format("1 of %d" % (total_books)))
        pb.show()

        close_requested = False
        installed_books = {}
        for i, path in enumerate(cached_books):
            this_book = {}
            pb.set_label('{:^100}'.format("%d of %d" % (i+1, total_books)))
            this_book['hash'] = self._fetch_marvin_content_hash(path)

            installed_books[path] = this_book
            pb.increment()

            if pb.close_requested:
                close_requested = True
                break
        else:
            # Push the local hash to the iDevice
            self._update_remote_hash_cache()

        pb.hide()

        if close_requested:
            raise AbortRequestException("user cancelled Marvin scan")

        return installed_books

    def _selected_book_id(self, row):
        '''
        Return selected Marvin book_id
        '''
        return self.tm.arraydata[row][self.BOOK_ID_COL]

    def _selected_books(self):
        '''
        Generate a dict of books selected in the dialog
        '''
        selected_books = {}

        for row in self._selected_rows():
            author = str(self.tm.arraydata[row][self.AUTHOR_COL].text())
            book_id = self.tm.arraydata[row][self.BOOK_ID_COL]
            cid = self.tm.arraydata[row][self.CALIBRE_ID_COL]
            has_annotations = bool(self.tm.arraydata[row][self.ANNOTATIONS_COL])
            has_articles = bool(self.tm.arraydata[row][self.ARTICLES_COL])
            has_dv_content = bool(self.tm.arraydata[row][self.DEEP_VIEW_COL])
            has_vocabulary = bool(self.tm.arraydata[row][self.VOCABULARY_COL])
            last_opened = str(self.tm.arraydata[row][self.LAST_OPENED_COL].text())
            path = self.tm.arraydata[row][self.PATH_COL]
            title = str(self.tm.arraydata[row][self.TITLE_COL].text())
            uuid = self.tm.arraydata[row][self.UUID_COL]
            selected_books[row] = {
                                   'author': author,
                                   'book_id': book_id,
                                   'cid': cid,
                                   'has_annotations': has_annotations,
                                   'has_articles': has_articles,
                                   'has_dv_content': has_dv_content,
                                   'has_vocabulary': has_vocabulary,
                                   'last_opened': last_opened,
                                   'path': path,
                                   'title': title,
                                   'uuid': uuid
                                  }

        return selected_books

    def _selected_cid(self, row):
        '''
        Return selected calibre id
        '''
        return self.tm.arraydata[row][self.CALIBRE_ID_COL]

    def _selected_rows(self):
        '''
        Return a list of selected rows
        '''
        srs = self.tv.selectionModel().selectedRows()
        return [sr.row() for sr in srs]

    def _set_flags(self, action):
        '''
        Set specified flags for selected books
        '''
        def _build_flag_list(flagbits):
            flags = []
            if flagbits & self.NEW_FLAG:
                flags.append(self.FLAGS['new'])
            if flagbits & self.READING_FLAG:
                flags.append(self.FLAGS['reading_list'])
            if flagbits & self.READ_FLAG:
                flags.append(self.FLAGS['read'])
            return flags

        self._log_location(action)
        if action == 'set_new_flag':
            mask = self.NEW_FLAG
        elif action == 'set_reading_list_flag':
            mask = self.READING_FLAG
        elif action == 'set_read_flag':
            mask = self.READ_FLAG

        selected_books = self._selected_books()
        for row in selected_books:
            book_id = selected_books[row]['book_id']
            flagbits = self.tm.arraydata[row][self.FLAGS_COL].sort_key
            if not flagbits & mask:
                # Set the bit with OR
                flagbits = flagbits | mask
                basename = "flags%d.png" % flagbits
                new_flags_widget = SortableImageWidgetItem(self,
                                                       os.path.join(self.parent.opts.resources_path,
                                                         'icons', basename),
                                                       flagbits, self.FLAGS_COL)
                # Update the model
                self.tm.arraydata[row][self.FLAGS_COL] = new_flags_widget

                # Update self.installed_books flags list
                self.installed_books[book_id].flags = _build_flag_list(flagbits)

                # Update Marvin db
                self._log("*** DON'T FORGET TO TELL MARVIN ABOUT THE UPDATED FLAGS ***")

            path = selected_books[row]['path']
            self._update_device_flags(book_id, path, _build_flag_list(flagbits))

        self.repaint()

    def _stage_command_file(self, command_name, command_soup, show_command=False):
        self._log_location(command_name)

        if show_command:
            if command_name == 'update_metadata':
                soup = BeautifulStoneSoup(command_soup.renderContents())
                # <descriptions>
                descriptions = soup.findAll('description')
                for description in descriptions:
                    d_tag = Tag(soup, 'description')
                    d_tag.insert(0, "(description removed for debug stream)")
                    description.replaceWith(d_tag)
                # <covers>
                covers = soup.findAll('cover')
                for cover in covers:
                    cover_tag = Tag(soup, 'cover')
                    cover_tag.insert(0, "(cover removed for debug stream)")
                    cover.replaceWith(cover_tag)
                self._log(soup.prettify())
            else:
                self._log("command_name: %s" % command_name)
                self._log(command_soup.prettify())

        self.ios.write(command_soup.renderContents(),
                       b'/'.join([self.parent.connected_device.staging_folder, b'%s.tmp' % command_name]))
        self.ios.rename(b'/'.join([self.parent.connected_device.staging_folder, b'%s.tmp' % command_name]),
                        b'/'.join([self.parent.connected_device.staging_folder, b'%s.xml' % command_name]))

    def _update_calibre_collections(self, cid, updated_calibre_collections):
        '''
        '''
        self._log_location()
        # Update collections custom column
        lookup = self.parent.prefs.get('collection_field_lookup', None)
        if lookup is not None and cid is not None:
            # Get the current value from the lookup field
            db = self.opts.gui.current_db
            mi = db.get_metadata(cid, index_is_id=True)
            #old_collections = mi.get_user_metadata(lookup, False)['#value#']
            #self._log("Updating old collections value: %s" % repr(old_collections))

            um = mi.metadata_for_field(lookup)
            um['#value#'] = updated_calibre_collections
            mi.set_user_metadata(lookup, um)
            db.set_metadata(cid, mi, set_title=False, set_authors=False)
            db.commit()

    def _update_calibre_metadata(self, book_id, cid, mismatches):
        '''
        Update calibre from Marvin metadata
        '''
        self._log_location(mismatches)

    def _update_device_flags(self, book_id, path, updated_flags):
        '''
        Given a set of updated flags for path, update local copies:
            cached_books[path]['device_collections']
            Device model book.device_collections
            (installed_books already updated in _clear_flags, _set_flags())
        '''
        self._log_location("%s: %s" % (self.installed_books[book_id].title, updated_flags))

        # Get current collection assignments
        marvin_collections = self.installed_books[book_id].device_collections
        updated_collections = sorted(updated_flags + marvin_collections, key=sort_key)

        # Update driver
        cached_books = self.parent.connected_device.cached_books
        cached_books[path]['device_collections'] = updated_collections

        # Update Device model
        for row in self.opts.gui.memory_view.model().map:
            book = self.opts.gui.memory_view.model().db[row]
            if book.path == path:
                book.device_collections = updated_collections
                break

    def _update_collections(self, action):
        '''
        Apply action to selected books.
            export_collections
            import_collections
            synchronize_collections
            clear_all_collections
        '''
        self._log_location(action)

        selected_books = self._selected_books()
        for row in selected_books:
            book_id = self._selected_book_id(row)
            cid = self._selected_cid(row)
            calibre_collections = self._get_calibre_collections(cid)
            marvin_collections = self._get_marvin_collections(book_id)
            if action == 'export_collections':
                # Apply calibre collections to Marvin
                self._log("export_collections: %s" % selected_books[row]['title'])
                self._update_marvin_collections(book_id, calibre_collections)

            elif action == 'import_collections':
                # Apply Marvin collections to calibre
                self._log("import_collections: %s" % selected_books[row]['title'])
                self._update_calibre_collections(cid, marvin_collections)

            elif action == 'synchronize_collections':
                # Merged collections to both calibre and Marvin
                self._log("synchronize_collections: %s" % selected_books[row]['title'])
                cl = set(calibre_collections)
                ml = set(marvin_collections)
                deltas = ml - cl
                merged_collections = sorted(calibre_collections + list(deltas), key=sort_key)
                self._update_calibre_collections(merged_collections)
                self._update_marvin_collections(merged_collections)

            elif action == 'clear_all_collections':
                # Remove all collection assignments from both calibre and Marvin
                self._log("clear_all_collections: %s" % selected_books[row]['title'])
                self._update_calibre_collections(cid, [])
                self._update_marvin_collections(book_id, [])

            else:
                self._log("unsupported action: %s" % action)
                title = "Update collections"
                msg = ("<p>{0}: not implemented</p>".format(action))
                MessageBox(MessageBox.INFO, title, msg,
                               show_copy_button=False).exec_()

    def _update_flags(self, action):
        '''
        '''
        if action in ['clear_new_flag', 'clear_reading_list_flag',
                        'clear_read_flag', 'clear_all_flags']:
            self._clear_flags(action)

        elif action in ['set_new_flag', 'set_reading_list_flag', 'set_read_flag']:
            self._set_flags(action)

        else:
            self._log("unsupported action: %s" % action)
            title = "Update flags"
            msg = ("<p>{0}: not implemented</p>".format(action))
            MessageBox(MessageBox.INFO, title, msg,
                           show_copy_button=False).exec_()

    def _update_marvin_collections(self, book_id, updated_marvin_collections):
        '''
        '''
        self._log_location()

        # Update installed_books
        self.installed_books[book_id].device_collections = updated_marvin_collections

        # Merge active flags with updated marvin collections
        cached_books = self.parent.connected_device.cached_books
        path = self.installed_books[book_id].path
        active_flags = self.installed_books[book_id].flags
        updated_collections = sorted(active_flags +
                                     updated_marvin_collections,
                                     key=sort_key)

        # Update driver (cached_books)
        cached_books[path]['device_collections'] = updated_collections

        # Update Device model
        for row in self.opts.gui.memory_view.model().map:
            book = self.opts.gui.memory_view.model().db[row]
            if book.path == path:
                book.device_collections = updated_collections
                break

        # Update Marvin
        self._log("DON'T FORGET TO TELL MARVIN ABOUT UPDATED COLLECTIONS")

    def _update_marvin_metadata(self, book_id, cid, mismatches):
        '''
        Update Marvin from calibre metadata
        '''
        self._log_location(mismatches)

    def _update_metadata(self, action):
        '''
        '''
        self._log_location(action)

        selected_books = self._selected_books()
        for row in selected_books:
            book_id = self._selected_book_id(row)
            cid = self._selected_cid(row)
            mismatches = self.installed_books[book_id].metadata_mismatches
            if action == 'export_metadata':
                # Apply calibre metadata to Marvin
                self._update_marvin_metadata(book_id, cid, mismatches)

            elif action == 'import_metadata':
                # Apply Marvin metadata to calibre
                self._update_calibre_metadata(book_id, cid, mismatches)


        """
        title = "Synchronize metadata"
        msg = ("<p>Not implemented</p>")
        MessageBox(MessageBox.INFO, title, msg,
                       show_copy_button=False).exec_()
        """

    def _update_remote_hash_cache(self):
        '''
        Copy updated hash cache to iDevice
        self.local_hash_cache, self.remote_hash_cache initialized
        in _localize_hash_cache()
        '''
        self._log_location()

        if self.parent.prefs.get('hash_caching_disabled', False):
            self._log("hash_caching_disabled, deleting remote hash cache")
            self.ios.remove(str(self.remote_hash_cache))
        else:
            # Copy local cache to iDevice
            self.ios.copy_to_idevice(self.local_hash_cache, str(self.remote_hash_cache))

    def _wait_for_command_completion(self, command_name, send_signal=True):
        '''
        Wait for Marvin to issue progress reports via status.xml
        Marvin creates status.xml upon receiving command, increments <progress>
        from 0.0 to 1.0 as command progresses.
        '''
        self._log_location(command_name)
        self._log("%s: waiting for '%s'" %
                                     (datetime.now().strftime('%H:%M:%S.%f'),
                                     self.parent.connected_device.status_fs))

        # Set initial watchdog timer for ACK
        WATCHDOG_TIMEOUT = 10.0
        watchdog = Timer(WATCHDOG_TIMEOUT, self._watchdog_timed_out)
        self.operation_timed_out = False
        watchdog.start()

        while True:
            if not self.ios.exists(self.parent.connected_device.status_fs):
                # status.xml not created yet
                if self.operation_timed_out:
                    self.ios.remove(self.parent.connected_device.status_fs)
                    raise UserFeedback("Marvin operation timed out.",
                                        details=None, level=UserFeedback.WARN)
                time.sleep(0.10)

            else:
                watchdog.cancel()

                self._log("%s: monitoring progress of %s" %
                                     (datetime.now().strftime('%H:%M:%S.%f'),
                                      command_name))

                # Start a new watchdog timer per iteration
                watchdog = Timer(WATCHDOG_TIMEOUT, self._watchdog_timed_out)
                self.operation_timed_out = False
                watchdog.start()

                code = '-1'
                current_timestamp = 0.0
                while code == '-1':
                    try:
                        if self.operation_timed_out:
                            self.ios.remove(self.parent.connected_device.status_fs)
                            raise UserFeedback("Marvin operation timed out.",
                                                details=None, level=UserFeedback.WARN)

                        status = etree.fromstring(self.ios.read(self.parent.connected_device.status_fs))
                        code = status.get('code')
                        timestamp = float(status.get('timestamp'))
                        if timestamp != current_timestamp:
                            current_timestamp = timestamp
                            d = datetime.now()
                            progress = float(status.find('progress').text)
                            self._log("{0}: {1:>2} {2:>3}%".format(
                                                 d.strftime('%H:%M:%S.%f'),
                                                 code,
                                                 "%3.0f" % (progress * 100)))
                            """
                            # Report progress
                            if self.report_progress is not None:
                                self.report_progress(0.5 + progress/2, '')
                            """

                            # Reset watchdog timer
                            watchdog.cancel()
                            watchdog = Timer(WATCHDOG_TIMEOUT, self._watchdog_timed_out)
                            watchdog.start()
                        time.sleep(0.01)

                    except:
                        time.sleep(0.01)
                        self._log("%s:  retry" % datetime.now().strftime('%H:%M:%S.%f'))

                # Command completed
                watchdog.cancel()

                final_code = status.get('code')
                if final_code != '0':
                    if final_code == '-1':
                        final_status= "in progress"
                    if final_code == '1':
                        final_status = "warnings"
                    if final_code == '2':
                        final_status = "errors"

                    messages = status.find('messages')
                    msgs = [msg.text for msg in messages]
                    details = "code: %s\n" % final_code
                    details += '\n'.join(msgs)
                    self._log(details)
                    raise UserFeedback("Marvin reported %s.\nClick 'Show details' for more information."
                                        % (final_status),
                                       details=details, level=UserFeedback.WARN)

                self.ios.remove(self.parent.connected_device.status_fs)

                self._log("%s: '%s' complete" %
                                     (datetime.now().strftime('%H:%M:%S.%f'),
                                      command_name))
                break
        """
        if self.report_progress is not None:
            self.report_progress(1.0, _('finished'))
        """

    def _watchdog_timed_out(self):
        '''
        Set flag if I/O operation times out
        '''
        self._log_location(datetime.now().strftime('%H:%M:%S.%f'))
        self.operation_timed_out = True

