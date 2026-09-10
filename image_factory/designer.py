"""Local template creation, region editing and deterministic row numbering."""
import json
import tempfile
from pathlib import Path
from PIL import Image,ImageDraw
from PySide6.QtWidgets import (QDialog,QFormLayout,QLineEdit,QSpinBox,QDialogButtonBox,
    QHBoxLayout,QPushButton,QFileDialog,QColorDialog)
from .editor import TemplateLayoutEditor
from .data import write_json


def properties(parent,title,fields):
    dialog=QDialog(parent);dialog.setWindowTitle(title);form=QFormLayout(dialog);widgets={}
    for key,label,value,limits in fields:
        if limits:
            widget=QSpinBox();widget.setRange(*limits);widget.setValue(value)
        else:widget=QLineEdit(str(value))
        widgets[key]=widget;form.addRow(label,widget)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText('应用');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
    buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
    if not dialog.exec():return None
    return {k:w.value() if isinstance(w,QSpinBox) else w.text() for k,w in widgets.items()}


class TemplateDesigner(TemplateLayoutEditor):
    def __init__(self,path=None,parent=None):
        self.temp=tempfile.TemporaryDirectory(prefix='image-factory-designer-')
        root=Path(self.temp.name);self.avatar=root/'avatar.png'
        avatar=Image.new('RGBA',(300,300),'#d7eeee');draw=ImageDraw.Draw(avatar)
        draw.ellipse((100,40,200,140),fill='#49998e');draw.ellipse((50,160,250,360),fill='#49998e');avatar.save(self.avatar)
        if path is None:
            path=root/'new.json'
            write_json(path,{'version':1,'size':[900,900],'background':'#e7f5f1','text':[{'field':'customer','box':[80,350,740,120],'size':64,'min_size':12,'color':'#17564b','align':'center'}],'slots':[]})
        spec=json.loads(Path(path).read_text(encoding='utf-8'))
        values={x['field']:'示例文字' for x in spec.get('text',[])}
        values.update({x['field']:str(self.avatar) for x in spec.get('slots',[])});values['__index']=1
        super().__init__(path,values,parent);self.setWindowTitle('模板设计器');self.resize(1020,850)
        row=QHBoxLayout()
        for title,action in [('添加文字',lambda:self.add_region('text')),('添加头像',lambda:self.add_region('slots')),('添加自动编号',lambda:self.add_region('number')),('区域属性',self.edit_properties),('删除区域',self.remove_region),('画布尺寸',self.canvas_size),('背景颜色',self.background_color),('背景图片',self.background_image)]:
            button=QPushButton(title);button.clicked.connect(action);row.addWidget(button)
        self.layout().insertLayout(1,row)
        self.label.setText('示例头像和文字仅供预览；保存后绑定客户名单中的文字列和头像路径列。')

    def rebuild(self,selected=0):
        self.items=[(kind,i) for kind in ['slots','text'] for i in range(len(self.spec.get(kind,[])))]
        self.selector.blockSignals(True);self.selector.clear()
        for kind,i in self.items:
            item=self.spec[kind][i];self.selector.addItem(('自动编号' if 'number' in item else '头像' if kind=='slots' else '文字')+' · '+item['field'])
        self.selector.setCurrentIndex(min(selected,len(self.items)-1));self.selector.blockSignals(False);self.refresh()

    def add_region(self,kind):
        used={item['field'] for items in [self.spec.get('slots',[]),self.spec.get('text',[])] for item in items}
        stem={'text':'text','slots':'avatar','number':'number'}[kind];name=stem;n=1
        while name in used:n+=1;name=stem+str(n)
        w,h=self.spec['size'];box=[round(w*.1),round(h*.1),max(1,round(w*.5)),max(1,round(h*(.3 if kind=='slots' else .15)))]
        item={'field':name,'box':box}
        if kind=='slots':self.values[name]=str(self.avatar)
        else:
            item.update(size=48,min_size=8,color='#17564b');self.values[name]='示例文字'
            if kind=='number':item['number']={'start':1,'step':1,'digits':3,'prefix':''}
        target='slots' if kind=='slots' else 'text';self.spec.setdefault(target,[]).append(item)
        self.rebuild(len(self.spec['slots'])-1 if target=='slots' else len(self.spec.get('slots',[]))+len(self.spec['text'])-1)

    def edit_properties(self):
        kind,i=self.items[self.selector.currentIndex()];item=self.spec[kind][i]
        fields=[('field','名单字段名',item['field'],None)]
        if kind=='text':
            fields.extend([('size','字号',item.get('size',48),(8,500)),('color','文字颜色（如 #17564b）',item.get('color','#17564b'),None)])
            if 'number' in item:
                number=item['number'];fields.extend([(key,label,number.get(key,default),limits) for key,label,default,limits in [('start','起始值',1,(0,999999999)),('step','步长',1,(1,999999)),('digits','最少位数',3,(1,12)),('prefix','前缀','',None)]])
            else:fields.append(('sample','预览文字',self.values[item['field']],None))
        result=properties(self,'区域属性',fields)
        if result is None:return
        name=result.pop('field').strip()
        if not name or name.startswith('__') or any(self.spec[k][j]['field']==name for k,j in self.items if (k,j)!=(kind,i)):
            self.label.setText('字段名不能为空、重复或以 __ 开头');return
        self.values[name]=self.values[item['field']];item['field']=name
        if kind=='text':
            item.update(size=result['size'],color=result['color'])
            if 'number' in item:item['number']={key:result[key] for key in ['start','step','digits','prefix']}
            else:self.values[name]=result['sample']
        self.rebuild(self.selector.currentIndex())

    def remove_region(self):
        if len(self.items)==1:self.label.setText('模板至少保留一个文字、头像或编号区域');return
        kind,i=self.items[self.selector.currentIndex()];del self.spec[kind][i];self.rebuild()

    def canvas_size(self):
        result=properties(self,'画布尺寸（现有区域保持像素位置）',[('w','宽度',self.spec['size'][0],(64,6000)),('h','高度',self.spec['size'][1],(64,6000))])
        if result:self.spec['size']=[result['w'],result['h']];self.canvas.source_size=tuple(self.spec['size']);self.refresh()

    def background_color(self):
        color=QColorDialog.getColor(parent=self)
        if color.isValid():self.spec['background']=color.name();self.spec.pop('background_image',None);self.refresh()

    def background_image(self):
        path,_=QFileDialog.getOpenFileName(self,'背景图片','','图片 (*.png *.jpg *.webp *.bmp)')
        if path:self.spec['background_image']=str(Path(path).resolve());self.refresh()
