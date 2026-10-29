"""Native macOS Keychain access. No secret-bearing subprocess, argv, or file."""
from __future__ import annotations

import ctypes as C
import sys
from contextlib import contextmanager


class KeychainAccessError(RuntimeError):
    def __init__(self, operation: str, status: int):
        self.status = status
        super().__init__(f"Keychain {operation} failed (OSStatus {status})")


class NativeKeychain:
    """SecItem access to the user's login keychain; missing != access denied."""

    def __init__(self):
        if sys.platform != "darwin":
            raise RuntimeError("macOS Keychain is available only on macOS")
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.sec = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
        pointer = C.c_void_p
        self._bind(self.cf, "CFStringCreateWithCString", pointer, [pointer, C.c_char_p, C.c_uint32])
        self._bind(self.cf, "CFDictionaryCreateMutable", pointer, [pointer, C.c_long, pointer, pointer])
        self._bind(self.cf, "CFDictionarySetValue", None, [pointer, pointer, pointer])
        self._bind(self.cf, "CFDataCreate", pointer, [pointer, pointer, C.c_long])
        self._bind(self.cf, "CFDataGetLength", C.c_long, [pointer])
        self._bind(self.cf, "CFDataGetBytePtr", pointer, [pointer])
        self._bind(self.cf, "CFRelease", None, [pointer])
        self._bind(self.sec, "SecItemCopyMatching", C.c_int32, [pointer, C.POINTER(pointer)])
        self._bind(self.sec, "SecItemAdd", C.c_int32, [pointer, C.POINTER(pointer)])
        self._bind(self.sec, "SecItemUpdate", C.c_int32, [pointer, pointer])
        self._bind(self.sec, "SecItemDelete", C.c_int32, [pointer])

    @staticmethod
    def _bind(library, name, restype, argtypes):
        fn = getattr(library, name)
        fn.restype, fn.argtypes = restype, argtypes

    def _constant(self, name):
        library = self.cf if name.startswith("kCF") else self.sec
        return C.c_void_p.in_dll(library, name).value

    def _set(self, dictionary, key, value):
        self.cf.CFDictionarySetValue(dictionary, self._constant(key), value)

    @contextmanager
    def _dictionary(self, fields):
        key_callbacks = C.addressof(C.c_byte.in_dll(self.cf, "kCFTypeDictionaryKeyCallBacks"))
        value_callbacks = C.addressof(C.c_byte.in_dll(self.cf, "kCFTypeDictionaryValueCallBacks"))
        dictionary = self.cf.CFDictionaryCreateMutable(None, 0, key_callbacks, value_callbacks)
        if not dictionary:
            raise MemoryError("cannot allocate Keychain query")
        try:
            for key, value in fields.items():
                if isinstance(value, bytes):
                    buffer = C.create_string_buffer(value)
                    obj = self.cf.CFDataCreate(None, buffer, len(value))
                else:
                    obj = self.cf.CFStringCreateWithCString(None, value.encode("utf-8"), 0x08000100)
                if not obj:
                    raise MemoryError("cannot allocate Keychain value")
                try:
                    self._set(dictionary, key, obj)
                finally:
                    self.cf.CFRelease(obj)
            yield dictionary
        finally:
            self.cf.CFRelease(dictionary)

    @contextmanager
    def _query(self, service, account):
        with self._dictionary({"kSecAttrService": service, "kSecAttrAccount": account}) as query:
            self._set(query, "kSecClass", self._constant("kSecClassGenericPassword"))
            yield query

    def get(self, service: str, account: str):
        result = C.c_void_p()
        with self._query(service, account) as query:
            self._set(query, "kSecReturnData", self._constant("kCFBooleanTrue"))
            self._set(query, "kSecMatchLimit", self._constant("kSecMatchLimitOne"))
            status = self.sec.SecItemCopyMatching(query, C.byref(result))
        if status == -25300:  # errSecItemNotFound only
            return None
        if status != 0:
            raise KeychainAccessError("read", status)
        try:
            length = self.cf.CFDataGetLength(result)
            return C.string_at(self.cf.CFDataGetBytePtr(result), length).decode("utf-8")
        finally:
            if result:
                self.cf.CFRelease(result)

    def save(self, service: str, account: str, value: str):
        encoded = value.encode("utf-8")
        with self._query(service, account) as query:
            with self._dictionary({"kSecValueData": encoded}) as attributes:
                status = self.sec.SecItemUpdate(query, attributes)
            if status == -25300:
                with self._dictionary({
                    "kSecAttrService": service, "kSecAttrAccount": account, "kSecValueData": encoded,
                }) as attributes:
                    self._set(attributes, "kSecClass", self._constant("kSecClassGenericPassword"))
                    status = self.sec.SecItemAdd(attributes, None)
        if status != 0:
            raise KeychainAccessError("write", status)

    def delete(self, service: str, account: str):
        with self._query(service, account) as query:
            status = self.sec.SecItemDelete(query)
        if status not in (0, -25300):
            raise KeychainAccessError("delete", status)
