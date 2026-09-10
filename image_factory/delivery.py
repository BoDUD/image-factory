import json
import os
import uuid
import zipfile
from pathlib import Path
from .jobs import Queue
from .data import digest, within


def export_batch(output,batch,destination):
    q=Queue(output)
    try:items=q.items(batch)
    finally:q.close()
    files=[]
    for _,_,name,status,sha,_ in items:
        if status!='succeeded':continue
        path=within(output,name)
        if not path.exists() or digest(path)!=sha:raise ValueError('成品缺失或被修改：'+name)
        files.append((path,sha))
    if not files:raise ValueError('此批次没有校验成功的成品')
    dest=Path(destination).resolve()
    if any(dest==p.resolve() for p,_ in files):raise ValueError('不能覆盖成品')
    temp=dest.with_name('.'+uuid.uuid4().hex+'.zip')
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
            for path,sha in files:z.write(path,path.name)
            z.writestr('manifest.json',json.dumps({'batch':batch,'files':[{'name':p.name,'sha256':sha} for p,sha in files]},ensure_ascii=False,indent=2))
        os.replace(temp,dest)
    finally:
        if temp.exists():temp.unlink()
    return str(dest)
