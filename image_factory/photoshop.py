"""COM runs in a subprocess. A timeout never kills the user's Photoshop."""
import json
import multiprocessing as mp
import sys
from pathlib import Path


class PhotoshopUncertain(RuntimeError):
    pass


def _host(pipe):
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            app = win32com.client.Dispatch("Photoshop.Application")
            script = Path(__file__).with_suffix(".jsx").read_text(encoding="utf-8")
            while True:
                request = pipe.recv()
                if request is None:
                    break
                try:
                    source = "var request = " + json.dumps(request, ensure_ascii=True) + ";\n" + script
                    pipe.send(json.loads(app.DoJavaScript(source)))
                except Exception as e:
                    pipe.send({"error": str(e)})
        finally:
            pythoncom.CoUninitialize()
    except Exception as e:
        pipe.send({"error": "无法连接 Photoshop，请安装并启动桌面 Photoshop。" + str(e)})
    finally:
        pipe.close()


class Photoshop:
    def __init__(self):
        self.process = None
        self.pipe = None

    def call(self, operation, timeout=120, **data):
        if sys.platform != "win32":
            raise RuntimeError("Photoshop 桥接目前只支持 Windows")
        if self.process is None:
            ctx = mp.get_context("spawn")
            self.pipe, child = ctx.Pipe()
            self.process = ctx.Process(target=_host, args=(child,), daemon=True)
            self.process.start()
            child.close()
        try:
            self.pipe.send(dict(operation=operation, **data))
            if not self.pipe.poll(timeout):
                raise PhotoshopUncertain("Photoshop 响应超时，批次已停止。请检查 Photoshop 和临时文件后再恢复；未关闭 Photoshop。")
            result = self.pipe.recv()
        except (EOFError, BrokenPipeError, OSError) as e:
            raise PhotoshopUncertain("Photoshop 连接中断，请检查处理状态后恢复") from e
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result

    def close(self):
        if self.process:
            try:
                self.pipe.send(None)
            except (OSError, EOFError):
                pass
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.terminate()  # Only our isolated COM helper.
                self.process.join(timeout=3)
            self.pipe.close()
            self.process = None
