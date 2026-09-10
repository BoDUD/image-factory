"""Durable job manifest, integrity-checked resume, no silent overwrites."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from PIL import Image
from .data import digest, stable_hash, safe_name, within
from . import imaging
from .photoshop import Photoshop, PhotoshopUncertain


class Queue:
    def __init__(self, output):
        self.root = Path(output).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".factory").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / ".factory/jobs.sqlite3", timeout=10)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, recipe TEXT NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, batch TEXT NOT NULL, payload TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending', sha TEXT, error TEXT);
        """)

    def close(self):
        self.db.close()

    def plan(self, recipe, rows):
        if not rows: raise ValueError("没有待处理记录")
        if len(rows)>50000:raise ValueError('一个批次最多 50000 张')
        if recipe.get('format','png') not in {'png','jpg'}:raise ValueError('格式必须为 png 或 jpg')
        key = stable_hash({"recipe":recipe, "rows":rows})
        if self.db.execute("SELECT 1 FROM batches WHERE id=?", (key,)).fetchone():
            return key
        from .naming import output_name
        date=datetime.now().strftime('%Y%m%d')
        with self.db:
            self.db.execute("INSERT INTO batches VALUES(?,?,?)", (key,json.dumps(recipe,ensure_ascii=False),datetime.now().isoformat()))
            reserved={r[0].casefold() for r in self.db.execute('SELECT path FROM items')}
            for i,row in enumerate(rows):
                child=recipe['recipes'][row['recipe_index']] if recipe['mode']=='multi' else recipe
                values=row['values'] if recipe['mode']=='multi' else row
                name=output_name(recipe.get('naming','{customer}_{index}'),values,Path(child.get('template','image')).stem,i+1,date,recipe.get('group','none'))
                relative = f"{name}.{recipe.get('format','png')}"
                counter=0
                while within(self.root,relative).exists() or relative.casefold() in reserved:
                    counter+=1;relative=f"{name}_{counter}.{recipe.get('format','png')}"
                self.db.execute("INSERT INTO items(id,batch,payload,path) VALUES(?,?,?,?)", (stable_hash([key,i]),key,json.dumps(row,ensure_ascii=False),relative))
                reserved.add(relative.casefold())
        return key

    def batches(self):
        return self.db.execute("SELECT id,created FROM batches ORDER BY created DESC").fetchall()

    def items(self, batch):
        return self.db.execute("SELECT id,payload,path,status,sha,error FROM items WHERE batch=? ORDER BY rowid",(batch,)).fetchall()

    def update(self, item, state, sha=None, error=None):
        with self.db:
            self.db.execute("UPDATE items SET status=?,sha=?,error=? WHERE id=?",(state,sha,error,item))

    def run(self, batch, callback=lambda *args:None, cancelled=lambda:False, paused=lambda:False):
        from .locking import exclusive
        with exclusive(self.root / '.factory/queue.lock'):
            return self._run(batch,callback,cancelled,paused)

    def _run(self, batch, callback, cancelled, paused):
        import time
        recipe = json.loads(self.db.execute("SELECT recipe FROM batches WHERE id=?",(batch,)).fetchone()[0])
        for path,sha in recipe.get("sources",{}).items():
            if not Path(path).is_file() or digest(path)!=sha:
                raise ValueError("输入素材或模板发生变化，请重新创建批次："+path)
        rows=self.items(batch); ps=Photoshop()
        try:
            for index,(key,payload,relative,state,sha,error) in enumerate(rows):
                while paused() and not cancelled(): time.sleep(.1)
                if cancelled(): break
                dest=within(self.root,relative)
                if dest.exists():
                    if sha and digest(dest)==sha:
                        self.update(key,"succeeded",sha);callback(index+1,len(rows),relative,"已校验，跳过");continue
                    self.update(key,"failed",error="目标文件存在但不属于可验证成品，请移走冲突文件")
                    callback(index+1,len(rows),relative,"文件冲突");continue
                temp=within(self.root,f".factory/{key}.{recipe.get('format','png')}")
                self.update(key,"running")
                committed_sha=None
                try:
                    data=json.loads(payload)
                    active=recipe
                    if recipe['mode']=='multi':
                        active=recipe['recipes'][data['recipe_index']];data=data['values']
                    mode=active["mode"]
                    if mode=="psd":
                        ps.call("render",template=active["template"],bindings=active["bindings"],values=data,output=str(temp),format=recipe["format"])
                    elif mode=="template":
                        imaging.save_image(imaging.render_template(active["template"],data),temp,recipe["format"])
                    else:
                        im=imaging.load_image(data["input"])
                        if mode=="watermark":
                            im=imaging.watermark(im,imaging.load_image(recipe["overlay"]),**recipe["options"])
                        elif mode=="transform": im=imaging.transform(im,recipe["operation"],recipe["amount"])
                        else: raise ValueError("不支持的任务类型")
                        imaging.save_image(im,temp,recipe["format"])
                    with Image.open(temp) as check:
                        check.load();imaging.size_ok(*check.size)
                        expected="JPEG" if recipe["format"]=="jpg" else "PNG"
                        if check.format!=expected: raise ValueError("输出格式不符合预期")
                    sha=digest(temp)
                    for path,original_sha in recipe.get('sources',{}).items():
                        if digest(path)!=original_sha:raise ValueError('输入在运行过程中改变，未提交本张成品：'+path)
                    # Store the expected hash before committing. A crash after link can be reconciled.
                    self.update(key,"committing",sha)
                    committed_sha=sha
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest=within(self.root,relative)
                    os.link(temp,dest)  # Atomic, same filesystem, never overwrites an existing destination.
                    temp.unlink()
                    self.update(key,"succeeded",sha)
                    callback(index+1,len(rows),relative,"完成")
                except Exception as e:
                    self.update(key,"failed",sha=committed_sha,error=str(e))
                    callback(index+1,len(rows),relative,str(e))
                    if isinstance(e,PhotoshopUncertain): raise
        finally:
            ps.close()
        return self.items(batch)


def sources(paths):
    return {str(Path(p).resolve()):digest(p) for p in paths}


def combine(entries,format='png',naming='{customer}_{template}_{row_id}',group='customer'):
    if not entries:raise ValueError('请先加入一个模板')
    recipes=[];rows=[];all_sources={}
    for index,(recipe,values) in enumerate(entries):
        if recipe['mode'] not in {'psd','template'}:raise ValueError('组合批次只接受模板任务')
        recipes.append(recipe)
        for path,sha in recipe['sources'].items():
            if path in all_sources and all_sources[path]!=sha:raise ValueError('同一素材的版本不同，请重新加入模板')
            all_sources[path]=sha
        rows.extend({'recipe_index':index,'values':value} for value in values)
    return {'mode':'multi','recipes':recipes,'sources':all_sources,'format':format,'naming':naming,'group':group},rows
