"""One overlay process per Windows login session."""
import ctypes,sys

class InstanceGuard:
    def __init__(self,name='Local\\ChessLens.ScreenOverlay'):
        self.name=name; self.handle=None
    def acquire(self):
        if sys.platform!='win32': return True
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
        kernel.CreateMutexW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        ctypes.set_last_error(0)
        handle=kernel.CreateMutexW(None,False,self.name)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error()==183:
            kernel.CloseHandle(handle); return False
        self.handle=handle; return True
    def close(self):
        if self.handle:
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]; kernel.CloseHandle(self.handle); self.handle=None
