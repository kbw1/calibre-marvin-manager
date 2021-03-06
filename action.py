#!/usr/bin/env python
# coding: utf-8

from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__ = 'GPL v3'
__copyright__ = '2013, Greg Riker <griker@hotmail.com>'
__docformat__ = 'restructuredtext en'

import atexit, os, sys, threading

from functools import partial
from lxml import etree, html
from zipfile import ZipFile

from PyQt4.Qt import (Qt, QApplication, QCursor, QIcon, QMenu, QTimer, QUrl,
                      pyqtSignal)

from calibre.constants import DEBUG
from calibre.customize.ui import device_plugins, disabled_device_plugins
from calibre.devices.idevice.libimobiledevice import libiMobileDevice
from calibre.devices.usbms.driver import debug_print
from calibre.ebooks.BeautifulSoup import BeautifulSoup
from calibre.gui2 import Application, open_url
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.device import device_signals
from calibre.gui2.dialogs.message_box import MessageBox
from calibre.library import current_library_name
from calibre.utils.config import config_dir

from calibre_plugins.marvin_manager import MarvinManagerPlugin
from calibre_plugins.marvin_manager.annotations_db import AnnotationsDB
from calibre_plugins.marvin_manager.book_status import BookStatusDialog
from calibre_plugins.marvin_manager.common_utils import (AbortRequestException,
    CompileUI, IndexLibrary, Logger, MyBlockingBusy, ProgressBar, Struct,
    get_icon, set_plugin_icon_resources, updateCalibreGUIView)
import calibre_plugins.marvin_manager.config as cfg
#from calibre_plugins.marvin_manager.dropbox import PullDropboxUpdates

# The first icon is the plugin icon, referenced by position.
# The rest of the icons are referenced by name
PLUGIN_ICONS = ['images/connected.png', 'images/disconnected.png']

class MarvinManagerAction(InterfaceAction, Logger):

    # Location reporting template
    LOCATION_TEMPLATE = "{cls}:{func}({arg1}) {arg2}"

    icon = PLUGIN_ICONS[0]
    minimum_ios_driver_version = (1, 3, 1)
    name = 'Marvin XD'
    prefs = cfg.plugin_prefs
    verbose = prefs.get('debug_plugin', False)

    # Declare the main action associated with this plugin
    action_spec = ('Marvin XD', None, None, None)
    #popup_type = QToolButton.InstantPopup
    action_add_menu = True
    action_menu_clone_qaction = True

    marvin_device_status_changed = pyqtSignal(str)
    plugin_device_connection_changed = pyqtSignal(object)

    def about_to_show_menu(self):
        self.rebuild_menus()

    def backup_restore(self):
        self._log_location("not implemented")

    def create_menu_item(self, m, menu_text, image=None, tooltip=None, shortcut=None):
        ac = self.create_action(spec=(menu_text, None, tooltip, shortcut), attr=menu_text)
        if image:
            ac.setIcon(QIcon(image))
        m.addAction(ac)
        return ac

    def developer_utilities(self, action):
        '''
        'Delete calibre hashes', 'Delete Marvin hashes'
        remote_cache_folder = '/'.join(['/Library', 'calibre.mm'])
        '''
        self._log_location(action)
        if action in ['Delete calibre hashes', 'Delete Marvin hashes',
                      'Nuke annotations', 'Reset column widths']:
            if action == 'Delete Marvin hashes':
                remote_cache_folder = '/'.join(['/Library', 'calibre.mm'])
                rhc = b'/'.join([remote_cache_folder, BookStatusDialog.HASH_CACHE_FS])

                if self.ios.exists(rhc):
                    self.ios.remove(rhc)
                    self._log("remote hash cache at %s deleted" % rhc)
            elif action == 'Delete calibre hashes':
                self.gui.current_db.delete_all_custom_book_data('epub_hash')
                self._log("cached epub hashes deleted")
                # Invalidate the library hash map, as library contents may change before reconnection
                if hasattr(self, 'library_scanner'):
                    self.library_scanner.hash_map = None
            elif action == 'Nuke annotations':
                self.nuke_annotations()
            elif action == 'Reset column widths':
                self._log("deleting marvin_library_column_widths")
                self.prefs.pop('marvin_library_column_widths')
                self.prefs.commit()
        else:
            self._log("unrecognized action")

    def discover_iosra_status(self):
        '''
        Confirm that iOSRA is installed and not disabled
        '''
        IOSRA = 'iOS reader applications'
        # Confirm that iOSRA is installed
        installed = False
        disabled = False
        status = "Marvin not connected"
        for dp in device_plugins(include_disabled=True):
            if dp.name == IOSRA:
                installed = True
                for ddp in disabled_device_plugins():
                    if ddp.name == IOSRA:
                        disabled = True
                break

        msg = None
        if not installed:
            status = "iOSRA plugin not installed"
            msg = ('<p>Marvin XD requires the iOS reader applications plugin to be installed.</p>' +
                   '<p>Install the plugin, configure it with Marvin ' +
                   'as the preferred reader application, then restart calibre.</p>' +
                   '<p><a href="http://www.mobileread.com/forums/showthread.php?t=215624">' +
                   'iOS reader applications support</a><br/>'
                   '<a href="http://www.mobileread.com/forums/showthread.php?t=221357">' +
                   'Marvin XD support</a></p>')
        elif installed and disabled:
            status = "iOSRA plugin disabled"
            msg = ('<p>Marvin XD requires the iOS reader applications plugin to be enabled.</p>' +
                   '<p>Enable the plugin in <i>Preferences|Advanced|Plugins</i>, ' +
                   'configure it with Marvin as the preferred reader application, ' +
                   'then restart calibre.</p>' +
                   '<p><a href="http://www.mobileread.com/forums/showthread.php?t=215624">' +
                   'iOS reader applications support</a><br/>'
                   '<a href="http://www.mobileread.com/forums/showthread.php?t=221357">' +
                   'Marvin XD support</a></p>')
        if msg:
            MessageBox(MessageBox.WARNING, status, msg, det_msg='', show_copy_button=False).exec_()

        return status

    # subclass override
    def genesis(self):
        self._log_location("v%d.%d.%d" % MarvinManagerPlugin.version)

        # General initialization, occurs when calibre launches
        self.book_status_dialog = None
        self.blocking_busy = MyBlockingBusy(self.gui, "Updating Marvin Library…", size=50)
        self.connected_device = None
        self.current_location = 'library'
        self.dropbox_processed = False
        self.ios = None
        self.installed_books = None
        self.marvin_content_updated = False
        self.menus_lock = threading.RLock()
        self.sync_lock = threading.RLock()
        self.indexed_library = None
        self.library_indexed = False
        self.library_last_modified = None
        self.marvin_connected = False
        self.resources_path = os.path.join(config_dir, 'plugins', "%s_resources" % self.name.replace(' ', '_'))
        if not os.path.exists(self.resources_path):
            os.makedirs(self.resources_path)
        self.virtual_library = None

        # Build a current opts object
        self.opts = self.init_options()

        # Read the plugin icons and store for potential sharing with the config widget
        icon_resources = self.load_resources(PLUGIN_ICONS)
        set_plugin_icon_resources(self.name, icon_resources)

        # Assign our menu to this action and an icon
        self.menu = QMenu(self.gui)
        self.qaction.setMenu(self.menu)
        self.qaction.setIcon(get_icon("images/disconnected.png"))
        self.qaction.triggered.connect(self.main_menu_button_clicked)
        self.menu.aboutToShow.connect(self.about_to_show_menu)

        # Init the prefs file
        self.init_prefs()

        # Populate dialog resources
        self.inflate_dialog_resources()

        # Populate the help resources
        self.inflate_help_resources()

        # Populate icon resources
        self.inflate_icon_resources()

        # Compile .ui files as needed
        CompileUI(self)

        '''
        # Hook exit in case we need to do cleanup
        atexit.register(self.onexit)
        '''

    def inflate_dialog_resources(self):
        '''
        Copy the dialog files to our resource directory
        '''
        self._log_location()

        dialogs = []
        with ZipFile(self.plugin_path, 'r') as zf:
            for candidate in zf.namelist():
                # Qt UI files
                if candidate.startswith('dialogs/') and candidate.endswith('.ui'):
                    dialogs.append(candidate)
                # Corresponding class definitions
                if candidate.startswith('dialogs/') and candidate.endswith('.py'):
                    dialogs.append(candidate)
        dr = self.load_resources(dialogs)
        for dialog in dialogs:
            if not dialog in dr:
                continue
            fs = os.path.join(self.resources_path, dialog)
            if not os.path.exists(fs):
                # If the file doesn't exist in the resources dir, add it
                if not os.path.exists(os.path.dirname(fs)):
                    os.makedirs(os.path.dirname(fs))
                with open(fs, 'wb') as f:
                    f.write(dr[dialog])
            else:
                # Is the .ui file current?
                update_needed = False
                with open(fs, 'r') as f:
                    if f.read() != dr[dialog]:
                        update_needed = True
                if update_needed:
                    with open(fs, 'wb') as f:
                        f.write(dr[dialog])

    def inflate_help_resources(self):
        '''
        Extract the help resources from the plugin
        '''
        help_resources = []
        with ZipFile(self.plugin_path, 'r') as zf:
            for candidate in zf.namelist():
                if (candidate.startswith('help/') and candidate.endswith('.html') or
                    candidate.startswith('help/images/')):
                    help_resources.append(candidate)

        rd = self.load_resources(help_resources)
        for resource in help_resources:
            if not resource in rd:
                continue
            fs = os.path.join(self.resources_path, resource)
            if os.path.isdir(fs) or fs.endswith('/'):
                continue
            if not os.path.exists(os.path.dirname(fs)):
                os.makedirs(os.path.dirname(fs))
            with open(fs, 'wb') as f:
                f.write(rd[resource])

    def inflate_icon_resources(self):
        '''
        Extract the icon resources from the plugin
        '''
        icons = []
        with ZipFile(self.plugin_path, 'r') as zf:
            for candidate in zf.namelist():
                if candidate.endswith('/'):
                    continue
                if candidate.startswith('icons/'):
                    icons.append(candidate)
        ir = self.load_resources(icons)
        for icon in icons:
            if not icon in ir:
                continue
            fs = os.path.join(self.resources_path, icon)
            if not os.path.exists(fs):
                if not os.path.exists(os.path.dirname(fs)):
                    os.makedirs(os.path.dirname(fs))
                with open(fs, 'wb') as f:
                    f.write(ir[icon])

    def init_options(self, disable_caching=False):
        """
        Build an opts object with a ProgressBar, Annotations db
        """
        opts = Struct(
            gui=self.gui,
            #icon=get_icon(PLUGIN_ICONS[0]),
            prefs=self.prefs,
            resources_path=self.resources_path,
            verbose=DEBUG)

        self._log_location()

        # Attach a Progress bar
        opts.pb = ProgressBar(parent=self.gui, window_title=self.name)

        # Instantiate the Annotations database
        opts.db = AnnotationsDB(opts, path=os.path.join(self.resources_path, 'annotations.db'))
        opts.conn = opts.db.connect()

        return opts

    def init_prefs(self):
        '''
        Set the initial default values as needed, do any needed maintenance
        '''
        pref_map = {
            'plugin_version': "%d.%d.%d" % self.interface_action_base_plugin.version,
            'injected_css': "h1\t{font-size: 1.5em;}\nh2\t{font-size: 1.25em;}\nh3\t{font-size: 1em;}"
            }

        for pm in pref_map:
            if not self.prefs.get(pm, None):
                self.prefs.set(pm, pref_map[pm])

        # Clean up JSON file < v1.1.0
        prefs_version = self.prefs.get("plugin_version", "0.0.0")
        if prefs_version < "1.1.0":
            self._log_location("Updating prefs to %d.%d.%d" %
                self.interface_action_base_plugin.version)
            for obsolete_setting in [
                'annotations_field_comboBox', 'annotations_field_lookup',
                'collection_field_comboBox', 'collection_field_lookup',
                'date_read_field_comboBox', 'date_read_field_lookup',
                'progress_field_comboBox', 'progress_field_lookup',
                'read_field_comboBox', 'read_field_lookup',
                'reading_list_field_comboBox', 'reading_list_field_lookup',
                'word_count_field_comboBox', 'word_count_field_lookup']:
                if self.prefs.get(obsolete_setting, None) is not None:
                    self._log("removing obsolete entry '{0}'".format(obsolete_setting))
                    self.prefs.__delitem__(obsolete_setting)
            self.prefs.set('plugin_version', "%d.%d.%d" % self.interface_action_base_plugin.version)

    # subclass override
    def initialization_complete(self):
        self.rebuild_menus()

        # Subscribe to device connection events
        device_signals.device_connection_changed.connect(self.on_device_connection_changed)

    def launch_library_scanner(self):
        '''
        Call IndexLibrary() to index current_db by uuid, title
        Need a test to see if db has been updated since last run. Until then,
        optimization disabled.
        After indexing, self.library_scanner.uuid_map and .title_map are populated
        '''

        mdb = self.gui.library_view.model().db
        current_vl = mdb.data.get_base_restriction_name()

        if (self.library_last_modified == self.gui.current_db.last_modified() and
                self.indexed_library is self.gui.current_db and
                self.library_indexed and
                self.library_scanner is not None and
                self.virtual_library == current_vl):
            self._log_location("library index current for virtual library %s" % repr(current_vl))
        else:
            self._log_location("updating library index for virtual library %s" % repr(current_vl))
            self.library_scanner = IndexLibrary(self)

            if False:
                self.connect(self.library_scanner, self.library_scanner.signal, self.library_index_complete)
                QTimer.singleShot(1, self.start_library_indexing)

                # Wait for indexing to complete
                while not self.library_scanner.isFinished():
                    Application.processEvents()
            else:
                self.start_library_indexing()
                while not self.library_scanner.isFinished():
                    Application.processEvents()
                self.library_index_complete()

    # subclass override
    def library_changed(self, db):
        self._log_location(current_library_name())
        self.indexed_library = None
        self.library_indexed = False
        self.library_scanner = None
        self.library_last_modified = None

    def library_index_complete(self):
        self._log_location()
        self.library_indexed = True
        self.indexed_library = self.gui.current_db
        self.library_last_modified = self.gui.current_db.last_modified()

        # Save the virtual library name we ran the indexing against
        mdb = self.gui.library_view.model().db
        current_vl = mdb.data.get_base_restriction_name()
        self.virtual_library = self.library_scanner.active_virtual_library = current_vl

        # Reset the hash_map in case we had a prior instance from a different vl
        self.library_scanner.hash_map = None

        # Reset self.installed_books
        self.installed_books = None

        self._busy_panel_teardown()

    # subclass override
    def location_selected(self, loc):
        self._log_location(loc)
        self.current_location = loc

    def main_menu_button_clicked(self):
        '''
        Primary click on menu button
        '''
        self._log_location()
        if self.connected_device:
            if not self.book_status_dialog:
                try:
                    self.show_installed_books()
                except AbortRequestException, e:
                    self._log(e)
                    self.book_status_dialog = None
        else:
            self.show_help()

    def marvin_status_changed(self, command):
        '''
        The Marvin driver emits a signal after completion of protocol commands.
        This method receives the notification. If the content on Marvin changed
        as a result of the operation, we need to invalidate our cache of Marvin's
        installed books.
        '''
        self.marvin_device_status_changed.emit(command)

        self._log_location(command)
        if command in ['delete_books', 'upload_books']:
            self.marvin_content_updated = True

    def nuke_annotations(self):
        db = self.gui.current_db
        id = db.FIELD_MAP['id']

        # Get all eligible custom fields
        all_custom_fields = db.custom_field_keys()
        custom_fields = {}
        for custom_field in all_custom_fields:
            field_md = db.metadata_for_field(custom_field)
            if field_md['datatype'] in ['comments']:
                custom_fields[field_md['name']] = {'field': custom_field,
                                                        'datatype': field_md['datatype']}

        fields = ['Comments']
        for cfn in custom_fields:
            fields.append(cfn)
        fields.sort()

        # Warn the user that we're going to do it
        title = 'Remove annotations?'
        msg = ("<p>All existing annotations will be removed from %s.</p>" %
               ', '.join(fields) +
               "<p>Proceed?</p>")
        d = MessageBox(MessageBox.QUESTION,
                       title, msg,
                       show_copy_button=False)
        if not d.exec_():
            return
        self._log_location("QUESTION: %s" % msg)

        # Show progress
        pb = ProgressBar(parent=self.gui, window_title="Removing annotations")
        total_books = len(db.data)
        pb.set_maximum(total_books)
        pb.set_value(0)
        pb.set_label('{:^100}'.format("Scanning 0 of %d" % (total_books)))
        pb.show()

        for i, record in enumerate(db.data.iterall()):
            mi = db.get_metadata(record[id], index_is_id=True)
            pb.set_label('{:^100}'.format("Scanning %d of %d" % (i, total_books)))

            # Remove user_annotations from Comments
            if mi.comments:
                soup = BeautifulSoup(mi.comments)
                uas = soup.find('div', 'user_annotations')
                if uas:
                    uas.extract()

                # Remove comments_divider from Comments
                cd = soup.find('div', 'comments_divider')
                if cd:
                    cd.extract()

                # Save stripped Comments
                mi.comments = unicode(soup)

                # Update the record
                db.set_metadata(record[id], mi, set_title=False, set_authors=False,
                                commit=True, force_changes=True, notify=True)

            # Removed user_annotations from custom fields
            for cfn in custom_fields:
                cf = custom_fields[cfn]['field']
                if True:
                    soup = BeautifulSoup(mi.get_user_metadata(cf, False)['#value#'])
                    uas = soup.findAll('div', 'user_annotations')
                    if uas:
                        # Remove user_annotations from originating custom field
                        for ua in uas:
                            ua.extract()

                        # Save stripped custom field data
                        um = mi.metadata_for_field(cf)
                        stripped = unicode(soup)
                        if stripped == u'':
                            stripped = None
                        um['#value#'] = stripped
                        mi.set_user_metadata(cf, um)

                        # Update the record
                        db.set_metadata(record[id], mi, set_title=False, set_authors=False,
                                        commit=True, force_changes=True, notify=True)
                else:
                    um = mi.metadata_for_field(cf)
                    um['#value#'] = None
                    mi.set_user_metadata(cf, um)
                    # Update the record
                    db.set_metadata(record[id], mi, set_title=False, set_authors=False,
                                    commit=True, force_changes=True, notify=True)

            pb.increment()

        # Hide the progress bar
        pb.hide()

        # Update the UI
        updateCalibreGUIView()

    def onexit(self):
        '''
        Called as calibre is exiting.
        '''
        self._log_location()

    def on_device_connection_changed(self, is_connected):
        '''
        self.connected_device is the handle to the driver.
        '''
        self.plugin_device_connection_changed.emit(is_connected)

        if is_connected:
            self.connected_device = self.gui.device_manager.device
            self.marvin_connected = (hasattr(self.connected_device, 'ios_reader_app') and
                                     self.connected_device.ios_reader_app == 'Marvin')
            if self.marvin_connected:

                self._log_location(self.connected_device.gui_name)

                # Init libiMobileDevice
                self.ios = libiMobileDevice(verbose=self.prefs.get('debug_libimobiledevice', False))
                self._log("mounting %s" % self.connected_device.app_id)
                self.ios.mount_ios_app(app_id=self.connected_device.app_id)

                # Change our icon
                self.qaction.setIcon(get_icon("images/connected.png"))

                # Subscribe to Marvin driver change events
                self.connected_device.marvin_device_signals.reader_app_status_changed.connect(
                    self.marvin_status_changed)

                # Explore connected.xml for <has_password>
                connected_fs = getattr(self.connected_device, 'connected_fs', None)
                if connected_fs and self.ios.exists(connected_fs):

                    # Wait for the driver to be silent to explore connected.xml
                    while self.connected_device.get_busy_flag():
                        Application.processEvents()
                    self.connected_device.set_busy_flag(True)

                    # connection.keys(): ['timestamp', 'marvin', 'device', 'system']
                    connection = etree.fromstring(self.ios.read(connected_fs))
                    #self._log(etree.tostring(connection, pretty_print=True))
                    self._log_location("%s running iOS %s" % (connection.get('device'), connection.get('system')))

                    self.has_password = False
                    chp = connection.find('has_password')
                    if chp is not None:
                        self.has_password = bool(chp.text == "true")
                    self._log("has_password: %s" % self.has_password)

                    self.connected_device.set_busy_flag(False)
            else:
                self._log("Marvin not connected")

        else:
            if self.marvin_connected:
                self._log_location("device disconnected")

                # Change our icon
                self.qaction.setIcon(get_icon("images/disconnected.png"))

                # Close libiMobileDevice connection, reset references to mounted device
                self.ios.disconnect_idevice()
                self.ios = None
                self.connected_device.marvin_device_signals.reader_app_status_changed.disconnect()
                self.connected_device = None

                # Invalidate the library hash map, as library contents may change before reconnection
                #self.library_scanner.hash_map = None

                # Clear has_password
                self.has_password = None

                # Dump our saved copy of installed_books
                self.installed_books = None

                self.marvin_connected = False

        self.rebuild_menus()

    """
    def process_dropbox_sync_records(self):
        '''
        Scan local Dropbox folder for metadata update records
        Show progress bar in dialog box reporting titles
        '''
        self._log_location()

        self.launch_library_scanner()
        foo = PullDropboxUpdates(self)
    """

    def rebuild_menus(self):
        self._log_location()
        with self.menus_lock:
            m = self.menu
            m.clear()

            # Add 'About…'
            ac = self.create_menu_item(m, 'About' + '…')
            ac.triggered.connect(self.show_about)
            m.addSeparator()

            # Add menu options for connected Marvin, Dropbox syncing when no connection
            marvin_connected = False

            dropbox_syncing_enabled = self.prefs.get('dropbox_syncing', False)
            process_dropbox = False

            if self.connected_device and hasattr(self.connected_device, 'ios_reader_app'):
                if (self.connected_device.ios_reader_app == 'Marvin' and
                        self.connected_device.ios_connection['connected'] is True):
                    self._log("Marvin connected")
                    marvin_connected = True
                    ac = self.create_menu_item(m, 'Explore Marvin Library', image=I("dialog_information.png"))
                    ac.triggered.connect(self.show_installed_books)

                    if False:
                        ac = self.create_menu_item(m, 'Backup or Restore Library', image=I("swap.png"))
                        ac.triggered.connect(self.backup_restore)
                        ac.setEnabled(False)

                        ac = self.create_menu_item(m, 'Reset Marvin Library', image=I("trash.png"))
                        ac.triggered.connect(self.reset_marvin_library)
                        ac.setEnabled(False)

                else:
                    self._log("Marvin not connected")
                    ac = self.create_menu_item(m, 'Marvin not connected')
                    ac.setEnabled(False)

            elif False and not self.connected_device:
                ac = self.create_menu_item(m, 'Update metadata via Dropbox')
                ac.triggered.connect(self.process_dropbox_sync_records)

                # If syncing enabled in Config dialog, automatically process 1x
                if dropbox_syncing_enabled and not self.dropbox_processed:
                    process_dropbox = True
            else:
                iosra_status = self.discover_iosra_status()
                self._log(iosra_status)
                ac = self.create_menu_item(m, iosra_status)
                ac.setEnabled(False)

            m.addSeparator()

            # Add 'Customize plugin…'
            ac = self.create_menu_item(m, 'Customize plugin' + '…', image=I("config.png"))
            ac.triggered.connect(self.show_configuration)

            m.addSeparator()

            # Add 'Help'
            ac = self.create_menu_item(m, 'Help', image=I('help.png'))
            ac.triggered.connect(self.show_help)

            # If Alt/Option key pressed, show Developer submenu
            modifiers = Application.keyboardModifiers()
            if bool(modifiers & Qt.AltModifier):
                m.addSeparator()
                self.developer_menu = m.addMenu(QIcon(I('config.png')),
                                                "Developer…")
                action = 'Delete calibre hashes'
                ac = self.create_menu_item(self.developer_menu, action, image=I('trash.png'))
                ac.triggered.connect(partial(self.developer_utilities, action))

                action = 'Delete Marvin hashes'
                ac = self.create_menu_item(self.developer_menu, action, image=I('trash.png'))
                ac.triggered.connect(partial(self.developer_utilities, action))
                ac.setEnabled(marvin_connected)

                action = 'Nuke annotations'
                ac = self.create_menu_item(self.developer_menu, action, image=I('trash.png'))
                ac.triggered.connect(partial(self.developer_utilities, action))

                action = 'Reset column widths'
                ac = self.create_menu_item(self.developer_menu, action, image=I('trash.png'))
                ac.triggered.connect(partial(self.developer_utilities, action))

            # Process Dropbox sync records automatically once only.
            if process_dropbox:
                self.process_dropbox_sync_records()
                self.dropbox_processed = True

    def reset_marvin_library(self):
        self._log_location("not implemented")

    def show_configuration(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def show_about(self):
        version = self.interface_action_base_plugin.version
        title = "%s v %d.%d.%d" % (self.name, version[0], version[1], version[2])
        msg = ('<p>To learn more about this plugin, visit the '
               '<a href="http://www.mobileread.com/forums/showthread.php?t=221357">Marvin XD</a> '
               'support thread at MobileRead’s Calibre forum.</p>')
        text = get_resources('about.txt')
        text = text.decode('utf-8')
        d = MessageBox(MessageBox.INFO, title, msg, det_msg=text, show_copy_button=False)
        d.exec_()

    def show_help(self):
        path = os.path.join(self.resources_path, 'help/help.html')
        open_url(QUrl.fromLocalFile(path))

    def show_installed_books(self):
        '''
        Show Marvin Library spreadsheet
        '''
        self._log_location()

        if self.connected_device.version < self.minimum_ios_driver_version:
            title = "Update required"
            msg = "<p>{0} requires v{1}.{2}.{3} (or later) of the iOS reader applications device driver.</p>".format(
                self.name,
                self.minimum_ios_driver_version[0],
                self.minimum_ios_driver_version[1],
                self.minimum_ios_driver_version[2])
            MessageBox(MessageBox.INFO, title, msg, det_msg='', show_copy_button=False).exec_()
        else:
            self.launch_library_scanner()

            # Assure that Library is active view. Avoids problems with _delete_books
            restore_to = None
            if self.current_location != 'library':
                restore_to = self.current_location
                self.gui.location_selected('library')

            self.book_status_dialog = BookStatusDialog(self, 'marvin_library')
            self.book_status_dialog.initialize(self)
            self._log_location("{0} books".format(len(self.book_status_dialog.installed_books)))
            self.book_status_dialog.exec_()

            # Keep a copy of installed_books in case user reopens w/o disconnect
            self.installed_books = self.book_status_dialog.installed_books

            # Restore the Device view if active before MXD window launched
            if restore_to:
                self.gui.location_selected(restore_to)

            self.book_status_dialog = None

    # subclass override
    def shutting_down(self):
        self._log_location()

    def start_library_indexing(self):
        self._log_location()
        self._busy_panel_setup("Indexing calibre library…")
        self.library_scanner.start()

    def _busy_panel_setup(self, title, show_cancel=False):
        '''
        '''
        self._log_location()
        Application.setOverrideCursor(QCursor(Qt.WaitCursor))
        self.busy_window = MyBlockingBusy(self.gui, title, size=60, show_cancel=show_cancel)
        self.busy_window.start()
        self.busy_window.show()

    def _busy_panel_teardown(self):
        '''
        '''
        self._log_location()
        self.busy_window.stop()
        self.busy_window.accept()
        self.busy_window = None
        Application.restoreOverrideCursor()
