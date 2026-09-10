import hashlib
import json
import os
import zipfile
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication
from image_factory.bundles import export_bundle,import_bundle,encoded
from image_factory.designer import TemplateDesigner
from image_factory import imaging


def test_frame_bundle_survives_move_and_temp_cleanup(tmp_path):
    app=QApplication.instance() or QApplication([])
    designer=TemplateDesigner();designer.preset_frame(4)
    designer.spec['text'][0]['box']=[80,750,740,100]
    original=tmp_path/'source';original.mkdir();template=original/'template.json';designer.save_to(template)
    designer.close();designer.temp.cleanup()
    values={'customer':'Alice','__index':1}
    avatar=tmp_path/'customer.png';Image.new('RGBA',(100,100),'red').save(avatar)
    values.update({s['field']:str(avatar) for s in designer.spec['slots']})
    expected=imaging.render_template(template,values)
    archive=tmp_path/'template.zip';export_bundle(template,archive)
    original.rename(tmp_path/'source-moved')
    moved=import_bundle(archive,tmp_path/'imported')
    assert imaging.render_template(moved,values).tobytes()==expected.tobytes()
    with zipfile.ZipFile(archive) as z:
        assert all(not name.endswith('customer.png') for name in z.namelist())
        spec=json.loads(z.read('template.json'));assert all(x['font'].startswith('assets/') for x in spec['text'])
    second=import_bundle(archive,tmp_path/'imported');assert second.parent!=moved.parent


@pytest.mark.parametrize('count',[1,2,4])
def test_frame_windows_and_overlay_order(tmp_path,count):
    from image_factory.frames import create_frame
    path=tmp_path/'frame.png';boxes=create_frame((900,900),count,path);frame=Image.open(path)
    assert len(boxes)==count
    for x,y,w,h in boxes:
        assert frame.getpixel((x+w//2,y+h//2))[3]==0
        assert frame.getpixel((x-1,y))[3]==255


@pytest.mark.parametrize('mode',['traversal','tamper','external','duplicate'])
def test_reject_invalid_archives(tmp_path,mode):
    spec={'version':1,'size':[100,100],'text':[{'field':'name','font':'C:/outside.ttf','box':[0,0,100,80]}]}
    data=encoded(spec);files={'template.json':data}
    manifest={'version':1,'sha256':{'template.json':hashlib.sha256(data).hexdigest()}}
    if mode=='tamper':files['template.json']=b'changed'
    if mode=='traversal':files['../outside']=b'x'
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as z:
        for name,content in files.items():z.writestr(name,content)
        z.writestr('manifest.json',encoded(manifest))
        if mode=='duplicate':
            with pytest.warns(UserWarning):z.writestr('template.json',data)
    with pytest.raises(ValueError):import_bundle(path,tmp_path/'imports')
    assert not list((tmp_path/'imports').glob('template-*'))


def test_export_will_not_replace_source(tmp_path):
    spec={'version':1,'size':[100,100],'text':[{'field':'name','box':[0,0,100,80]}]}
    path=tmp_path/'template.json';path.write_bytes(encoded(spec));before=path.read_bytes()
    with pytest.raises(ValueError):export_bundle(path,path)
    assert path.read_bytes()==before
