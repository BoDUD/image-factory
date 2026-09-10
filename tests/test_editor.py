import copy
import json
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PIL import Image
from PySide6.QtCore import QPointF,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from image_factory.editor import PlacementCanvas,WatermarkEditor,TemplateLayoutEditor
from image_factory import imaging
from image_factory.demo import create_demo


@pytest.fixture
def qt():
    app=QApplication.instance() or QApplication([])
    yield app


def drag(canvas,start,end):
    QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=canvas.to_view(QPointF(*start)).toPoint())
    QTest.mouseMove(canvas,canvas.to_view(QPointF(*end)).toPoint())
    QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=canvas.to_view(QPointF(*end)).toPoint())


def test_drag_source_coordinates_and_resize(qt):
    canvas=PlacementCanvas(Image.new('RGBA',(400,300)),[30,30,80,40]);canvas.resize(800,500);canvas.show();qt.processEvents()
    drag(canvas,(60,50),(100,80))
    assert canvas.box.x()==pytest.approx(70,abs=1)
    assert canvas.box.y()==pytest.approx(60,abs=1)
    before=canvas.box.width();br=canvas.box.bottomRight()
    drag(canvas,(br.x(),br.y()),(br.x()+40,br.y()+20))
    assert canvas.box.width()==pytest.approx(before+40,abs=1)
    assert canvas.box.width()/canvas.box.height()==pytest.approx(2)
    canvas.close()


def test_editor_export_and_cancel(qt,tmp_path):
    base=Image.new('RGBA',(400,300),'white');overlay=Image.new('RGBA',(80,40),'red')
    options={'scale':.2,'opacity':1,'position':'top-left','tile':False}
    original=copy.deepcopy(options);editor=WatermarkEditor(base,overlay,options);editor.show();qt.processEvents()
    drag(editor.canvas,(60,50),(120,110));editor.accept_checked()
    output=tmp_path/'export.png';imaging.watermark(base,overlay,**editor.options).save(output)
    assert Image.open(output).tobytes()==editor.rendered().tobytes()
    assert editor.options['offset']==pytest.approx([.225,.3],abs=.004)
    scaled=imaging.watermark(Image.new('RGBA',(800,600),'white'),overlay,**editor.options)
    assert scaled.getpixel((190,190))[:3]==(255,0,0)
    assert options==original
    editor.reject();assert options==original


def test_template_save_new_preserves_source_and_assets(qt,tmp_path):
    create_demo(tmp_path);source=tmp_path/'greeting.json'
    background=tmp_path/'background.png';Image.new('RGBA',(900,900),'yellow').save(background)
    spec=json.loads(source.read_text());spec['background_image']='background.png';source.write_text(json.dumps(spec),encoding='utf-8')
    original=source.read_bytes();values={'customer':'Alice','order_id':'001'}
    editor=TemplateLayoutEditor(source,values);editor.show();qt.processEvents()
    drag(editor.canvas,(300,370),(350,410));assert editor.spec['text'][0]['box'][0]==pytest.approx(130,abs=2)
    dest=tmp_path/'elsewhere'/'edited.json';dest.parent.mkdir();editor.save_to(dest)
    assert source.read_bytes()==original
    assert Path(json.loads(dest.read_text())['background_image'])==background.resolve()
    assert imaging.render_template(dest,values).tobytes()==imaging.render_spec(editor.portable_spec(),values,source).tobytes()
    with pytest.raises(ValueError,match='覆盖'):editor.save_to(source)
    editor.spec['text'][0]['box']=[0,0,1,1]
    with pytest.raises(ValueError,match='排版'):editor.save_to(dest)
    editor.close()


def test_batch_uses_editor_coordinates(qt,tmp_path):
    from image_factory.jobs import Queue,sources
    base=Image.new('RGBA',(400,300),'white');overlay=Image.new('RGBA',(80,40),'red')
    base.save(tmp_path/'base.png');overlay.save(tmp_path/'mark.png')
    editor=WatermarkEditor(base,overlay,{'scale':.2,'opacity':.7})
    editor.move_box([83,77,103,51.5]);editor.accept_checked()
    recipe={'mode':'watermark','format':'png','overlay':str(tmp_path/'mark.png'),'options':editor.options,'sources':sources([tmp_path/'base.png',tmp_path/'mark.png'])}
    queue=Queue(tmp_path/'out')
    try:
        batch=queue.plan(recipe,[{'input':str(tmp_path/'base.png'),'__name':'Customer'}])
        result=queue.run(batch);assert result[0][3]=='succeeded'
        assert Image.open(queue.root/result[0][2]).tobytes()==editor.rendered().tobytes()
    finally:queue.close()


@pytest.mark.parametrize('version',[1,2])
def test_preset_versions(qt,tmp_path,monkeypatch,version):
    from image_factory.app import Window,QFileDialog
    options={'scale':.257891,'opacity':.65,'position':'top-left','gap':30,'blend':'normal','tile':False}
    if version==2:options.update(position='custom',offset=[.23,.35])
    path=tmp_path/'preset.json';path.write_text(json.dumps({'version':version,'overlay':'mark.png','options':options}))
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**kw:(str(path),''))
    window=Window();window.load_preset();actual=window.water_options()
    assert actual['scale']==options['scale']
    assert actual['offset']==options.get('offset')
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**kw:(str(path),''))
    window.save_preset();assert json.loads(path.read_text())['options']==actual
    window.close()


@pytest.mark.parametrize('offset',[[float('nan'),0],[0,float('inf')],[3,0],[0]])
def test_invalid_offsets(offset):
    with pytest.raises(ValueError):imaging.watermark_rect((400,300),(80,40),offset=offset)


def test_no_photoshop_is_not_render_verified():
    from image_factory.diagnostics import photoshop_environment
    assert photoshop_environment()['render_verified'] is False
