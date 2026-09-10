import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from image_factory.app import Window


def test_demo_binding_and_recipe(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=Window();window.store=tmp_path/'state';window.store.mkdir()
    window.demo()
    assert len(window.rows)==3
    recipe,values=window.recipe()
    assert recipe['mode']=='template' and values[0]['customer']=='今今'
    window.save_mapping()
    assert window.config_path().exists()
    window.add_collection()
    assert len(window.collection)==1 and len(window.collection[0][1])==3
    window.close()
