# coding=utf-8
# pynput
# Copyright (C) 2015-2019 Moses Palmér
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
"""
Utility functions and classes for the *win32* backend.
"""

# pylint: disable=C0103
# We want to make it obvious how structs are related

# pylint: disable=R0903
# This module contains a number of structs

import contextlib
import ctypes
import itertools
import threading

from ctypes import (
    windll,
    wintypes)

import six

from . import AbstractListener, win32_vks as VK


# LPDWORD is not in ctypes.wintypes on Python 2
if not hasattr(wintypes, 'LPDWORD'):
    wintypes.LPDWORD = ctypes.POINTER(wintypes.DWORD)


class MOUSEINPUT(ctypes.Structure):
    """Contains information about a simulated mouse event.
    """
    MOVE = 0x0001
    LEFTDOWN = 0x0002
    LEFTUP = 0x0004
    RIGHTDOWN = 0x0008
    RIGHTUP = 0x0010
    MIDDLEDOWN = 0x0020
    MIDDLEUP = 0x0040
    XDOWN = 0x0080
    XUP = 0x0100
    WHEEL = 0x0800
    HWHEEL = 0x1000
    ABSOLUTE = 0x8000

    XBUTTON1 = 0x0001
    XBUTTON2 = 0x0002

    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    """Contains information about a simulated keyboard event.
    """
    EXTENDEDKEY = 0x0001
    KEYUP = 0x0002
    SCANCODE = 0x0008
    UNICODE = 0x0004

    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    """Contains information about a simulated message generated by an input
    device other than a keyboard or mouse.
    """
    _fields_ = [
        ('uMsg', wintypes.DWORD),
        ('wParamL', wintypes.WORD),
        ('wParamH', wintypes.WORD)]


class INPUT_union(ctypes.Union):
    """Represents the union of input types in :class:`INPUT`.
    """
    _fields_ = [
        ('mi', MOUSEINPUT),
        ('ki', KEYBDINPUT),
        ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    """Used by :attr:`SendInput` to store information for synthesizing input
    events such as keystrokes, mouse movement, and mouse clicks.
    """
    MOUSE = 0
    KEYBOARD = 1
    HARDWARE = 2

    _fields_ = [
        ('type', wintypes.DWORD),
        ('value', INPUT_union)]


LPINPUT = ctypes.POINTER(INPUT)

VkKeyScan = windll.user32.VkKeyScanW
VkKeyScan.argtypes = (
    wintypes.WCHAR,)

SendInput = windll.user32.SendInput
SendInput.argtypes = (
    wintypes.UINT,
    LPINPUT,
    ctypes.c_int)

GetCurrentThreadId = windll.kernel32.GetCurrentThreadId
GetCurrentThreadId.restype = wintypes.DWORD


class MessageLoop(object):
    """A class representing a message loop.
    """
    #: The message that signals this loop to terminate
    WM_STOP = 0x0401

    _LPMSG = ctypes.POINTER(wintypes.MSG)

    _GetMessage = windll.user32.GetMessageW
    _GetMessage.argtypes = (
        _LPMSG,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT)
    _PeekMessage = windll.user32.PeekMessageW
    _PeekMessage.argtypes = (
        _LPMSG,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT)
    _PostThreadMessage = windll.user32.PostThreadMessageW
    _PostThreadMessage.argtypes = (
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM)

    PM_NOREMOVE = 0

    def __init__(self):
        self._threadid = None
        self._event = threading.Event()
        self.thread = None

    def __iter__(self):
        """Initialises the message loop and yields all messages until
        :meth:`stop` is called.

        :raises AssertionError: if :meth:`start` has not been called
        """
        assert self._threadid is not None

        try:
            # Pump messages until WM_STOP
            while True:
                msg = wintypes.MSG()
                lpmsg = ctypes.byref(msg)
                r = self._GetMessage(lpmsg, None, 0, 0)
                if r <= 0 or msg.message == self.WM_STOP:
                    break
                else:
                    yield msg

        finally:
            self._threadid = None
            self.thread = None

    def start(self):
        """Starts the message loop.

        This method must be called before iterating over messages, and it must
        be called from the same thread.
        """
        self._threadid = GetCurrentThreadId()
        self.thread = threading.current_thread()

        # Create the message loop
        msg = wintypes.MSG()
        lpmsg = ctypes.byref(msg)
        self._PeekMessage(lpmsg, None, 0x0400, 0x0400, self.PM_NOREMOVE)

        # Set the event to signal to other threads that the loop is created
        self._event.set()

    def stop(self):
        """Stops the message loop.
        """
        self._event.wait()
        if self._threadid:
            self.post(self.WM_STOP, 0, 0)

    def post(self, msg, wparam, lparam):
        """Posts a message to this message loop.

        :param ctypes.wintypes.UINT msg: The message.

        :param ctypes.wintypes.WPARAM wparam: The value of ``wParam``.

        :param ctypes.wintypes.LPARAM lparam: The value of ``lParam``.
        """
        self._PostThreadMessage(self._threadid, msg, wparam, lparam)


class SystemHook(object):
    """A class to handle Windows hooks.
    """
    #: The hook action value for actions we should check
    HC_ACTION = 0

    _HOOKPROC = ctypes.WINFUNCTYPE(
        wintypes.LPARAM,
        ctypes.c_int32, wintypes.WPARAM, wintypes.LPARAM)

    _SetWindowsHookEx = windll.user32.SetWindowsHookExW
    _SetWindowsHookEx.argtypes = (
        ctypes.c_int,
        _HOOKPROC,
        wintypes.HINSTANCE,
        wintypes.DWORD)
    _UnhookWindowsHookEx = windll.user32.UnhookWindowsHookEx
    _UnhookWindowsHookEx.argtypes = (
        wintypes.HHOOK,)
    _CallNextHookEx = windll.user32.CallNextHookEx
    _CallNextHookEx.argtypes = (
        wintypes.HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM)

    #: The registered hook procedures
    _HOOKS = {}

    class SuppressException(Exception):
        """An exception raised by a hook callback to suppress further
        propagation of events.
        """
        pass

    def __init__(self, hook_id, on_hook=lambda code, msg, lpdata: None):
        self.hook_id = hook_id
        self.on_hook = on_hook
        self._hook = None

    def __enter__(self):
        key = threading.current_thread().ident
        assert key not in self._HOOKS

        # Add ourself to lookup table and install the hook
        self._HOOKS[key] = self
        self._hook = self._SetWindowsHookEx(
            self.hook_id,
            self._handler,
            None,
            0)

        return self

    def __exit__(self, exc_type, value, traceback):
        key = threading.current_thread().ident
        assert key in self._HOOKS

        if self._hook is not None:
            # Uninstall the hook and remove ourself from lookup table
            self._UnhookWindowsHookEx(self._hook)
            del self._HOOKS[key]

    @staticmethod
    @_HOOKPROC
    def _handler(code, msg, lpdata):
        key = threading.current_thread().ident
        self = SystemHook._HOOKS.get(key, None)
        if self:
            # pylint: disable=W0702; we want to silence errors
            try:
                self.on_hook(code, msg, lpdata)
            except self.SuppressException:
                # Return non-zero to stop event propagation
                return 1
            except:
                # Ignore any errors
                pass
            # pylint: enable=W0702
            return SystemHook._CallNextHookEx(0, code, msg, lpdata)


class ListenerMixin(object):
    """A mixin for *win32* event listeners.

    Subclasses should set a value for :attr:`_EVENTS` and implement
    :meth:`_handle`.

    Subclasses must also be decorated with a decorator compatible with
    :meth:`pynput._util.NotifierMixin._receiver` or implement the method
    ``_receive()``.
    """
    #: The Windows hook ID for the events to capture.
    _EVENTS = None

    #: The window message used to signal that an even should be handled.
    _WM_PROCESS = 0x410

    #: Additional window messages to propagate to the subclass handler.
    _WM_NOTIFICATIONS = []

    def suppress_event(self):
        """Causes the currently filtered event to be suppressed.

        This has a system wide effect and will generally result in no
        applications receiving the event.

        This method will raise an undefined exception.
        """
        raise SystemHook.SuppressException()

    def _run(self):
        self._message_loop = MessageLoop()
        with self._receive():
            self._mark_ready()
            self._message_loop.start()

            # pylint: disable=W0702; we want to silence errors
            try:
                with SystemHook(self._EVENTS, self._handler):
                    # Just pump messages
                    for msg in self._message_loop:
                        if not self.running:
                            break
                        if msg.message == self._WM_PROCESS:
                            self._process(msg.wParam, msg.lParam)
                        elif msg.message in self._WM_NOTIFICATIONS:
                            self._on_notification(
                                msg.message, msg.wParam, msg.lParam)
            except:
                # This exception will have been passed to the main thread
                pass
            # pylint: enable=W0702

    def _stop_platform(self):
        try:
            self._message_loop.stop()
        except AttributeError:
            # The loop may not have been created
            pass

    @AbstractListener._emitter
    def _handler(self, code, msg, lpdata):
        """The callback registered with *Windows* for events.

        This method will post the message :attr:`_WM_HANDLE` to the message loop
        started with this listener using :meth:`MessageLoop.post`. The
        parameters are retrieved with a call to :meth:`_handle`.
        """
        try:
            converted = self._convert(code, msg, lpdata)
            if converted is not None:
                self._message_loop.post(self._WM_PROCESS, *converted)
        except NotImplementedError:
            self._handle(code, msg, lpdata)

        if self.suppress:
            self.suppress_event()

    def _convert(self, code, msg, lpdata):
        """The device specific callback handler.

        This method converts a low-level message and data to a
        ``WPARAM`` / ``LPARAM`` pair.
        """
        raise NotImplementedError()

    def _process(self, wparam, lparam):
        """The device specific callback handler.

        This method performs the actual dispatching of events.
        """
        raise NotImplementedError()

    def _handle(self, code, msg, lpdata):
        """The device specific callback handler.

        This method calls the appropriate callback registered when this
        listener was created based on the event.

        This method is only called if :meth:`_convert` is not implemented.
        """
        raise NotImplementedError()

    def _on_notification(self, code, wparam, lparam):
        """An additional notification handler.

        This method will be called for every message in
        :attr:`_WM_NOTIFICATIONS`.
        """
        raise NotImplementedError()


class KeyTranslator(object):
    """A class to translate virtual key codes to characters.
    """
    _GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
    _GetAsyncKeyState.argtypes = (
        ctypes.c_int,)
    _GetKeyboardLayout = ctypes.windll.user32.GetKeyboardLayout
    _GetKeyboardLayout.argtypes = (
        wintypes.DWORD,)
    _GetKeyboardState = ctypes.windll.user32.GetKeyboardState
    _GetKeyboardState.argtypes = (
        ctypes.c_voidp,)
    _GetKeyState = ctypes.windll.user32.GetAsyncKeyState
    _GetKeyState.argtypes = (
        ctypes.c_int,)
    _MapVirtualKeyEx = ctypes.windll.user32.MapVirtualKeyExW
    _MapVirtualKeyEx.argtypes = (
        wintypes.UINT,
        wintypes.UINT,
        wintypes.HKL)
    _ToUnicodeEx = ctypes.windll.user32.ToUnicodeEx
    _ToUnicodeEx.argtypes = (
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_voidp,
        ctypes.c_voidp,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.HKL)

    _MAPVK_VK_TO_VSC = 0
    _MAPVK_VSC_TO_VK = 1
    _MAPVK_VK_TO_CHAR = 2

    def __init__(self):
        self.update_layout()

    def __call__(self, vk, is_press):
        """Converts a virtual key code to a string.

        :param int vk: The virtual key code.

        :param bool is_press: Whether this is a press.

        :return: parameters suitable for the :class:`pynput.keyboard.KeyCode`
            constructor

        :raises OSError: if a call to any *win32* function fails
        """
        # Get a string representation of the key
        layout_data = self._layout_data[self._modifier_state()]
        scan = self._to_scan(vk, self._layout)
        character, is_dead = layout_data[scan]

        return {
            'char': character,
            'is_dead': is_dead,
            'vk': vk,
            '_scan': scan}

    def update_layout(self):
        """Updates the cached layout data.
        """
        self._layout, self._layout_data = self._generate_layout()

    def char_from_scan(self, scan):
        """Translates a scan code to a character, if possible.

        :param int scan: The scan code to translate.

        :return: maybe a character
        :rtype: str or None
        """
        return self._layout_data[(False, False, False)][scan][0]

    def _generate_layout(self):
        """Generates the keyboard layout.

        This method will call ``ToUnicodeEx``, which modifies kernel buffers,
        so it must *not* be called from the keyboard hook.

        The return value is the tuple ``(layout_handle, layout_data)``, where
        ``layout_data`` is a mapping from the tuple ``(shift, ctrl, alt)`` to
        an array indexed by scan code containing the data
        ``(character, is_dead)``, and ``layout_handle`` is the handle of the
        layout.

        :return: a composite layout
        """
        layout_data = {}

        state = (ctypes.c_ubyte * 255)()
        with self._thread_input() as active_thread:
            layout = self._GetKeyboardLayout(active_thread)
        vks = [
            self._to_vk(scan, layout)
            for scan in range(len(state))]

        for shift, ctrl, alt in itertools.product(
                (False, True), (False, True), (False, True)):
            current = [(None, False)] * len(state)
            layout_data[(shift, ctrl, alt)] = current

            # Update the keyboard state based on the modifier state
            state[VK.SHIFT] = 0x80 if shift else 0x00
            state[VK.CONTROL] = 0x80 if ctrl else 0x00
            state[VK.MENU] = 0x80 if alt else 0x00

            # For each virtual key code...
            out = (ctypes.wintypes.WCHAR * 5)()
            for (scan, vk) in enumerate(vks):
                # ...translate it to a unicode character
                count = self._ToUnicodeEx(
                    vk, scan, ctypes.byref(state), ctypes.byref(out),
                    len(out), 0, layout)

                # Cache the result if a key is mapped
                if count != 0:
                    character = out[0]
                    is_dead = count < 0
                    current[scan] = (character, is_dead)

                    # If the key is dead, flush the keyboard state
                    if is_dead:
                        self._ToUnicodeEx(
                            VK.DECIMAL, vks[VK.DECIMAL], ctypes.byref(state),
                            ctypes.byref(out), len(out), 0, layout)

        return (layout, layout_data)

    def _to_scan(self, vk, layout):
        """Retrieves the scan code for a virtual key code.

        :param int vk: The virtual key code.

        :param layout: The keyboard layout.

        :return: the scan code
        """
        return self._MapVirtualKeyEx(
            vk, self._MAPVK_VK_TO_VSC, layout)

    def _to_vk(self, scan, layout):
        """Retrieves the virtual key code for a scan code.

        :param int vscan: The scan code.

        :param layout: The keyboard layout.

        :return: the virtual key code
        """
        return self._MapVirtualKeyEx(
            scan, self._MAPVK_VSC_TO_VK, layout)

    def _modifier_state(self):
        """Returns a key into :attr:`_layout_data` for the current modifier
        state.

        :return: the current modifier state
        """
        shift = bool(self._GetAsyncKeyState(VK.SHIFT))
        ctrl = bool(self._GetAsyncKeyState(VK.CONTROL))
        alt = bool(self._GetAsyncKeyState(VK.MENU))
        return (shift, ctrl, alt)

    @contextlib.contextmanager
    def _thread_input(self):
        """Yields the current thread ID.
        """
        yield GetCurrentThreadId()
