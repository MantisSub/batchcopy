#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Copy files from multiple Insta360 Pro 2 memory cards to a common destination directory
"""

__author__ = "Axel Busch"
__copyright__ = "Copyright 2023, Xlvisuals Limited"
__license__ = "GPL-2.1"
__version__ = "0.0.6"
__email__ = "info@xlvisuals.com"

import os
import sys
import shutil
import signal
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog, messagebox, scrolledtext
from helpers import Helpers
from queue import Queue
from threading import Thread
from time import sleep, time


class ThreadedCopy:

    def __init__(self):
        self._stopping = False
        self._file_queue = Queue()
        self.total_file_count = 0
        self.copied_file_count = 0
        self.lock = threading.Lock()

    def _worker_func(self):
        while True:
            try:
                source, dest = self._file_queue.get()
                if source and dest and not self._stopping:
                    self.log(f"Copying {source}")
                    shutil.copy(source, dest, follow_symlinks=False)
                    with self.lock:
                        self.copied_file_count += 1
                else:
                    break
            except Exception as e:
                self.log(f"Error copying: {str(e)}")
            finally:
                self._file_queue.task_done()

    def put(self, source, dest):
        self._file_queue.put([source, dest])

    def start(self, max_threads=6):
        self._threads = []
        for i in range(max_threads):
            if not self._stopping:
                t = Thread(target=self._worker_func, daemon=True)
                if t:
                    t.start()
                    self._threads.append(t)
        return self._threads

    def stop(self):
        self._stopping = True
        if self._threads:
            for i in self._threads:
                # add one per thread
                self._file_queue.put((None, None))
            for t in self._threads:
                t.join(2)
        return True

    def wait(self):
        self._file_queue.join()
        return True

    def init(self, sources, target, startswith=("VID_", "PIC_"), log_callback=None):
        if log_callback:
            self.log = log_callback
        else:
            self.log = print

        self.log("Collecting source subfolders")
        folders = []
        for s in sources:
            for p in startswith:
                subdirs = Helpers.get_subdirs(s, p)
                for d in subdirs:
                    if d not in folders:
                        folders.append(d)

        self.log("Creating target folders")
        for f in folders:
            try:
                p = os.path.abspath(os.path.join(target, f))
                if not os.path.exists(p):
                    os.mkdir(p)
            except FileExistsError:
                pass

        self.log("Preparing files")
        for f in folders:
            for s in sources:
                try:
                    source_filenames = []
                    source = os.path.abspath(os.path.join(s, f))
                    destination = os.path.abspath(os.path.join(target, f)) + os.path.sep
                    try:
                        # program the loop explicit in case some recording subfolders are missing from some cards
                        for sf in os.listdir(source):
                            sf_path = os.path.join(source, sf)
                            if os.path.isfile(sf_path):
                                # only filename, not path
                                source_filenames.append(sf)
                    except FileNotFoundError as e:
                        self.log(f"Warning. Folder '{source}' is missing.")
                    for filename in source_filenames:
                        source_file = os.path.abspath(os.path.join(source, filename))
                        destination_file = os.path.abspath(os.path.join(destination, filename))
                        try:
                            if os.path.exists(destination_file):
                                if os.path.getsize(destination_file) == os.path.getsize(source_file):
                                    self.log(f"Skipping '{source_file}': destination '{destination_file}' already exists")
                                    continue
                                else:
                                    # file sizes don't match -> delete destination before copying
                                    self.log("Deleting '{}'".format(destination_file))
                                    os.remove(destination_file)
                            self.put(source_file, destination)
                            self.total_file_count += 1
                        except Exception as e:
                            self.log("Error copying '{}': {}".format(source_file, e))
                except Exception as e:
                    self.log(f"Error preparing copy for {s}: {str(e)}")
        self.log(f"Prepared {self.total_file_count} files")



class BatchCopy():

    def __init__(self):
        # self.button_cancel = None
        self.button_start = None
        self.text_area = None

        self.themes_path = os.path.abspath('awthemes-10.4.0')
        self.theme_names = ['awdark', 'awlight']
        self.iconbitmap = None
        self.editor_width = 80
        self.button_width = 25
        self.source_listbox = None
        self.source_button = None
        self.target_button = None
        self.target_entry = None
        self.target_dir_value = None

        self.copying = False
        self._lock = threading.Lock()
        self._unprocessed_logs = []
        self._can_quit = True
        self._threadedcopy = None
        self._copy_thread = None

    def init(self):
        self._init_tk()
        self._init_ttk()
        if sys.platform == "darwin":
            self.editor_width = int(self.editor_width/2)
            self.button_width = int(self.button_width/2)

    def _init_tk(self):
        # Create root element and load and set theme
        self.root = tk.Tk()
        self.root.title("Batch Copy")
        if self.iconbitmap and os.path.isfile(self.iconbitmap):
            self.root.iconbitmap(self.iconbitmap)
        self.root.resizable(False, False)

        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=False)
        filemenu.add_command(label="About ...", command=self._on_about)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self._on_quit)
        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)

        self.root.bind("<<log_callback>>", self._on_log_callback)
        self.root.bind("<<done_callback>>", self._on_done_callback)
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)
        self.target_dir_value = tk.StringVar()

    def _init_ttk(self):
        # Load and set theme
        if not self.root:
            self._init_tk()
        self.root.tk.call('lappend', 'auto_path', self.themes_path)
        for name in self.theme_names:
            self.root.tk.call('package', 'require', name)
        self.style = ttk.Style(self.root)
        self.style.theme_use(self.theme_names[0])

    def set_theme(self, index):
        if index >= len(self.theme_names):
            index = 0
        self.style.theme_use(self.theme_names[index])
        self.root.configure(bg=self.style.lookup('TFrame', 'background'))
        self.source_listbox.configure(bg='white', fg='black')

    def toggle_theme(self):
        try:
            cur_index = self.theme_names.index(self.style.theme_use())
        except:
            cur_index = 0
        self.set_theme(cur_index + 1)

    def _get_list_entries(self):
        return [self.source_listbox.get(i) for i in range(self.source_listbox.size())]

    def _on_select_source_dir(self):
        sdir = filedialog.askdirectory()
        if sdir:
            if sdir.endswith('/') or sdir.endswith('\\'):
                sdir = sdir[:-1]
                if not sys.platform == 'win32 and not sdir':
                    sdir = os.path.sep
        if sdir:
            tdir = self.target_dir_value.get()
            if sdir in self._get_list_entries():
                messagebox.showerror(title="Error", message="This source has already been selected.")
                return
            elif tdir.startswith(sdir):
                messagebox.showerror(title="Error", message="Target directory must not be same as or below source directory.")
                return
            else:
                recordings = Helpers.get_subdirs(sdir, "VID_")
                # check if it has recordings subdirs, if not show warning.
                self.source_listbox.insert(self.source_listbox.size(), sdir)
                if not recordings:
                    recordings = Helpers.get_subdirs(sdir, "PIC_")
                    if not recordings:
                        messagebox.showwarning(title="Warning", message="The selected directory has no VID_ or PIC_ subdirectories.")

    def _on_remove_source_dir(self):
        try:
            [index] = self.source_listbox.curselection()
        except ValueError:
            return
        self.source_listbox.delete(index)
        self.source_listbox.select_set(max(index, self.source_listbox.size() - 1))

    def _on_select_target_dir(self):
        idir = self.target_dir_value.get() or None
        tdir = filedialog.askdirectory(initialdir=idir)
        if tdir:
            if tdir.endswith('/') or tdir.endswith('\\'):
                tdir = tdir[:-1]
                if not sys.platform == 'win32 and not tdir':
                    tdir = os.path.sep
        if tdir:
            source_dirs = self._get_list_entries()
            for sdir in source_dirs:
                if tdir.startswith(sdir):
                    messagebox.showerror(title="Error", message="Target directory must not be same as or below source directory.")
                    return
            self.target_dir_value.set(tdir)
            if not os.path.isdir(tdir):
                messagebox.showwarning(title="Warning", message="No valid target directory selected.")

    def _on_find_cards(self):
        file = ".pro_suc"
        drives = Helpers.get_drives()
        all_cards = []
        new_cards = []
        for fdir in drives:
            try:
                if fdir.endswith('/') or fdir.endswith('\\'):
                    fdir = fdir[:-1]
                proc_file = os.path.join(fdir, file)
                if os.path.isfile(proc_file):
                    all_cards.append(fdir)
                    if fdir not in self._get_list_entries():
                        new_cards.append(fdir)
            except:
                pass
        if new_cards:
            for card in new_cards:
                self.source_listbox.insert(self.source_listbox.size(), card)
        if not all_cards:
            messagebox.showwarning(title="Info", message="No new Pro 2 cards found.")

    def _on_about(self):
        title = 'About Batch Copy'
        message = (
            'Batch Copy for Insta360 Pro 2 by Axel Busch\n'
            'Version ' + __version__ + '\n'
            '\n'
            'Provided by Mantis Sub underwater housing for Pro 2\n'
            'Visit https://www.mantis-sub.com/'
        )
        disclaimer = (
            'This program is distributed in the hope that it will be useful, '
            'but WITHOUT ANY WARRANTY; without even the implied warranty of '
            'MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU '
            'Lesser General Public License for more details.'
        )
        messagebox.showinfo(title=title, message=message, detail=disclaimer)

    def _on_quit(self):
        try:
            self.root.quit()
        except:
            pass
        if self.copying or self._threadedcopy:
            # Force exit and stopping of copy threads
            if sys.platform == "darwin":
                os.kill(os.getpid(), signal.SIGKILL)
            else:
                os._exit(0)
        else:
            # Exit gently
            sys.exit(0)

    def _clear_log(self):
        self.text_area.configure(state=tk.NORMAL)
        self.text_area.delete('1.0', tk.END)
        self.text_area.configure(state=tk.DISABLED)

    def _on_erase_source_dir(self):
        self._clear_log()
        sources_dirs = self._get_list_entries()
        system_root_dir = Helpers.system_root_path()
        if sources_dirs:
            self.log(f"Erasing all files except Insta360\nspeed test success indicator:")
            self.log("")
            answer = messagebox.askyesno("Confirm", f"Are you sure you want to erase all {len(sources_dirs)} cards? This action can't be undone.")
            if answer:
                for source in sources_dirs:
                    try:
                        if not source:
                            self.log(f"Error: empty source.")
                        elif source == system_root_dir:
                            self.log(f"Error erasing '{source}': path is system root.")
                        else:
                            Helpers.erase_all(source, ".pro_suc")
                            self.log(f"Erased all files in '{source}'.")
                            os.mkdir(os.path.join(source, "DCIM"))
                            os.mkdir(os.path.join(source, "EVENT"))

                    except Exception as e:
                        return
            self.log("Done.")
        else:
            messagebox.showerror(title="Error", message="No cards added.")

    def _on_start(self):
        try:
            self._clear_log()
            self.button_start.config(state=tk.DISABLED)
            # self.button_cancel.config(state=tk.NORMAL)

            sources_dirs = self._get_list_entries()
            target_dir = self.target_dir_value.get()
            if not sources_dirs:
                messagebox.showerror(title="Error", message="No source selected.")
                return

            if not target_dir:
                messagebox.showerror(title="Error", message="No target folder selected.")
                return

            if not os.path.exists(target_dir):
                try:
                    os.mkdir(target_dir)
                except:
                    pass

            if not os.path.exists(target_dir):
                messagebox.showerror(title="Error", message="Target folder does not exist.")
                return

            space_required_gb = round(Helpers.get_used_space(sources_dirs) / 1073741824, 1)
            space_free_gb = round(Helpers.get_free_space(target_dir) / 1073741824, 1)
            if space_free_gb <= space_required_gb:
                messagebox.showerror(title="Error", message=f"Not enough space on target.\n"
                                                            f"Required: {space_required_gb} GB\n"
                                                            f"Available: {space_free_gb} GB.")
                return
            self.log_callback(f"Copying {space_required_gb} GB")

            def start_copy():
                self._threadedcopy = ThreadedCopy()
                self._threadedcopy.init(sources_dirs, target_dir, ("VID_", "PIC_"), self.log_callback)
                if self._threadedcopy.total_file_count > 0:
                    start = time()
                    self._threadedcopy.start(len(sources_dirs))
                    self._threadedcopy.wait()
                    self._threadedcopy.stop()
                    end = time()
                    duration = int(end - start)+1
                    self.log_callback(f"\n++ Finished copying {self._threadedcopy.copied_file_count} of {self._threadedcopy.total_file_count} files in {duration}s. ++\n\n")
                else:
                    self.log_callback("\n++ Finished. Nothing to copy. ++\n\n")
                self.done_callback()

            self._copy_thread = threading.Thread(target=start_copy)
            if self._copy_thread:
                self.copying = True
                self._copy_thread.start()
                self._can_quit = False

        except Exception as e:
            self.log_callback(f"Error: {str(e)}")

        finally:
            if not self.copying:
                self.button_start.config(state=tk.NORMAL)
                # self.button_cancel.config(state=tk.DISABLED)

    def done_callback(self):
        self.root.event_generate("<<done_callback>>")

    def _on_done_callback(self, event=None):
        if self._is_copy_thread_alive():
            self.root.update_idletasks()
            self.root.update()
            sleep(0.1)
        if self._copy_thread:
            self._copy_thread.join(1)
            self._copy_thread = None
        self._stitcher = None
        self._can_quit = True
        if self.button_start:
            self.button_start.config(state=tk.NORMAL)
            # self.button_cancel.config(state=tk.DISABLED)

    def _is_copy_thread_alive(self):
        alive = False
        if self._copy_thread:
            alive = self._copy_thread.is_alive()
            if not alive:
                self._copy_thread.join(2)
                self._copy_thread = None
        return alive

    def log_callback(self, text):
        try:
            # It's not safe to call tkinter directly from a different thread.
            # But we can send store the data temporarily and send a message to tkinter to process it.
            try:
                self._lock.acquire()
                self._unprocessed_logs.append(text)
            finally:
                self._lock.release()
            self.root.event_generate("<<log_callback>>")
        except Exception as e:
            print("Error in log_callback(): ", str(e))

            # We're in trouble. Probably user quit the program while copying. Force exit to close all threads.
            print("Exiting")
            self._on_quit()


    def _on_log_callback(self, event=None):
        if self.text_area:
            try:
                self._lock.acquire()
                for text in self._unprocessed_logs:
                    self.log(text)
                self._unprocessed_logs.clear()
            finally:
                self._lock.release()

    def log(self, text):
        # Only call from main gui thread
        try:
            if self.text_area:
                self.text_area.configure(state=tk.NORMAL)
                if text != ".":
                    self.text_area.insert(tk.END, "\n")
                self.text_area.insert(tk.END, text)
                self.text_area.configure(state=tk.DISABLED)
        except Exception as e:
            print("Error in log(): ", str(e))
            print(text)

    def show(self):
        self.root.columnconfigure(0, minsize=50)
        self.root.columnconfigure(1, minsize=50)
        self.root.columnconfigure(2, minsize=50)
        self.root.columnconfigure(3, minsize=50)
        self.root.columnconfigure(4, minsize=50)
        self.root.rowconfigure(0, weight=1)

        row = 0
        label1 = ttk.Label(self.root, text='Copy recordings from multiple Insta360 Pro 2 memory cards to a common target folder.', font='bold')
        label1.grid(row=row, column=0, columnspan=5, padx=50, pady=(20,5), sticky="w")

        row += 1
        label2 = ttk.Label(self.root, text='Only PIC_xxx and VID_xxx folders are copied. Existing folders with the same name are merged. ')
        label2.grid(row=row, column=0, columnspan=5, padx=50, pady=(5,20), sticky="w")

        row += 1
        ttk.Label(self.root, text="Sources", anchor='e').grid(row=row, column=0, padx=(50,5), pady=2, sticky="en")
        self.source_listbox = tk.Listbox(self.root, selectmode=tk.SINGLE, height=8)
        self.source_listbox.grid(row=row, column=1, columnspan=3, rowspan=4, padx=2, pady=2, sticky="ewns")
        self.source_button = ttk.Button(self.root, text='Find cards', command=self._on_find_cards, width=self.button_width)
        self.source_button.grid(row=row, column=4, padx=(5,50), pady=5, sticky="wn")
        row += 1
        self.source_button = ttk.Button(self.root, text='Choose card', command=self._on_select_source_dir, width=self.button_width)
        self.source_button.grid(row=row, column=4, padx=(5,50), pady=5, sticky="wn")
        row += 1
        self.source_button = ttk.Button(self.root, text='Remove selected', command=self._on_remove_source_dir, width=self.button_width)
        self.source_button.grid(row=row, column=4, padx=(5,50), pady=5, sticky="wn")
        row += 1
        self.erase_button = ttk.Button(self.root, text='Erase cards', command=self._on_erase_source_dir, width=self.button_width)
        self.erase_button.grid(row=row, column=4, padx=(5,50), pady=5, sticky="wn")
        row += 1
        ttk.Label(self.root, text="").grid(row=row, column=0, padx=2, pady=5, sticky="wns")

        row += 1
        ttk.Label(self.root, text="Target", anchor='e').grid(row=row, column=0, padx=(50,5), pady=(10,2), sticky="e")
        self.target_entry = tk.Entry(self.root, width=self.editor_width, textvariable=self.target_dir_value)
        self.target_entry.grid(row=row, column=1, columnspan=3, padx=2, pady=(10,2), sticky="ew")
        self.target_button = ttk.Button(self.root, text='Choose folder', command=self._on_select_target_dir, width=self.button_width)
        self.target_button.grid(row=row, column=4, padx=(5,50), pady=(10,2), sticky="w")

        row += 1
        ttk.Label(self.root, text="Progress", anchor='e').grid(row=row, column=0, padx=(50,5), pady=(10,2), sticky="ne")
        self.text_area = scrolledtext.ScrolledText(self.root, wrap=tk.NONE, height=12, width=50, bg='grey', fg='white')
        self.text_area.config(state=tk.DISABLED)
        self.text_area.grid(row=row, column=1, columnspan=3, padx=2, pady=(10,2), sticky="ew")

        row += 1
        # self.button_cancel = ttk.Button(text='Cancel', command=self._on_cancel, width=self.button_width)
        # self.button_cancel.grid(row=row, column=0, columnspan=2, padx=(50, 0), pady=(20,50), sticky="w")
        self.button_start = ttk.Button(text='Start', command=self._on_start, width=self.button_width)
        self.button_start.grid(row=row, column=3, columnspan=2, padx=(0, 50), pady=(15,50), sticky="e")

        self.button_start.config(state=tk.NORMAL)
        # self.button_cancel.config(state=tk.DISABLED)

        row += 1
        label1 = ttk.Label(self.root, text='Provided by Mantis Sub underwater housing for Insta360 Pro/Pro 2. See File -> About for details.')
        label1.grid(row=row, column=0, columnspan=5, padx=50, pady=(2,20), sticky="w")

        # update theme
        self.set_theme(0)

        # run blocking main loop
        self.root.mainloop()
        return 0


def run():
    b = BatchCopy()
    b.init()
    b.show()


if __name__ == "__main__":
    run()
