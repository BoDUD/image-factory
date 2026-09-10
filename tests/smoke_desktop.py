"""Run a real QThread batch through the desktop window, then capture its UI."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from image_factory.app import Window,STYLE,configure_fonts

app=QApplication([]);configure_fonts(app);app.setStyleSheet(STYLE)
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
w=Window();w.store=root/'state';w.store.mkdir(exist_ok=True);w.output.setText(str(root/'output'))
w.demo();w.show();w.start_templates()
counter=0
def poll():
    global counter
    counter+=1
    if w.worker and w.worker.isRunning():
        if counter>300:raise RuntimeError('Smoke timeout')
        return
    assert w.last_batch and all(x[3]=='succeeded' for x in w.last_batch['items'])
    w.grab().save(str(root/'desktop.png'))
    timer.stop();w.close();app.quit()
timer=QTimer();timer.timeout.connect(poll);timer.start(100)
app.exec()
print('Desktop end-to-end passed')
