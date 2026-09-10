import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PIL import Image
from PySide6.QtWidgets import QApplication
from image_factory.designer import TemplateDesigner
from image_factory import imaging
from image_factory.jobs import Queue
from image_factory.templates import prepare_many
from image_factory.data import read_customers


def test_new_template_regions_and_batch(tmp_path):
    app=QApplication.instance() or QApplication([])
    editor=TemplateDesigner();editor.add_region('slots');editor.add_region('number');editor.add_region('text')
    assert len(editor.items)==4
    editor.remove_region();assert len(editor.items)==3
    number=editor.spec['text'][-1];number['number']={'start':98,'step':2,'digits':4,'prefix':'VIP-'}
    assert imaging.number_text(number['number'],1)=='VIP-0098'
    assert imaging.number_text(number['number'],2)=='VIP-0100'
    destination=tmp_path/'template.json';editor.save_to(destination)
    assert set(imaging.inspect_template(destination))=={'customer','avatar'}
    assert 'image-factory-designer-' not in destination.read_text(encoding='utf-8')
    Image.new('RGB',(200,200),'red').save(tmp_path/'a.png')
    csv=tmp_path/'customers.csv';csv.write_text('customer,avatar\nAlice,a.png\nBob,a.png',encoding='utf-8')
    headers,rows=read_customers(csv)
    entries=prepare_many([destination],headers,rows,csv,tmp_path,lambda p:None)
    recipe,values=entries[0];assert values[1]['__index']=='0002'
    queue=Queue(tmp_path/'out')
    try:
        key=queue.plan(recipe,values);items=queue.run(key);assert all(x[3]=='succeeded' for x in items)
        expected=imaging.render_template(destination,values[1]);assert Image.open(queue.root/items[1][2]).tobytes()==expected.tobytes()
        hashes=[x[4] for x in items];assert [x[4] for x in queue.run(key)]==hashes
    finally:queue.close();editor.close()


def test_number_only_template_and_properties(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    editor=TemplateDesigner();editor.add_region('number');editor.selector.setCurrentIndex(0);editor.remove_region()
    assert len(editor.items)==1
    monkeypatch.setattr('image_factory.designer.properties',lambda *a:{'field':'ticket','size':48,'color':'#123456','start':5,'step':3,'digits':4,'prefix':'A'})
    editor.edit_properties();assert editor.spec['text'][0]['number']['step']==3
    path=tmp_path/'number.json';editor.save_to(path);assert imaging.inspect_template(path)==[]
    csv=tmp_path/'customers.csv';csv.write_text('姓名\n甲\n乙',encoding='utf-8')
    headers,rows=read_customers(csv);recipe,values=prepare_many([path],headers,rows,csv,tmp_path,lambda p:None)[0]
    assert imaging.number_text(editor.spec['text'][0]['number'],values[1]['__index'])=='A0008'
    from image_factory.app import Window
    window=Window();window.store=tmp_path/'state';window.store.mkdir();window.load_template(str(path));window.load_customers(str(csv))
    assert len(window.recipe()[1])==2
    window.close();editor.close()
