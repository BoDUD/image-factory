"""Portable template ZIPs with bounded, verified and isolated extraction."""
import hashlib
import json
import os
import re
import tempfile
import uuid
import zipfile
from pathlib import Path
from . import imaging

LIMIT=128*1024*1024


def references(spec):
    for key in ('background_image','frame'):
        if spec.get(key):yield spec,key
    for item in spec.get('text',[]):
        yield item,'font'


def encoded(value):return json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')


def export_bundle(template,destination):
    template=Path(template).resolve();destination=Path(destination).resolve()
    imaging.inspect_template(template)
    spec=json.loads(template.read_text(encoding='utf-8'));files={}
    source_paths={template}
    for owner,key in references(spec):
        source=imaging.asset(template,owner[key]) if owner.get(key) else Path(imaging.font_path() or 'missing-font')
        source=source.resolve();source_paths.add(source)
        if source.stat().st_size>LIMIT:raise ValueError('素材包超过 128 MB 限制')
        data=source.read_bytes();name='assets/'+hashlib.sha256(data).hexdigest()+source.suffix.lower()
        files[name]=data;owner[key]=name
        if len(files)>500 or sum(map(len,files.values()))>LIMIT:raise ValueError('素材数量或大小超过限制')
    if destination in source_paths:raise ValueError('素材包不能覆盖原模板或素材')
    files['template.json']=encoded(spec)
    if sum(map(len,files.values()))>LIMIT:raise ValueError('素材包超过 128 MB 限制')
    files['manifest.json']=encoded({'version':1,'sha256':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()}})
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        archive=Path(temp)/'bundle.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for name,data in files.items():z.writestr(name,data)
        os.replace(archive,destination)
    return destination


def import_bundle(archive,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(names)>512 or len(set(names))!=len(names) or sum(i.file_size for i in infos)>LIMIT:raise ValueError('素材包条目重复、过多或超过 128 MB')
        if any(not re.fullmatch(r'(template|manifest)\.json|assets/[0-9a-f]{64}\.[a-z0-9]{1,8}',n) for n in names):raise ValueError('素材包包含非法路径')
        if any((i.external_attr>>16)&0o170000==0o120000 for i in infos):raise ValueError('素材包不能包含符号链接')
        manifest=json.loads(z.read('manifest.json'));hashes=manifest.get('sha256',{})
        if manifest.get('version')!=1 or set(hashes)!=set(names)-{'manifest.json'} or 'template.json' not in hashes:raise ValueError('素材包清单无效')
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            root=Path(temp)/'content';root.mkdir()
            for name,expected in hashes.items():
                data=z.read(name)
                if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('素材校验失败：'+name)
                target=root/name;target.parent.mkdir(exist_ok=True);target.write_bytes(data)
            spec=json.loads((root/'template.json').read_text(encoding='utf-8'))
            for owner,key in references(spec):
                if owner.get(key) not in hashes or not owner[key].startswith('assets/'):raise ValueError('模板引用了包外素材')
            imaging.inspect_template(root/'template.json')
            final=folder/('template-'+uuid.uuid4().hex);root.rename(final)
    return final/'template.json'
