import json
import zipfile
import pytest
from image_factory.jobs import Queue,combine,sources
from image_factory.demo import create_demo
from image_factory import imaging
from image_factory.delivery import export_batch
from image_factory.naming import output_name


def test_multi_template_resume_and_nested_zip(tmp_path):
    create_demo(tmp_path)
    first=tmp_path/'greeting.json';second=tmp_path/'second.json'
    spec=json.loads(first.read_text());spec['background']='#ffeedd';second.write_text(json.dumps(spec))
    entries=[]
    for template in [first,second]:
        recipe={'mode':'template','template':str(template),'format':'png','sources':sources(imaging.dependencies(template))}
        entries.append((recipe,[{'customer':'Alice','order_id':'001','__index':'0001'},{'customer':'Bob','order_id':'002','__index':'0002'}]))
    recipe,rows=combine(entries)
    q=Queue(tmp_path/'out')
    try:
        batch=q.plan(recipe,rows)
        processed=[]
        q.run(batch,callback=lambda *args:processed.append(args),cancelled=lambda:len(processed)>=1)
        assert sum(x[3]=='succeeded' for x in q.items(batch))==1
        items=q.run(batch);assert len(items)==4 and all(x[3]=='succeeded' for x in items)
        assert all('/' in x[2] for x in items)
        assert q.plan(recipe,rows)==batch
        export_batch(q.root,batch,tmp_path/'out.zip')
        with zipfile.ZipFile(tmp_path/'out.zip') as z:
            assert len(z.namelist())==5 and len(set(z.namelist()))==5
            assert all('/' in x['name'] for x in json.loads(z.read('manifest.json'))['files'])
    finally:q.close()


@pytest.mark.parametrize('pattern',['{customer.__class__}','{unknown}','{index:04d}','{customer!r}','{'])
def test_invalid_naming(pattern):
    with pytest.raises(ValueError):output_name(pattern,{},'template',1,'20260910')


def test_naming_and_classification():
    assert output_name('{date}_{row_id}',{'__index':'0007'},'t',1,'20260910')=='20260910_0007'
    name=output_name('{customer}',{'customer':'../../CON'},'t',1,'20260910','customer')
    assert name.count('/')==1 and not name.startswith('.')
    assert output_name('{customer}',{'customer':'.factory'},'t',1,'20260910','customer').startswith('_.factory/')


def test_invalid_rule_rolls_back(tmp_path):
    q=Queue(tmp_path)
    try:
        with pytest.raises(ValueError):q.plan({'mode':'transform','naming':'{bad}'},[{}])
        assert not q.batches()
    finally:q.close()


def test_bulk_import_matching(tmp_path):
    from image_factory.templates import prepare_many
    from image_factory.data import read_customers
    create_demo(tmp_path);second=tmp_path/'second.json';second.write_bytes((tmp_path/'greeting.json').read_bytes())
    headers,rows=read_customers(tmp_path/'customers.csv')
    entries=prepare_many([tmp_path/'greeting.json',second],headers,rows,tmp_path/'customers.csv',tmp_path,lambda path:None)
    assert len(entries)==2 and entries[0][1][0]['customer']=='今今'
    with pytest.raises(ValueError,match='未匹配'):prepare_many([second],['different'],[{'different':'x','__index':'1'}],tmp_path/'customers.csv',tmp_path,lambda path:None)


def test_unicode_casefold_collisions(tmp_path):
    q=Queue(tmp_path)
    try:
        batch=q.plan({'mode':'transform','naming':'{customer}'},[{'customer':'Änne'},{'customer':'änne'}])
        names=[x[2].casefold() for x in q.items(batch)]
        assert len(set(names))==2
    finally:q.close()
