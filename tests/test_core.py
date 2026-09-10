import json
import os
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from image_factory.data import read_customers, safe_name, within, digest, auto_bind
from image_factory.demo import create_demo
from image_factory.jobs import Queue, sources
from image_factory import imaging
from image_factory.delivery import export_batch


def test_csv_and_txt(tmp_path):
    p=tmp_path/'names.csv';p.write_text('姓名,编号\n"张,三",001\n李四,002\n',encoding='utf-8-sig')
    headers,rows=read_customers(p)
    assert rows[0]['编号']=='001' and rows[0]['姓名']=='张,三'
    assert auto_bind(['customer','order_id'],headers)=={'customer':'姓名','order_id':'编号'}
    p.write_text('姓名,姓名\na,b',encoding='utf-8')
    with pytest.raises(ValueError):read_customers(p)


def test_xlsx_reject_formula(tmp_path):
    from openpyxl import Workbook
    book=Workbook();book.active.append(['姓名','编号']);book.active.append(['Test','=1+2'])
    path=tmp_path/'names.xlsx';book.save(path)
    with pytest.raises(ValueError,match='公式'):read_customers(path)


def test_paths(tmp_path):
    for unsafe in ['../../secret','/root/file']:
        with pytest.raises(ValueError):within(tmp_path,unsafe)
    assert safe_name('CON')=='_CON'
    assert '/' not in safe_name('../../hi')


def make_batch(tmp_path):
    source=tmp_path/'input.png';Image.new('RGB',(80,60),'red').save(source)
    recipe={'mode':'transform','operation':'mirror','amount':1,'format':'png','sources':sources([source])}
    q=Queue(tmp_path/'out');batch=q.plan(recipe,[{'input':str(source),'__name':'Test'},{'input':str(source),'__name':'Test'}])
    return q,batch,source


def test_run_resume_tamper_and_zip(tmp_path):
    q,batch,source=make_batch(tmp_path)
    try:
        result=q.run(batch);assert all(x[3]=='succeeded' for x in result)
        assert len(list(q.root.glob('*.png')))==2
        q.run(batch);assert len(list(q.root.glob('*.png')))==2
        zip_path=tmp_path/'delivery.zip';export_batch(q.root,batch,zip_path)
        with zipfile.ZipFile(zip_path) as z:assert len(z.namelist())==3
        target=q.root/result[0][2];target.write_bytes(b'changed')
        with pytest.raises(ValueError):export_batch(q.root,batch,zip_path)
        again=q.run(batch);assert again[0][3]=='failed' and target.read_bytes()==b'changed'
        source.write_bytes(b'changed')
        with pytest.raises(ValueError,match='发生变化'):q.run(batch)
    finally:q.close()


def test_cancel_and_commit_recovery(tmp_path):
    q,batch,_=make_batch(tmp_path)
    try:
        assert all(x[3]=='pending' for x in q.run(batch,cancelled=lambda:True))
        item=q.items(batch)[0];dest=q.root/item[2];Image.new('RGB',(80,60)).save(dest)
        q.update(item[0],'committing',digest(dest))
        result=q.run(batch);assert all(x[3]=='succeeded' for x in result)
    finally:q.close()


def test_template_and_alpha(tmp_path):
    create_demo(tmp_path);path=tmp_path/'greeting.json'
    im=imaging.render_template(path,{'customer':'Hello','order_id':'001'})
    assert im.size==(900,900)
    spec=json.loads(path.read_text());spec['text'][0]['box']=[0,0,1,1];path.write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='超出'):imaging.render_template(path,{'customer':'Hello','order_id':'001'})
    base=Image.new('RGBA',(100,100),'red');over=Image.new('RGBA',(20,20),(0,0,255,255))
    result=imaging.watermark(base,over,scale=.2,opacity=1,position='center')
    assert result.getpixel((50,50))==(0,0,255,255)
    assert result.getpixel((0,0))==(255,0,0,255)
    imaging.save_image(Image.new('RGBA',(10,10),(0,0,0,0)),tmp_path/'white.jpg','jpg')
    assert Image.open(tmp_path/'white.jpg').getpixel((0,0))==(255,255,255)


def test_animation_rejected_by_static(tmp_path):
    p=tmp_path/'test.gif'
    Image.new('RGB',(10,10),'red').save(p,save_all=True,append_images=[Image.new('RGB',(10,10),'blue')],duration=100)
    with pytest.raises(ValueError,match='动态图'):imaging.load_image(p)


def test_collage_limits():
    with pytest.raises(ValueError):imaging.collage([Image.new('RGBA',(5,5))],cell=100000)


def test_gif_durations_loop_and_cancel(tmp_path):
    from image_factory.media import watermark_gif
    source=tmp_path/'src.gif';mark=tmp_path/'mark.png';dest=tmp_path/'out.gif'
    Image.new('RGBA',(30,30),'red').save(source,save_all=True,append_images=[Image.new('RGBA',(30,30),'blue')],duration=[80,170],loop=2)
    Image.new('RGBA',(3,3),'white').save(mark)
    watermark_gif(source,mark,dest,{},hold_frame=1,hold_ms=200)
    with Image.open(dest) as im:
        assert im.info['loop']==2 and im.info['duration']==80
        im.seek(1);assert im.info['duration']==370
    before=dest.read_bytes()
    with pytest.raises(ValueError,match='取消'):watermark_gif(source,mark,dest,{},cancelled=lambda:True)
    assert dest.read_bytes()==before


def test_queue_exclusive(tmp_path):
    from image_factory.locking import exclusive
    q,batch,_=make_batch(tmp_path)
    try:
        with exclusive(q.root/'.factory/queue.lock'):
            with pytest.raises(RuntimeError,match='已有任务'):q.run(batch)
    finally:q.close()
