"""Prepare multiple templates without reading or mutating UI state."""
import json
from pathlib import Path
from .data import auto_bind,digest,stable_hash
from .jobs import sources
from . import imaging


def prepare_many(paths,headers,rows,customer_path,store,inspect_ps):
    if not rows:raise ValueError('请先导入客户名单，再拖入多个模板')
    entries=[]
    for original in paths:
        path=str(Path(original).resolve());layers=[]
        if Path(path).suffix.lower()=='.psd':
            mode='psd';layers=inspect_ps(path)['layers'];fields=list(dict.fromkeys(l['field'] for l in layers));files=[path]
        else:
            mode='template';fields=imaging.inspect_template(path);files=imaging.dependencies(path)
        if not fields and mode=='psd':raise ValueError(Path(path).name+' 没有可绑定字段')
        mapping=auto_bind(fields,headers);config={}
        config_path=Path(store)/'mappings'/(stable_hash(path)+'.json')
        if config_path.exists():
            config=json.loads(config_path.read_text(encoding='utf-8'))
            if config.get('hash')==digest(path):
                mapping.update({k:v for k,v in config.get('mapping',{}).items() if v in headers})
            else:config={}
        if any(f not in mapping for f in fields):
            raise ValueError(Path(path).name+' 存在未匹配字段，请单独载入、绑定并保存后再加入批次')
        values=[]
        for row in rows:
            value={f:row[mapping[f]] for f in fields}
            if any(not str(v).strip() for v in value.values()):raise ValueError(Path(path).name+' 的必填客户信息为空')
            value['__index']=row['__index'];values.append(value)
        if mode=='template':
            spec=json.loads(Path(path).read_text(encoding='utf-8'))
            for slot in spec.get('slots',[]):
                for row in values:
                    image=Path(row[slot['field']])
                    if not image.is_absolute():image=Path(customer_path).parent/image
                    row[slot['field']]=str(image.resolve());files.append(image)
        files.append(customer_path)
        recipe={'mode':mode,'template':path,'format':'png','sources':sources(files)}
        if mode=='psd':recipe['bindings']=[dict(l,max_width=config.get('widths',{}).get(l['field'],int(l['width'])),min_size=12) for l in layers]
        entries.append((recipe,values))
    return entries
