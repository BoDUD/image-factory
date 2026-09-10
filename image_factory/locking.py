"""OS locks are released on process exit; stale lock files are harmless."""
import os
from contextlib import contextmanager


@contextmanager
def exclusive(path):
    handle=open(path,'a+b')
    handle.seek(0,2)
    if not handle.tell():handle.write(b'0');handle.flush()
    handle.seek(0)
    locked=False
    try:
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError as e:raise RuntimeError('此成品目录已有任务运行，请勿同时启动两个批次') from e
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()
